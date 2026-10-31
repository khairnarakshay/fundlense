# ai_intelligence/llm/factory.py
"""
Provider factory - returns a LangChain BaseChatModel built from our own
validated settings (llm/configuration.py). We do NOT wrap LangChain's chat
model interface in a second custom interface: LangChain's invoke()/stream()/
with_structured_output() already IS the provider-independent contract the
brief asks for. Adding a future provider (OpenAI, Anthropic) means adding one
branch here that returns the matching LangChain chat model class - everything
downstream (chat_service.py, and later graphs) only ever talks to the
returned object through LangChain's own standard interface, so nothing else
in this app needs to change.
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from ai_intelligence.domain.exceptions import LLMConfigurationError
from ai_intelligence.llm.configuration import LLMConfig, load_llm_config


def get_chat_model(config: LLMConfig | None = None) -> BaseChatModel:
    """
    Returns a ready-to-use LangChain chat model for whatever provider/model is
    configured. Raises LLMConfigurationError for anything invalid or
    unsupported - never falls back to a different provider or model.
    """
    config = config or load_llm_config()

    if config.provider == "huggingface":
        # Imported here, not at module level, so importing factory.py doesn't
        # require every provider's package installed - only the one actually
        # configured for this deployment.
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

        endpoint = HuggingFaceEndpoint(
            repo_id=config.model_id,
            # "auto" lets HF pick a provider from what's enabled on the account;
            # ours was set explicitly (AI_HF_INFERENCE_PROVIDER=groq) earlier
            # because auto-routing failed during setup - see project notes.
            provider=config.hf_inference_provider or "auto",
            huggingfacehub_api_token=config.api_token,
            temperature=config.temperature,
            timeout=config.timeout_seconds,
        )
        return ChatHuggingFace(llm=endpoint)

    if config.provider == "groq":
        # Groq's own API directly - no HF router/credits involved at all,
        # separate account, separate free tier from the huggingface branch above.
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=config.model_id,
            api_key=config.api_token,
            temperature=config.temperature,
            timeout=config.timeout_seconds,
        )

    if config.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=config.model_id,
            google_api_key=config.api_token,
            temperature=config.temperature,
            timeout=config.timeout_seconds,
        )

    # Defensive: config validation (configuration.py) already restricts
    # config.provider to SUPPORTED_PROVIDERS, so reaching here means a
    # provider was added to that set without a branch here - a bug in this
    # factory, not a user configuration error.
    raise LLMConfigurationError(
        f"No chat model wiring for provider={config.provider!r} - add a branch in get_chat_model().")