# ai_intelligence/tests/test_huggingface_provider.py
"""Tests for the Hugging Face adapter's error normalization and structured-output
fallback. The underlying InferenceClient is mocked - no real network/API calls."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from pydantic import BaseModel

from ai_intelligence.domain.exceptions import LLMProviderError, StructuredOutputError
from ai_intelligence.domain.schemas import ChatMessage, MessageRole
from ai_intelligence.llm.providers.huggingface import HuggingFaceProvider


class DummySchema(BaseModel):
    answer: str
    confidence: float


def _make_response(content: str):
    message = MagicMock(content=content)
    choice = MagicMock(message=message, finish_reason="stop")
    response = MagicMock(choices=[choice], usage=None)
    return response


class HuggingFaceProviderGenerateTests(SimpleTestCase):
    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_generate_returns_normalized_result(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.return_value = _make_response("hello there")

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        result = provider.generate([ChatMessage(role=MessageRole.USER, content="hi")])

        self.assertEqual(result.content, "hello there")
        self.assertEqual(result.provider, "huggingface")
        self.assertEqual(result.model_id, "any/model")

    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_generate_wraps_unexpected_errors(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.side_effect = RuntimeError("boom")

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        with self.assertRaises(LLMProviderError):
            provider.generate([ChatMessage(role=MessageRole.USER, content="hi")])


class HuggingFaceProviderStructuredOutputTests(SimpleTestCase):
    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_structured_output_valid_json_first_try(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.return_value = _make_response(
            '{"answer": "yes", "confidence": 0.9}')

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        result = provider.generate_structured(
            [ChatMessage(role=MessageRole.USER, content="q")], DummySchema)

        self.assertIsInstance(result, DummySchema)
        self.assertEqual(result.answer, "yes")

    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_structured_output_strips_markdown_fences(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.return_value = _make_response(
            '```json\n{"answer": "yes", "confidence": 0.5}\n```')

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        result = provider.generate_structured(
            [ChatMessage(role=MessageRole.USER, content="q")], DummySchema)

        self.assertEqual(result.answer, "yes")

    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_structured_output_raises_after_retries_exhausted(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.return_value = _make_response("not json at all")

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        with self.assertRaises(StructuredOutputError):
            provider.generate_structured(
                [ChatMessage(role=MessageRole.USER, content="q")], DummySchema)
        # one initial attempt + _STRUCTURED_OUTPUT_RETRIES retries
        self.assertEqual(mock_client.chat_completion.call_count, 2)


class HuggingFaceProviderHealthCheckTests(SimpleTestCase):
    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_health_check_healthy(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.return_value = _make_response("pong")

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        health = provider.health_check()
        self.assertTrue(health.healthy)

    @patch("ai_intelligence.llm.providers.huggingface.InferenceClient")
    def test_health_check_unhealthy_never_raises(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.chat_completion.side_effect = RuntimeError("down")

        provider = HuggingFaceProvider(model_id="any/model", api_token="tok")
        health = provider.health_check()   # must not raise
        self.assertFalse(health.healthy)
        self.assertIn("down", health.detail)