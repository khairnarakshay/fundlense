# ai_intelligence/memory/long_term.py
"""
Long-term user memory - technique 3 of 3 (see context_window.py).

Stores a FEW short facts the user explicitly stated about themselves (a goal,
a horizon, a preference), so a later conversation does not start from zero.
Deliberately narrow:

  * opt-in by content: extraction only runs for messages that look like a
    statement about goals/horizon/preferences (a cheap regex gate, so most
    turns cost no extra model call);
  * the model only proposes candidates; every candidate is validated in code
    before it is stored (length, category, no identifiers, no instruction-like text);
  * capped per user, de-duplicated, and fully visible and deletable by the
    user through the API.
Portfolio data is never stored here - it stays in its own tables.
"""
from __future__ import annotations

import hashlib
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ai_intelligence.conf import ai_flag, ai_int
from ai_intelligence.domain.guardrails import looks_like_prompt_injection
from ai_intelligence.models import ChatConversation, UserMemory

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 200

_WORTH_EXTRACTING = re.compile(
    r"\b(my goal|my goals|i want to|i'd like to|i would like to|i plan to|i am planning|i'm planning|"
    r"i am saving|i'm saving|saving for|retire\w*|my horizon|years?\s+(from now|horizon)|long[- ]term|"
    r"short[- ]term|i prefer|my preference|risk (appetite|tolerance)|i am (conservative|aggressive)|"
    r"i'm (conservative|aggressive)|remember (that|this))\b", re.IGNORECASE)

# Identifiers that must never be stored as "memory".
_SENSITIVE = re.compile(
    r"[A-Z]{5}\d{4}[A-Z]"            # PAN
    r"|\b\d{9,}\b"                   # account / folio / phone style digit runs
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"     # e-mail
    r"|\b(password|otp|pin)\b", re.IGNORECASE)


class MemoryCandidate(BaseModel):
    category: str = Field(description="One of: goal, horizon, risk_preference, preference, other")
    content: str = Field(description="One short sentence stating the fact in third person, e.g. 'Saving for a house in 5 years'")


class MemoryCandidates(BaseModel):
    memories: list[MemoryCandidate] = Field(default_factory=list)


EXTRACTION_INSTRUCTIONS = (
    "From the user's message, extract ONLY facts the user explicitly stated about their own goals, "
    "investment horizon, risk preference or preferences. Each memory is one short third-person sentence. "
    "Do not infer anything the user did not say. Do not extract portfolio values, fund names held, "
    "personal identifiers, or anything about other people. If there is nothing to extract, return an empty list."
)


def should_attempt_extraction(user_message: str) -> bool:
    return ai_flag("AI_MEMORY_ENABLED") and bool(_WORTH_EXTRACTING.search(user_message))


def normalize_content(text: str) -> str:
    return " ".join(text.lower().split())


def validate_candidate(candidate: MemoryCandidate) -> str | None:
    """The cleaned content to store, or None if the candidate must be rejected."""
    content = " ".join(candidate.content.split())
    if not content or len(content) > MAX_CONTENT_CHARS:
        return None
    if candidate.category not in UserMemory.Category.values:
        return None
    if _SENSITIVE.search(content) or looks_like_prompt_injection(content):
        return None
    return content


def extract_and_store(user, conversation: ChatConversation | None, user_message: str, chat_model) -> int:
    """Returns the number of NEW memories stored. Callers treat any exception as non-fatal."""
    if not should_attempt_extraction(user_message):
        return 0
    result = chat_model.with_structured_output(MemoryCandidates).invoke(
        [SystemMessage(content=EXTRACTION_INSTRUCTIONS), HumanMessage(content=user_message)])
    if isinstance(result, dict):
        result = MemoryCandidates(**result)
    if result is None:
        return 0

    stored = 0
    budget = ai_int("AI_MEMORY_MAX_PER_USER") - UserMemory.objects.filter(user=user).count()
    for candidate in result.memories:
        if budget <= 0:
            logger.info("Memory cap reached for a user; not storing further memories")
            break
        content = validate_candidate(candidate)
        if content is None:
            continue
        digest = hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()
        _, created = UserMemory.objects.get_or_create(
            user=user, content_hash=digest,
            defaults={"category": candidate.category, "content": content, "source_conversation": conversation})
        if created:
            stored += 1
            budget -= 1
    return stored


def memories_for_prompt(user) -> list[str]:
    """The user's newest memories, as short lines for the prompt (count from settings)."""
    return [m.content for m in UserMemory.objects.filter(user=user)[: ai_int("AI_MEMORY_IN_PROMPT")]]