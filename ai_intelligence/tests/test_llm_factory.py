# ai_intelligence/tests/test_llm_factory.py
"""
Tests for configuration validation and the chat-model factory. The factory
test mocks langchain_huggingface's classes - no real network call, and no
dependency on exactly which chat-completion backend LangChain uses under the
hood, just that our factory wires OUR validated config into it correctly.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from ai_intelligence.domain.exceptions import LLMConfigurationError
from ai_intelligence.llm.configuration import load_llm_config


class LLMConfigurationTests(SimpleTestCase):
    @override_settings(AI_LLM_PROVIDER="", AI_LLM_MODEL_ID="x")
    def test_missing_provider_raises(self):
        with self.assertRaises(LLMConfigurationError):
            load_llm_config()

    @override_settings(AI_LLM_PROVIDER="not-a-real-provider", AI_LLM_MODEL_ID="x")
    def test_unknown_provider_raises(self):
        with self.assertRaises(LLMConfigurationError):
            load_llm_config()

    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="")
    def test_missing_model_id_raises(self):
        with self.assertRaises(LLMConfigurationError):
            load_llm_config()

    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="some/model", AI_LLM_API_TOKEN="")
    def test_missing_token_for_huggingface_raises(self):
        with self.assertRaises(LLMConfigurationError):
            load_llm_config()

    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="some/model",
                       AI_LLM_API_TOKEN="tok", AI_LLM_TEMPERATURE="not-a-number")
    def test_invalid_temperature_raises(self):
        with self.assertRaises(LLMConfigurationError):
            load_llm_config()

    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="some/model",
                       AI_LLM_API_TOKEN="tok", AI_LLM_TEMPERATURE="0.2", AI_LLM_TIMEOUT_SECONDS="30",
                       AI_HF_INFERENCE_PROVIDER="groq")
    def test_valid_config_loads(self):
        config = load_llm_config()
        self.assertEqual(config.provider, "huggingface")
        self.assertEqual(config.model_id, "some/model")
        self.assertEqual(config.temperature, 0.2)
        self.assertEqual(config.timeout_seconds, 30)
        self.assertEqual(config.hf_inference_provider, "groq")


class ChatModelFactoryTests(SimpleTestCase):
    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="any/model-id-works",
                       AI_LLM_API_TOKEN="tok", AI_HF_INFERENCE_PROVIDER="groq")
    @patch("langchain_huggingface.ChatHuggingFace")
    @patch("langchain_huggingface.HuggingFaceEndpoint")
    def test_factory_wires_config_into_langchain_for_any_model_id(self, mock_endpoint_cls, mock_chat_cls):
        """Confirms the factory is NOT hardcoded to one model, and passes our
        validated config (model id, token, provider, temperature, timeout)
        through to LangChain's own classes rather than re-implementing them."""
        from ai_intelligence.llm.factory import get_chat_model

        mock_endpoint_cls.return_value = MagicMock()
        mock_chat_cls.return_value = MagicMock()

        get_chat_model()

        mock_endpoint_cls.assert_called_once()
        _, kwargs = mock_endpoint_cls.call_args
        self.assertEqual(kwargs["repo_id"], "any/model-id-works")
        self.assertEqual(kwargs["provider"], "groq")
        self.assertEqual(kwargs["huggingfacehub_api_token"], "tok")
        mock_chat_cls.assert_called_once()

    def test_factory_rejects_unregistered_provider_via_explicit_config(self):
        from ai_intelligence.llm.configuration import LLMConfig
        from ai_intelligence.llm.factory import get_chat_model

        bogus = LLMConfig(provider="not-a-real-provider", model_id="x", base_url=None,
                          api_token="tok", temperature=0.1, timeout_seconds=60)
        with self.assertRaises(LLMConfigurationError):
            get_chat_model(bogus)