# ai_intelligence/memory/conversation_store.py
"""
Persistent conversation storage. Every function takes the authenticated user;
there is no function that touches a conversation without one.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ai_intelligence.domain.exceptions import ConversationNotFound
from ai_intelligence.memory.context_window import estimate_tokens
from ai_intelligence.models import ChatConversation, ChatMessage
from ai_intelligence.selectors import get_conversation

TITLE_MAX_CHARS = 60


def create_conversation(user) -> ChatConversation:
    return ChatConversation.objects.create(user=user)


def resolve_conversation(user, conversation_id) -> ChatConversation:
    """An existing conversation the user owns, or a new one when no id is given."""
    if conversation_id in (None, ""):
        return create_conversation(user)
    return get_conversation(user, conversation_id)


def _title_from(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= TITLE_MAX_CHARS else one_line[: TITLE_MAX_CHARS - 1].rstrip() + "…"


@transaction.atomic
def append_turn(user, conversation_id: int, user_text: str, assistant_text: str,
                user_metadata: dict | None = None,
                assistant_metadata: dict | None = None) -> tuple[ChatMessage, ChatMessage]:
    """
    Store one user message and its answer as a pair, under a row lock on the
    conversation so two simultaneous requests cannot be given the same
    sequence number. Ownership is re-checked inside the lock.
    """
    try:
        conversation = ChatConversation.objects.select_for_update().get(pk=conversation_id, user=user)
    except ChatConversation.DoesNotExist:
        raise ConversationNotFound("Conversation not found.") from None

    base = conversation.message_count
    user_msg = ChatMessage.objects.create(
        conversation=conversation, role=ChatMessage.Role.USER, content=user_text, sequence=base + 1,
        token_estimate=estimate_tokens(user_text), metadata=user_metadata or {})
    assistant_msg = ChatMessage.objects.create(
        conversation=conversation, role=ChatMessage.Role.ASSISTANT, content=assistant_text, sequence=base + 2,
        token_estimate=estimate_tokens(assistant_text), metadata=assistant_metadata or {})

    conversation.message_count = base + 2
    conversation.last_message_at = timezone.now()
    update_fields = ["message_count", "last_message_at", "updated_at"]
    if not conversation.title:
        conversation.title = _title_from(user_text)
        update_fields.append("title")
    conversation.save(update_fields=update_fields)
    return user_msg, assistant_msg


def list_messages_page(conversation: ChatConversation, limit: int, before_sequence: int | None = None):
    """
    Cursor pagination for chat history (infinite scroll upward): the `limit`
    messages immediately before `before_sequence`, or the newest `limit` when
    it is omitted. Returns (messages oldest-first, has_more, next_before).
    """
    qs = ChatMessage.objects.filter(conversation=conversation)
    if before_sequence is not None:
        qs = qs.filter(sequence__lt=before_sequence)
    rows = list(qs.order_by("-sequence")[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return rows, has_more, (rows[0].sequence if has_more and rows else None)


def delete_conversation(user, conversation_id) -> None:
    get_conversation(user, conversation_id).delete()      # messages cascade