# ai_intelligence/domain/guardrails.py
"""
Code-level output checks: the part of "the AI never gives advice" that does
NOT depend on the model obeying a prompt. The prompt rules in policies.py ask
nicely; this runs after the model has answered and removes what slipped
through - it was added after the first live report produced "the investor may
want to consider diversification" despite the prompt saying not to.

Scope, stated honestly: this is a keyword heuristic, applied only to the
`points_to_review` list, where every item is supposed to be a bare factual
observation (so action words are never legitimate there). It is NOT applied
to the free-text sections, where words like "should" can appear innocently
("the figure should be read as a proxy") and a keyword filter would give
false positives. Checking those properly is a job for the LangGraph validation
step (Phase 5).
"""
from __future__ import annotations

import re

# Deliberately excludes "suggest*" ("the index suggests high concentration" is
# a normal neutral observation) and "diversification" (the noun is neutral;
# only the verb "diversify" is an instruction).
_ADVICE_PATTERN = re.compile(
    r"\b(consider|should|may want to|might want to|recommend\w*|advis(e|ed|ing)|"
    r"rebalanc\w*|diversify|buy|sell|switch|redeem|invest more)\b",
    re.IGNORECASE,
)


def looks_like_advice(text: str) -> bool:
    return bool(_ADVICE_PATTERN.search(text))


def drop_advice_items(items: list[str]) -> tuple[list[str], int]:
    """Returns (items with advice-like entries removed, how many were removed)."""
    kept = [item for item in items if not looks_like_advice(item)]
    return kept, len(items) - len(kept)

_INJECTION_PATTERN = re.compile(
    r"("
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions|"
    r"reveal\s+(your\s+)?system\s+prompt|"
    r"</?knowledge_base>|"
    r"\bSYSTEM\s*:"
    r")",
    re.IGNORECASE,
)


def looks_like_prompt_injection(text: str) -> bool:
    """Returns True if text contains prompt-injection markers."""
    return bool(_INJECTION_PATTERN.search(text))
