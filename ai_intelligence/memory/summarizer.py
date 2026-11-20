# ai_intelligence/memory/summarizer.py
"""
Rolling summary - technique 2 of 3 (see context_window.py).

When the not-yet-summarized history grows past a threshold, everything except
the newest few messages is folded into ChatConversation.summary, and
`summary_through_sequence` records how far the summary reaches. The next prompt
then contains: summary + the recent messages verbatim.

The summary is told NOT to record portfolio figures: those change daily and are
re-read from the database on every turn, so a number frozen into a summary would
only go stale (the brief: authoritative financial data must not be replaced by
conversational memory).
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from ai_intelligence.models import ChatConversation, ChatMessage

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 3000

SUMMARY_INSTRUCTIONS = (
    "You maintain a compact running summary of a chat between an investor and the Fundlense assistant. "
    "Merge the NEW MESSAGES into the EXISTING SUMMARY and return the updated summary only.\n"
    "Keep: what the user is trying to understand or achieve, topics already explained, decisions or "
    "preferences the user stated, and questions still open.\n"
    "Do NOT keep: portfolio values, NAVs, returns, percentages or any other figures (they are re-read "
    "fresh every turn and would only go stale), and never include personal identifiers.\n"
    f"Write plain sentences, under {MAX_SUMMARY_CHARS // 6} words."
)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def maybe_summarize(conversation: ChatConversation, chat_model, *, trigger_tokens: int,
                    keep_recent: int) -> bool:
    """
    Fold old messages into the summary if the unsummarized history is above
    `trigger_tokens`. Returns True when the summary was updated.

    The write is a compare-and-set on summary_through_sequence, so two requests
    summarizing the same conversation cannot overwrite each other with a stale
    result. Callers treat failures as non-fatal (summaries are an optimisation).
    """
    conversation.refresh_from_db(fields=["summary", "summary_through_sequence"])
    pending = list(ChatMessage.objects
                   .filter(conversation=conversation, sequence__gt=conversation.summary_through_sequence)
                   .order_by("sequence"))
    if len(pending) <= keep_recent or sum(m.token_estimate for m in pending) <= trigger_tokens:
        return False

    to_fold = pending[:-keep_recent] if keep_recent else pending
    transcript = "\n".join(f"{m.role.upper()}: {m.content}" for m in to_fold)
    prompt = (f"EXISTING SUMMARY:\n{conversation.summary or '(none yet)'}\n\n"
              f"NEW MESSAGES:\n{transcript}")
    response = chat_model.invoke([SystemMessage(content=SUMMARY_INSTRUCTIONS), HumanMessage(content=prompt)])
    new_summary = _content_text(response.content).strip()[:MAX_SUMMARY_CHARS]
    if not new_summary:
        logger.warning("Summarizer returned an empty summary; keeping the old one")
        return False

    updated = (ChatConversation.objects
               .filter(pk=conversation.pk, summary_through_sequence=conversation.summary_through_sequence)
               .update(summary=new_summary, summary_through_sequence=to_fold[-1].sequence))
    return bool(updated)