# ai_intelligence/views.py
"""
Phase 3: deterministic portfolio analysis endpoint. No LLM call yet - see
application/portfolio_analysis_service.py.

NOTE: `api_response` import path below is a guess (`core.utils`) based on the
function body you shared, not a confirmed location - adjust to wherever it
actually lives in your project; everything else in this file is independent
of that.
"""
import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from ai_intelligence.application.chat_service import ChatInputError, ask_portfolio_question
from ai_intelligence.application.portfolio_analysis_service import get_portfolio_analysis
from ai_intelligence.domain.exceptions import (
    CapabilityNotSupportedError, LLMConfigurationError, LLMProviderError, LLMTimeoutError,
)
from core.response import api_response   # <- confirm/adjust this import path

logger = logging.getLogger(__name__)


class ChatAPIView(APIView):
    """
    POST /api/ai/chat/   body: {"question": "..."}
    Single-turn, portfolio-grounded chat. No conversation persistence yet
    (Phase 6) - every call is grounded fresh in the user's current analysis.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = request.data.get("question") or request.data.get("message")

        try:
            result = ask_portfolio_question(request.user, question)
        except ChatInputError as exc:
            return api_response(400, str(exc))
        except CapabilityNotSupportedError as exc:
            # the configured provider/model can't do something this call needed -
            # a config issue, not a transient failure, so log it for visibility
            logger.error("AI chat capability not supported: %s", exc)
            return api_response(400, str(exc))
        except LLMConfigurationError as exc:
            logger.error("AI chat misconfigured: %s", exc)
            return api_response(500, "The AI assistant is not configured correctly.")
        except LLMTimeoutError:
            return api_response(504, "The AI assistant took too long to respond. Please try again.")
        except LLMProviderError:
            logger.exception("AI provider error during chat for user_id=%s", request.user.id)
            return api_response(502, "The AI assistant is temporarily unavailable. Please try again.")
        except Exception:                                   # noqa: BLE001
            logger.exception("Unexpected error during chat for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong.")

        return api_response(200, "Data fetched successfully", data=result)


class PortfolioAnalysisAPIView(APIView):
    """POST /api/ai/portfolio-analysis/ - deterministic analysis, no LLM involved yet."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            result = get_portfolio_analysis(request.user)
        except Exception:                                   # noqa: BLE001
            logger.exception("portfolio analysis failed for user_id=%s", request.user.id)
            return api_response(500, "Something went wrong while analyzing the portfolio")

        # pydantic's model_dump(mode="json") gives JSON-safe types (dates/datetimes
        # as ISO strings) directly - no DRF serializer needed for this response.
        return api_response(200, "Data fetched successfully", data=result.model_dump(mode="json"))