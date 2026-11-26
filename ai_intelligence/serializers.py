# ai_intelligence/serializers.py
"""DRF serializers: validation of every request input, and the shape of every record returned."""
from __future__ import annotations

from rest_framework import serializers

from ai_intelligence.models import ChatConversation, ChatMessage, UserMemory

ALLOWED_PAGE_SIZES = (10, 20, 50, 100)


class ChatRequestSerializer(serializers.Serializer):
    """`question` is accepted as an alias of `message`, for clients of the earlier single-turn endpoint.
    Note what is NOT here: any user id. The user always comes from the authenticated request."""
    message = serializers.CharField(required=False, trim_whitespace=True)
    question = serializers.CharField(required=False, trim_whitespace=True)
    conversation_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate(self, attrs):
        text = attrs.get("message") or attrs.get("question")
        if not text:
            raise serializers.ValidationError({"message": "This field is required."})
        attrs["text"] = text
        return attrs


class PageQuerySerializer(serializers.Serializer):
    page_no = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)
    q = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")

    def validate_page_size(self, value):
        return min(ALLOWED_PAGE_SIZES, key=lambda allowed: abs(allowed - value))     # snap to 10/20/50/100


class MessagesQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=30)
    before = serializers.IntegerField(required=False, min_value=1, allow_null=True, default=None)


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatConversation
        fields = ["id", "title", "message_count", "last_message_at", "created_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "sequence", "role", "content", "metadata", "created_at"]


class MemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMemory
        fields = ["id", "category", "content", "created_at"]