# ai_intelligence/llm/providers/huggingface.py
"""
Hugging Face hosted Inference API adapter.

Uses huggingface_hub's InferenceClient against the chat-completions-compatible
endpoint. Works with any model_id the configured token has access to - this
adapter does not hardcode or validate a specific model; see configuration.py
for required settings (AI_LLM_MODEL_ID, AI_LLM_API_TOKEN). base_url (optional)
lets the same adapter point at a self-hosted Inference Endpoint instead of the
public hosted API, without any code change.

Structured output is NOT a native capability here - many hosted HF models
don't expose a true JSON mode/response_format through the Inference API.
Instead this adapter implements a prompt-based JSON-mode fallback: the schema
is described to the model, its output is parsed as JSON and validated against
the pydantic schema, and on failure the adapter retries once with the
validation error fed back to the model. If it still fails, StructuredOutputError
is raised rather than returning an invalid or guessed object.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError
from pydantic import BaseModel, ValidationError

from ai_intelligence.domain.exceptions import LLMProviderError, LLMTimeoutError, StructuredOutputError
from ai_intelligence.domain.schemas import (
    ChatMessage, GenerationParams, GenerationResult, ProviderCapability, ProviderHealth,
)
from ai_intelligence.llm.interfaces import LLMProvider

_STRUCTURED_OUTPUT_RETRIES = 1   # one retry with the validation error fed back, then give up


class HuggingFaceProvider(LLMProvider):
    """Hosted HF Inference API (or a self-hosted Inference Endpoint via base_url),
    through huggingface_hub.InferenceClient."""

    capabilities = frozenset({ProviderCapability.TEXT_GENERATION, ProviderCapability.STRUCTURED_OUTPUT})

    def __init__(self, model_id: str, api_token: str, base_url: str | None = None,
                timeout_seconds: int = 60, hf_inference_provider: str | None = None):
        super().__init__(model_id)
        # "provider" here is HF's Inference Providers backend (hf-inference, groq,
        # together, ...) - NOT our own AI_LLM_PROVIDER abstraction ("huggingface").
        # Explicit, not "auto": auto-routing failed with "not supported by any
        # provider you have enabled" during setup - being explicit is also more
        # predictable for a production deployment anyway.
        self._client = InferenceClient(
            model=base_url or model_id, token=api_token, timeout=timeout_seconds,
            provider=hf_inference_provider or "hf-inference",
        )
        self._timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "huggingface"

    def generate(self, messages: list[ChatMessage], params: GenerationParams | None = None) -> GenerationResult:
        params = params or GenerationParams()
        started = time.monotonic()
        try:
            response = self._client.chat_completion(
                messages=[{"role": m.role.value, "content": m.content} for m in messages],
                max_tokens=params.max_tokens,
                temperature=params.temperature,
                stop=params.stop,
            )
        except TimeoutError as exc:
            raise LLMTimeoutError(f"Hugging Face request timed out after {self._timeout_seconds}s") from exc
        except HfHubHTTPError as exc:
            raise LLMProviderError(f"Hugging Face request failed: {exc}") from exc
        except Exception as exc:                            # noqa: BLE001 - last-resort normalization
            raise LLMProviderError(f"Unexpected error calling Hugging Face: {exc}") from exc

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

    def generate_structured(self, messages, schema: type[BaseModel], params: GenerationParams | None = None):
        params = params or GenerationParams()
        schema_json = json.dumps(schema.model_json_schema())
        instruction = ChatMessage(
            role="system",
            content=("Respond with ONLY a single JSON object matching this JSON Schema, "
                     f"no prose, no markdown fences:\n{schema_json}"),
        )
        working_messages = [instruction, *messages]

        last_error: Exception | None = None
        for _ in range(_STRUCTURED_OUTPUT_RETRIES + 1):
            result = self.generate(working_messages, params)
            try:
                parsed = _extract_json(result.content)
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                working_messages = [
                    instruction,
                    *messages,
                    ChatMessage(role="assistant", content=result.content),
                    ChatMessage(role="user", content=f"That was not valid JSON matching the schema: {exc}. "
                                                     f"Reply again with ONLY the corrected JSON object."),
                ]

        raise StructuredOutputError(
            f"Model {self.model_id!r} did not produce valid structured output after "
            f"{_STRUCTURED_OUTPUT_RETRIES + 1} attempt(s): {last_error}")

    def health_check(self) -> ProviderHealth:
        try:
            self.generate(
                [ChatMessage(role="user", content="ping")],
                GenerationParams(max_tokens=1, timeout_seconds=min(self._timeout_seconds, 10)),
            )
            return ProviderHealth(healthy=True, provider=self.provider_name, model_id=self.model_id,
                                  checked_at=datetime.now(timezone.utc))
        except Exception as exc:                            # noqa: BLE001 - health_check must never raise
            return ProviderHealth(healthy=False, provider=self.provider_name, model_id=self.model_id,
                                  checked_at=datetime.now(timezone.utc), detail=str(exc))


def _extract_json(text: str) -> dict:
    """Models often wrap JSON in markdown fences despite instructions - strip
    those before parsing rather than failing immediately."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)