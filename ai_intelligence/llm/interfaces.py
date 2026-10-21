# ai_intelligence/llm/interfaces.py
"""
The provider-independent contract every LLM adapter must implement. Nothing
outside this file and factory.py should ever import a provider-specific
module (huggingface_hub, openai, etc.) directly - see Section 5 of the
project brief: "a different supported LLM provider can be selected through
configuration without rewriting business services."
"""
from __future__ import annotations

import abc
from typing import TypeVar

from pydantic import BaseModel

from ai_intelligence.domain.exceptions import CapabilityNotSupportedError
from ai_intelligence.domain.schemas import (
    ChatMessage, GenerationParams, GenerationResult, ProviderCapability, ProviderHealth,
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMProvider(abc.ABC):
    """Abstract base for every LLM provider adapter."""

    #: Capabilities this provider instance actually supports. An adapter must
    #: set this accurately - the orchestration layer checks it via supports()
    #: before calling generate_structured()/stream(), rather than discovering
    #: the lack of support from a runtime failure deep in a graph node.
    capabilities: frozenset[ProviderCapability] = frozenset({ProviderCapability.TEXT_GENERATION})

    def __init__(self, model_id: str, **config):
        self.model_id = model_id
        self._config = config

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Short identifier, e.g. 'huggingface' - used in GenerationResult and logs."""

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities

    @abc.abstractmethod
    def generate(self, messages: list[ChatMessage], params: GenerationParams | None = None) -> GenerationResult:
        """Plain text generation. Every provider must implement this."""

    def generate_structured(
        self, messages: list[ChatMessage], schema: type[SchemaT],
        params: GenerationParams | None = None,
    ) -> SchemaT:
        """
        Default: raises CapabilityNotSupportedError. A provider that can do
        structured output (natively or via a JSON-mode fallback) overrides
        this. Kept as an explicit opt-in, not a silent best-effort default,
        per the brief's instruction not to assume every model supports
        structured output.
        """
        raise CapabilityNotSupportedError(
            f"{self.provider_name} provider for model {self.model_id!r} does not support structured output.")

    def stream(self, messages: list[ChatMessage], params: GenerationParams | None = None):
        """Default: raises CapabilityNotSupportedError. A provider that
        supports streaming overrides this to yield text chunks."""
        raise CapabilityNotSupportedError(
            f"{self.provider_name} provider for model {self.model_id!r} does not support streaming.")

    @abc.abstractmethod
    def health_check(self) -> ProviderHealth:
        """
        A cheap, fast check that the provider/model is reachable and
        configured correctly. Must NEVER raise - returns
        ProviderHealth(healthy=False, ...) on failure instead, so callers
        (e.g. a future GET /api/ai/status/) can report status without a
        try/except at every call site.
        """