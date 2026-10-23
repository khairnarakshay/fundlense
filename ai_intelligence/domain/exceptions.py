# ai_intelligence/domain/exceptions.py
"""
Exception hierarchy for the AI intelligence layer.

Every exception a caller (a Django view, a service, a graph node) might need
to catch is defined here, so error handling stays consistent and no raw
provider-SDK exception (huggingface_hub's, or a future provider's) ever leaks
up to a view.
"""


class AIIntelligenceError(Exception):
    """Base class for every exception raised by the ai_intelligence app."""


class LLMConfigurationError(AIIntelligenceError):
    """Raised by the provider factory/configuration loader for missing or
    invalid configuration - e.g. an unknown AI_LLM_PROVIDER value, or a
    required setting (model id, token) not set for the selected provider.
    Never results in a silent fallback to another provider or model - the
    brief (Section 5) is explicit that invalid config must be a clear error."""


class LLMProviderError(AIIntelligenceError):
    """Raised when a configured provider's underlying call fails - network
    error, non-2xx response, rate limit, malformed response, etc. Wraps the
    provider SDK's own exception as __cause__ so the original traceback isn't
    lost."""


class LLMTimeoutError(LLMProviderError):
    """The provider call exceeded its configured timeout."""


class CapabilityNotSupportedError(AIIntelligenceError):
    """Raised when a caller asks a provider to do something it doesn't support
    (e.g. structured output, streaming) for the configured provider/model, so
    the orchestration layer can handle it explicitly rather than the call
    failing deep inside the adapter in a confusing way."""


class StructuredOutputError(AIIntelligenceError):
    """Raised when a model's output could not be parsed/validated against the
    requested schema, even after an adapter's own retry (see
    providers/huggingface.py's JSON-mode fallback)."""