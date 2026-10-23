# ai_intelligence/llm/providers/groq.py
"""
Groq Hosted Inference API Adapter.

Uses the OpenAI client SDK targeted at Groq's cloud endpoint.
Provides a highly reliable free-tier option during testing with models
like 'llama3-8b-8192' or 'gemma2-9b-it'.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from openai import OpenAI, OpenAIError, APITimeoutError

from ai_intelligence.domain.exceptions import LLMProviderError, LLMTimeoutError
from ai_intelligence.domain.schemas import (
    ChatMessage, GenerationParams, GenerationResult, ProviderCapability, ProviderHealth,
)
from ai_intelligence.llm.interfaces import LLMProvider, SchemaT


class GroqProvider(LLMProvider):
    """Groq API Adapter using OpenAI client bindings."""

    # Groq natively supports text generation AND JSON structured output modes
    capabilities = frozenset({ProviderCapability.TEXT_GENERATION, ProviderCapability.STRUCTURED_OUTPUT})

    def __init__(self, model_id: str, api_token: str, base_url: str = "https://groq.com", timeout_seconds: int = 60):
        super().__init__(model_id)
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_token,
            timeout=timeout_seconds,
        )
        self._timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "groq"

    def generate(self, messages: list[ChatMessage], params: GenerationParams | None = None) -> GenerationResult:
        params = params or GenerationParams()
        started = time.monotonic()

        try:
            response = self._client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": m.role.value, "content": m.content} for m in messages],
                max_tokens=params.max_tokens,
                temperature=params.temperature,
                stop=params.stop,
            )
        except APITimeoutError as exc:
            raise LLMTimeoutError(f"Groq request timed out after {self._timeout_seconds}s") from exc
        except OpenAIError as exc:
            raise LLMProviderError(f"Groq request failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Unexpected error calling Groq: {exc}") from exc

        latency_ms = (time.monotonic() - started) * 1000
        choice = response.choices[0]
        usage = getattr(response, "usage", None)

        return GenerationResult(
            content=choice.message.content or "",
            provider=self.provider_name,
            model_id=self.model_id,
            finish_reason=getattr(choice, "finish_reason", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            latency_ms=latency_ms,
        )

    def generate_structured(
            self, messages: list[ChatMessage], schema: type[SchemaT],
            params: GenerationParams | None = None,
    ) -> SchemaT:
        """Natively uses Groq's JSON mode capability to enforce the Pydantic schema structure."""
        params = params or GenerationParams()

        # Inject standard instructions asking the model to respect the layout structure
        schema_json = json.dumps(schema.model_json_schema())
        system_instruction = ChatMessage(
            role="system",
            content=f"You must return exclusively a valid JSON object matching this schema: {schema_json}"
        )

        combined_messages = [system_instruction] + messages
        started = time.monotonic()

        try:
            response = self._client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": m.role.value, "content": m.content} for m in combined_messages],
                max_tokens=params.max_tokens,
                temperature=params.temperature,
                response_format={"type": "json_object"},  # Forces Groq to output clean JSON
                stop=params.stop,
            )
            raw_content = response.choices[0].message.content or "{}"
            return schema.model_validate_json(raw_content)

        except OpenAIError as exc:
            raise LLMProviderError(f"Groq structured generation failed: {exc}") from exc
        except Exception as exc:
            raise LLMProviderError(f"Failed parsing validation matching Pydantic schema: {exc}") from exc

    def health_check(self) -> ProviderHealth:
        """A cheap, fast check targeting an ultra-light message completion payload."""
        try:
            self._client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=2,
            )
            return ProviderHealth(healthy=True, timestamp=datetime.now(timezone.utc))
        except Exception as exc:
            return ProviderHealth(
                healthy=False,
                timestamp=datetime.now(timezone.utc),
                error_message=str(exc)
            )
