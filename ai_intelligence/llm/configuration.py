# ai_intelligence/llm/configuration.py
"""
Reads AI_LLM_* settings from Django settings (your project populates those from
.env via python-dotenv - see the settings.py block in the project notes).
Centralized here so the factory and every provider adapter share one source of
truth and one validation point, instead of each reading os.environ separately.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from ai_intelligence.domain.exceptions import LLMConfigurationError

SUPPORTED_PROVIDERS = {"huggingface"}   # grows as llm/providers/ gains adapters


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model_id: str
    base_url: str | None
    api_token: str | None
    temperature: float
    timeout_seconds: int


def load_llm_config() -> LLMConfig:
    """
    Reads and validates configuration. Raises LLMConfigurationError immediately
    for anything missing or invalid - per the brief, invalid config must be a
    clear error, never a silent fallback to a different provider or model.
    """
    provider = (getattr(settings, "AI_LLM_PROVIDER", "") or "").strip().lower()
    if not provider:
        raise LLMConfigurationError("AI_LLM_PROVIDER is not set.")
    if provider not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(
            f"Unknown AI_LLM_PROVIDER={provider!r}. Supported: {sorted(SUPPORTED_PROVIDERS)}")

    model_id = (getattr(settings, "AI_LLM_MODEL_ID", "") or "").strip()
    if not model_id:
        raise LLMConfigurationError(
            "AI_LLM_MODEL_ID is not set - this adapter works with any model id "
            "the configured token has access to, but one must be provided.")

    api_token = (getattr(settings, "AI_LLM_API_TOKEN", "") or "").strip() or None
    if provider == "huggingface" and not api_token:
        raise LLMConfigurationError(
            "AI_LLM_API_TOKEN is required for provider='huggingface' (hosted Inference API).")

    try:
        temperature = float(getattr(settings, "AI_LLM_TEMPERATURE", 0.1))
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"AI_LLM_TEMPERATURE must be a number: {exc}") from exc

    try:
        timeout_seconds = int(getattr(settings, "AI_LLM_TIMEOUT_SECONDS", 60))
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(f"AI_LLM_TIMEOUT_SECONDS must be an integer: {exc}") from exc
    if timeout_seconds <= 0:
        raise LLMConfigurationError("AI_LLM_TIMEOUT_SECONDS must be positive.")

    return LLMConfig(
        provider=provider,
        model_id=model_id,
        base_url=(getattr(settings, "AI_LLM_BASE_URL", "") or "").strip() or None,
        api_token=api_token,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )