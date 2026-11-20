# ai_intelligence/memory/context_window.py
"""
Token budgeting for conversation history - the first of three techniques that
keep a long conversation inside the model's context window:

  1. SLIDING WINDOW (this file): replay the newest messages that fit a token
     budget, oldest dropped first.
  2. ROLLING SUMMARY (summarizer.py): turns older than the window are compressed
     into ChatConversation.summary instead of being lost.
  3. LONG-TERM MEMORY (long_term.py): durable facts the user stated (goals,
     horizon) survive across conversations as a few short lines.

Tokens are ESTIMATED (about 4 characters each) - good enough for budgeting and
free of any tokenizer dependency or provider-specific behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ai_intelligence.models import ChatConversation, ChatMessage


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) + 4        # +4 ~ per-message framing overhead


@dataclass(frozen=True)
class HistoryWindow:
    messages: list[BaseMessage]              # chronological, ready for the prompt
    summary: str                             # rolling summary of everything older
    dropped_unsummarized: int                # messages neither in the window nor in the summary yet


def build_history(conversation: ChatConversation, token_budget: int) -> HistoryWindow:
    """
    Newest-first walk over messages not yet folded into the summary, keeping
    those that fit `token_budget` (always at least the newest one), returned in
    chronological order.
    """
    unsummarized = list(ChatMessage.objects
                        .filter(conversation=conversation, sequence__gt=conversation.summary_through_sequence)
                        .order_by("-sequence"))
    kept: list[ChatMessage] = []
    used = 0
    for message in unsummarized:
        cost = message.token_estimate or estimate_tokens(message.content)
        if kept and used + cost > token_budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    messages = [HumanMessage(content=m.content) if m.role == ChatMessage.Role.USER else AIMessage(content=m.content)
                for m in kept]
    return HistoryWindow(messages=messages, summary=conversation.summary,
                         dropped_unsummarized=len(unsummarized) - len(kept))