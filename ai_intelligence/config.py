# ai_intelligence/conf.py
"""
Every tunable of the AI layer in one place. Each value is read from Django
settings (which your settings.py fills from .env via dotenv) and falls back to
the default below, so a missing setting never crashes the app - except the few
that are genuinely required (see llm/configuration.py and
embeddings/factory.py, which raise clear configuration errors instead).

Values arriving from environment variables are strings, so the typed accessors
below cast them; a malformed value raises ImproperlyConfigured at use time
rather than silently using a wrong number.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS: dict[str, object] = {
    # --- chat / conversation memory ---
    "AI_CHAT_MAX_MESSAGE_CHARS": 2000,
    "AI_CHAT_RECENT_TOKEN_BUDGET": 3000,     # max tokens of recent history placed in a prompt
    "AI_CHAT_SUMMARIZE_AFTER_TOKENS": 2500,  # fold old turns into the summary once unsummarized history exceeds this
    "AI_CHAT_KEEP_RECENT_MESSAGES": 6,       # newest messages that are never folded into the summary
    "AI_CHAT_MAX_GENERATION_ATTEMPTS": 2,    # 1 first try + at most 1 corrected retry
    "AI_CHAT_RETENTION_DAYS": 0,             # 0 = keep forever; used by `manage.py prune_conversations`
    # --- long-term memory ---
    "AI_MEMORY_ENABLED": True,
    "AI_MEMORY_MAX_PER_USER": 50,
    "AI_MEMORY_IN_PROMPT": 8,
    # --- RAG ---
    "AI_RAG_TOP_K": 4,
    "AI_RAG_MAX_DISTANCE": 0.6,              # cosine distance; lower = more similar; chunks above this are dropped
    "AI_RAG_CHUNK_SIZE": 1000,
    "AI_RAG_CHUNK_OVERLAP": 150,
    "AI_RAG_MAX_DOCUMENT_CHARS": 2_000_000,
    # --- embeddings ---
    "AI_EMBEDDING_PROVIDER": "",             # fake | fastembed | gemini  (empty = RAG disabled, chat still works)
    "AI_EMBEDDING_MODEL_ID": "",
    "AI_EMBEDDING_DIMENSIONS": 384,          # baked into the vector column by the migration - see README before changing
    "AI_EMBEDDING_API_TOKEN": "",
    # --- LangSmith (privacy-safe by default; see observability/langsmith.py) ---
    "AI_LANGSMITH_TRACING": False,
    "AI_LANGSMITH_API_KEY": "",
    "AI_LANGSMITH_PROJECT": "fundlense-development",
    "AI_LANGSMITH_ENDPOINT": "",
    "AI_LANGSMITH_ALLOW_CONTENT": False,     # True = send prompts/answers to LangSmith. Synthetic data only.
}


def ai_setting(name: str):
    return getattr(settings, name, DEFAULTS[name])


def ai_int(name: str) -> int:
    try:
        return int(ai_setting(name))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(f"{name} must be an integer: {exc}") from exc


def ai_float(name: str) -> float:
    try:
        return float(ai_setting(name))
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(f"{name} must be a number: {exc}") from exc


def ai_flag(name: str) -> bool:
    value = ai_setting(name)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def ai_str(name: str) -> str:
    return str(ai_setting(name) or "").strip()