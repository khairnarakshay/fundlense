# ai_intelligence/tests/test_llm_factory.py
"""Tests for the provider factory and configuration validation - no network calls."""
from django.test import SimpleTestCase, override_settings

from ai_intelligence.domain.exceptions import LLMConfigurationError
from ai_intelligence.llm.configuration import load_llm_config
from ai_intelligence.llm.factory import get_llm_provider
from ai_intelligence.llm.providers.huggingface import HuggingFaceProvider


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
                       AI_LLM_API_TOKEN="tok", AI_LLM_TEMPERATURE="0.2", AI_LLM_TIMEOUT_SECONDS="30")
    def test_valid_config_loads(self):
        config = load_llm_config()
        self.assertEqual(config.provider, "huggingface")
        self.assertEqual(config.model_id, "some/model")
        self.assertEqual(config.temperature, 0.2)
        self.assertEqual(config.timeout_seconds, 30)


class LLMFactoryTests(SimpleTestCase):
    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="any/model-id-works",
                       AI_LLM_API_TOKEN="tok")
    def test_factory_builds_huggingface_provider_for_any_model_id(self):
        """Confirms the adapter is NOT hardcoded to one model - any configured
        model_id produces a working provider instance."""
        provider = get_llm_provider()
        self.assertIsInstance(provider, HuggingFaceProvider)
        self.assertEqual(provider.model_id, "any/model-id-works")
        self.assertEqual(provider.provider_name, "huggingface")

    @override_settings(AI_LLM_PROVIDER="huggingface", AI_LLM_MODEL_ID="x", AI_LLM_API_TOKEN="tok")
    def test_factory_rejects_unregistered_provider_via_explicit_config(self):
        from ai_intelligence.llm.configuration import LLMConfig
        from ai_intelligence.llm import factory as factory_module
        bogus = LLMConfig(provider="not-registered", model_id="x", base_url=None,
                          api_token="tok", temperature=0.1, timeout_seconds=60)
        # bypass SUPPORTED_PROVIDERS validation by constructing LLMConfig directly,
        # to test the factory's own guard independently of configuration.py's
        factory_module._PROVIDERS.clear()
        with self.assertRaises(LLMConfigurationError):
            get_llm_provider(bogus)