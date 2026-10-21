# ai_intelligence/llm/factory.py
"""
Provider factory - the ONLY place that maps a configured provider name to a
concrete adapter class. Add a new provider by adding one entry to
_register_providers() and a new module under providers/ - nothing else in
this app should construct a provider adapter directly.
"""
from __future__ import annotations

from ai_intelligence.domain.exceptions import LLMConfigurationError
from ai_intelligence.llm.configuration import LLMConfig, load_llm_config
from ai_intelligence.llm.interfaces import LLMProvider

_PROVIDERS: dict[str, type] = {}


def _register_providers() -> None:
    """
    Provider SDK imports are deferred into this function (called lazily, on
    first use) rather than at module level, so importing factory.py doesn't
    require every provider's SDK to be installed - only the one actually
    configured for this deployment.
    """
    if _PROVIDERS:
        return
    from ai_intelligence.llm.providers.huggingface import HuggingFaceProvider
    _PROVIDERS["huggingface"] = HuggingFaceProvider


def get_llm_provider(config: LLMConfig | None = None) -> LLMProvider:
    """
    Returns a configured, ready-to-use LLMProvider instance for whatever
    model_id is in config (or in Django settings, if config is omitted).
    Raises LLMConfigurationError for any invalid/missing configuration -
    never falls back to a different provider or model.
    """
    _register_providers()
    config = config or load_llm_config()

    provider_cls = _PROVIDERS.get(config.provider)
    if provider_cls is None:
        raise LLMConfigurationError(
            f"No adapter registered for provider={config.provider!r}. "
            f"Available: {sorted(_PROVIDERS)}")

    if config.provider == "huggingface":
        return provider_cls(
            model_id=config.model_id,
            api_token=config.api_token,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
        )

    # Defensive: a provider registered in _PROVIDERS but not wired up above is
    # a bug in this factory, not a user configuration error.
    raise NotImplementedError(f"Factory wiring missing for provider={config.provider!r}")