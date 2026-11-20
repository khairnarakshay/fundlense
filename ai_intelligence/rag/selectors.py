# ai_intelligence/selectors.py
"""
THE only place private records are looked up by id. Every function here takes
the authenticated `user` and filters on it, so an id taken from a URL or
request body is never used on its own. A record that exists but belongs to
someone else raises the same NotFound error as one that does not exist,
so ids cannot be used to probe other users' data.
"""
from __future__ import annotations

from ai_intelligence.domain.exceptions import ConversationNotFound, MemoryNotFound
from ai_intelligence.models import ChatConversation, UserMemory


def conversations_for_user(user):
    return ChatConversation.objects.filter(user=user)


def get_conversation(user, conversation_id) -> ChatConversation:
    try:
        return ChatConversation.objects.get(pk=conversation_id, user=user)
    except (ChatConversation.DoesNotExist, ValueError, TypeError):
        raise ConversationNotFound("Conversation not found.") from None


def memories_for_user(user):
    return UserMemory.objects.filter(user=user)


def get_memory(user, memory_id) -> UserMemory:
    try:
        return UserMemory.objects.get(pk=memory_id, user=user)
    except (UserMemory.DoesNotExist, ValueError, TypeError):
        raise MemoryNotFound("Memory not found.") from None