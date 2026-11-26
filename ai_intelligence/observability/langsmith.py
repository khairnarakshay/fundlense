# ai_intelligence/observability/langsmith.py
"""
LangSmith tracing, configured so that turning it on cannot leak financial data.

Defaults are SAFE: tracing is off unless AI_LANGSMITH_TRACING is true AND an API
key is set. When it is on, prompts and answers are HIDDEN from the trace
(LANGSMITH_HIDE_INPUTS / LANGSMITH_HIDE_OUTPUTS = "true", verified against
langsmith's source) unless AI_LANGSMITH_ALLOW_CONTENT is explicitly true - which
should only ever be done with synthetic data. You still get the structure of each
run: which graph nodes ran, how long each took, errors, token usage.

Trace metadata never contains a user id, PAN or folio: conversations are
referenced by a keyed pseudonym (HMAC of the id with SECRET_KEY), which lets you
correlate runs of one conversation without identifying anyone.

What can still reach LangSmith (be aware): run names, tags, timings, token
counts, model names, and error TEXT. Exception messages are not covered by the
hide flags, so keep exception messages free of user content.

Configure with the AI_LANGSMITH_* settings only. configure_tracing() deliberately
overrides LANGSMITH_*/LANGCHAIN_* variables set directly in the environment, so
one setting controls it and a stray variable cannot switch tracing on.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

from django.conf import settings

from ai_intelligence.conf import ai_flag, ai_str

logger = logging.getLogger(__name__)


def configure_tracing() -> bool:
    """Apply the tracing settings to the environment. Returns True if tracing is on."""
    api_key = ai_str("AI_LANGSMITH_API_KEY")
    if not ai_flag("AI_LANGSMITH_TRACING"):
        _set_tracing("false")
        return False
    if not api_key:
        logger.warning("AI_LANGSMITH_TRACING is true but AI_LANGSMITH_API_KEY is empty; tracing stays OFF")
        _set_tracing("false")
        return False

    _set_tracing("true")
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = ai_str("AI_LANGSMITH_PROJECT") or "fundlense-development"
    if ai_str("AI_LANGSMITH_ENDPOINT"):
        os.environ["LANGSMITH_ENDPOINT"] = ai_str("AI_LANGSMITH_ENDPOINT")

    hide = "false" if ai_flag("AI_LANGSMITH_ALLOW_CONTENT") else "true"
    os.environ["LANGSMITH_HIDE_INPUTS"] = hide
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = hide
    if hide == "false":
        logger.warning("LangSmith will receive prompts and answers (AI_LANGSMITH_ALLOW_CONTENT=true). "
                       "Use synthetic data only.")
    return True


def _set_tracing(value: str) -> None:
    # langsmith reads TRACING_V2 first, then TRACING, in the LANGSMITH then LANGCHAIN namespaces.
    for name in ("LANGSMITH_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
        os.environ[name] = value


def pseudonym(kind: str, value) -> str:
    """Stable, non-reversible reference for correlating runs without identifying a person."""
    return hmac.new(settings.SECRET_KEY.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:16]


def trace_config(conversation_id, run_name: str) -> dict:
    """The `config` passed to graph.invoke(): names the run and attaches ONLY pseudonymous metadata."""
    return {"run_name": run_name, "tags": ["fundlense-ai"],
            "metadata": {"conversation_ref": pseudonym("conversation", conversation_id), "graph": "chat_v1"}}