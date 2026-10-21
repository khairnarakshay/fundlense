# ai_intelligence/domain/schemas.py
"""
Typed data-transfer objects for the AI intelligence layer.

These are the ONLY shapes that should cross between Django services and the
LLM/graph layer - no raw Django model instances or querysets should ever be
passed into a provider or a graph node. Keeping this boundary typed is what
Section 3 of the project brief means by "AI services should consume explicitly
defined data-transfer objects... instead of querying arbitrary database
records." Portfolio-specific DTOs (snapshot, analysis result) are added in
Phase 3 alongside the deterministic analysis engine that produces them - this
file only has the provider-facing shapes needed for Phase 2.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """One turn in a conversation sent to an LLM provider."""
    role: MessageRole
    content: str


class GenerationParams(BaseModel):
    """Generation parameters a caller may override; each provider adapter
    translates these into whatever shape its underlying client expects."""
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)
    timeout_seconds: int = Field(default=60, gt=0)
    stop: list[str] | None = None


class GenerationResult(BaseModel):
    """Normalized result from any provider - the orchestration layer never sees
    a provider-specific response object."""
    content: str
    provider: str
    model_id: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None
    raw: dict[str, Any] | None = None   # provider's raw response - populate only where tracing needs it


class ProviderCapability(str, Enum):
    TEXT_GENERATION = "text_generation"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"


class ProviderHealth(BaseModel):
    healthy: bool
    provider: str
    model_id: str
    checked_at: datetime
    detail: str | None = None