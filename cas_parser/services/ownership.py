# cas_parser/services/ownership.py
"""
Reject a CAS statement that isn't the logged-in user's own - checked by PAN, not by
email, since the same person can legitimately hold investments registered under
several different email addresses but their PAN never changes.
"""
import logging

logger = logging.getLogger(__name__)


def _normalize_pan(pan):
    return (pan or "").strip().upper()


def extract_statement_pans(parsed):
    """Every distinct, non-blank PAN reported across the statement's folios.
    (investor_info in casparser's output has no PAN field - PAN is per-folio only,
    see ingest.py's module docstring for the confirmed JSON shape.)"""
    pans = set()
    for folio in parsed.get("folios") or []:
        pan = _normalize_pan(folio.get("PAN"))
        if pan:
            pans.add(pan)
    return pans


def get_user_pan(user):
    """
    ASSUMPTION: the logged-in user's own verified PAN is stored at `user.pan`.
    This is the ONE place to change if it actually lives elsewhere (e.g.
    `user.profile.pan`, a separate KYC model, etc).
    """
    return _normalize_pan(getattr(user, "pan", ""))


def save_user_pan(user, pan):
    """Learns the user's PAN from their first successful upload, so future uploads
    can be checked without asking them to enter it separately. Same ASSUMPTION as
    get_user_pan - adjust together if PAN lives somewhere other than `user.pan`."""
    user.pan = pan
    user.save(update_fields=["pan"])


def mask_pan(pan):
    """ABCDE1234F -> AB*****4F - for error messages, so we're not echoing a full PAN
    back into an HTTP response / log line unnecessarily."""
    pan = _normalize_pan(pan)
    if len(pan) < 4:
        return "*" * len(pan)
    return pan[:2] + "*" * (len(pan) - 3) + pan[-1]


def check_statement_ownership(user, parsed):
    """
    Returns (allowed: bool, message: str | None).

    - user has no PAN on file yet + statement reports exactly one PAN -> learn it,
      allow. (First upload establishes the user's PAN.)
    - user has no PAN on file + statement reports zero or multiple PANs -> can't
      verify either way; allow through rather than blocking a legitimate user, but
      log it so the gap is visible.
    - user has a PAN on file -> statement must report that PAN on at least one folio
      (a joint folio with a different co-applicant PAN is fine, as long as the user's
      own PAN appears somewhere in the statement). Otherwise reject.
    """
    statement_pans = extract_statement_pans(parsed)
    user_pan = get_user_pan(user)

    if not user_pan:
        if len(statement_pans) == 1:
            save_user_pan(user, next(iter(statement_pans)))
        else:
            logger.warning("Could not establish PAN for user_id=%s from upload "
                           "(found %d distinct PAN(s) in statement)", user.id, len(statement_pans))
        return True, None

    if statement_pans and user_pan not in statement_pans:
        reported = mask_pan(next(iter(statement_pans)))
        return False, (
            f"This statement belongs to PAN {reported}, which doesn't match your "
            f"registered PAN. Please upload your own CAS statement."
        )

    return True, None