# cas_parser/api/views.py
import logging


from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from cas_parser.models import CASStatement
from cas_parser.services.hashing import compute_file_hash
from cas_parser.services.ingest import process_cas_statement
from core.response import api_response   # reuse the same {st, msg, data} envelope everywhere

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"application/pdf"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024   # 25 MB - CAS PDFs are small; this just stops abuse


class CASStatementUploadAPIView(APIView):
    """
    POST /api/cas/upload/   (multipart/form-data)
      file            - required, the CAS/CDSL/NSDL PDF
      password        - required, PDF open-password
      statement_type  - optional: CAS | CDSL | NSDL (defaults to CAS)

    Re-upload behaviour:
      - the exact same file (same sha256) re-uploaded by the same user is detected via
        CASStatement's existing UniqueConstraint(user, file_hash) and is NOT reprocessed -
        the previous result is returned as-is.
      - a DIFFERENT file (old statement, a newer statement, an overlapping period, a
        corrected re-download) is processed fully and stored as its own CASStatement/
        CASFolio/CASSchemeHolding snapshot. Transactions are deduped at the individual-
        transaction level across ALL of the user's holdings for that ISIN (see
        services/ingest.py), so overlapping periods never double-count on the dashboard.
      - a statement with no transaction rows (a Summary Statement, not Detailed) is
        rejected with a 422 and a message telling the user what to upload instead.
    """

    permission_classes = [IsAuthenticated]

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        print(request.data)
        uploaded_file = request.FILES.get("file")
        password = request.data.get("password") or ""
        statement_type = (request.data.get("statement_type") or CASStatement.StatementType.CAS).upper()

        if not uploaded_file:
            return api_response(400, "file is required")
        if not password:
            return api_response(400, "password is required")
        if uploaded_file.content_type not in ALLOWED_CONTENT_TYPES and not uploaded_file.name.lower().endswith(".pdf"):
            return api_response(400, "Only PDF files are accepted")
        if uploaded_file.size > MAX_UPLOAD_BYTES:
            return api_response(400, "File is too large")
        if statement_type not in CASStatement.StatementType.values:
            statement_type = CASStatement.StatementType.UNKNOWN

        try:
            file_hash = compute_file_hash(uploaded_file)
        except Exception:                                   # noqa: BLE001
            logger.exception("Failed hashing uploaded CAS file for user_id=%s", request.user.id)
            return api_response(500, "Could not read the uploaded file")

        existing = (CASStatement.objects
                   .filter(user=request.user, file_hash=file_hash)
                   .order_by("-created_at").first())
        if existing:
            if existing.processing_status == CASStatement.ProcessingStatus.COMPLETED:
                return api_response(200, "This statement was already uploaded and processed.",
                                    data=_statement_summary(existing))
            # Previously uploaded but failed (e.g. wrong password that time) - let the
            # user retry with the password they just supplied, reusing the same row.
            ok, message, http_status = process_cas_statement(existing, password)
            return api_response(http_status, message, data=_statement_summary(existing))

        try:
            statement = CASStatement.objects.create(
                user=request.user,
                statement_type=statement_type,
                source_file=uploaded_file,
                file_name=uploaded_file.name,
                file_hash=file_hash,
                processing_status=CASStatement.ProcessingStatus.PENDING,
            )
        except Exception:                                   # noqa: BLE001 - e.g. a race on the unique constraint
            logger.exception("Failed creating CASStatement for user_id=%s", request.user.id)
            return api_response(500, "Could not save the uploaded file")

        ok, message, http_status = process_cas_statement(statement, password)
        return api_response(http_status, message, data=_statement_summary(statement))


def _statement_summary(statement):
    return {
        "statement_id": statement.id,
        "status": statement.processing_status,
        "statement_from": statement.statement_from,
        "statement_to": statement.statement_to,
        "investor_name": statement.investor_name,
        "folio_count": statement.folios.count(),
        "scheme_count": sum(f.scheme_holdings.count() for f in statement.folios.all()),
    }