# ai_intelligence/embeddings/factory.py
"""
Embedding providers, behind LangChain's own `Embeddings` interface (same idea as
llm/factory.py: LangChain already is the provider-independent contract, so this
file only maps OUR validated settings onto it).

Providers
  fastembed  local ONNX model, no API key, no per-request cost. Default model
             BAAI/bge-small-en-v1.5 (384 dimensions). Recommended starting point.
  gemini     Google embeddings API (needs AI_EMBEDDING_API_TOKEN and an explicit
             AI_EMBEDDING_MODEL_ID).
  fake       deterministic word-hashing vectors. NOT semantic - it only matches
             shared words. For tests and local plumbing checks, never production.

Every embedding call is validated against AI_EMBEDDING_DIMENSIONS: the pgvector
column has a fixed width, and vectors from different models must never be mixed
in one index (see README, "Changing the embedding model").
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from ai_intelligence.conf import ai_int, ai_str
from ai_intelligence.domain.exceptions import EmbeddingConfigurationError, EmbeddingError

SUPPORTED_EMBEDDING_PROVIDERS = {"fake", "fastembed", "gemini"}
DEFAULT_MODELS = {"fake": "hashing-v1", "fastembed": "BAAI/bge-small-en-v1.5"}


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    model_id: str
    dimensions: int
    api_token: str | None

    @property
    def label(self) -> str:
        """Stored on every chunk; retrieval only searches chunks with the current label."""
        return f"{self.provider}:{self.model_id}"


def load_embedding_config() -> EmbeddingConfig:
    provider = ai_str("AI_EMBEDDING_PROVIDER").lower()
    if not provider:
        raise EmbeddingConfigurationError("AI_EMBEDDING_PROVIDER is not set, so knowledge retrieval is disabled.")
    if provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        raise EmbeddingConfigurationError(
            f"Unknown AI_EMBEDDING_PROVIDER={provider!r}. Supported: {sorted(SUPPORTED_EMBEDDING_PROVIDERS)}")

    model_id = ai_str("AI_EMBEDDING_MODEL_ID") or DEFAULT_MODELS.get(provider, "")
    if not model_id:
        raise EmbeddingConfigurationError(f"AI_EMBEDDING_MODEL_ID is required for provider={provider!r}.")

    api_token = ai_str("AI_EMBEDDING_API_TOKEN") or None
    if provider == "gemini" and not api_token:
        raise EmbeddingConfigurationError("AI_EMBEDDING_API_TOKEN is required for provider='gemini'.")

    dimensions = ai_int("AI_EMBEDDING_DIMENSIONS")
    if dimensions <= 0:
        raise EmbeddingConfigurationError("AI_EMBEDDING_DIMENSIONS must be positive.")
    return EmbeddingConfig(provider, model_id, dimensions, api_token)


class HashingEmbeddings(Embeddings):
    """Feature-hashing bag of words, L2-normalised. Deterministic and offline, so
    retrieval tests are meaningful (texts sharing words are closer) - but it has no
    notion of meaning. Never use it for real knowledge retrieval."""

    def __init__(self, dimensions: int):
        self._dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vector[digest % self._dimensions] += 1.0 if (digest >> 64) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:                       # empty text: a zero vector has undefined cosine distance
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FastEmbedEmbeddings(Embeddings):
    """Thin LangChain wrapper over fastembed's TextEmbedding (local ONNX inference).
    The model is downloaded on first use and cached."""

    def __init__(self, model_name: str):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingConfigurationError("fastembed is not installed: pip install fastembed") from exc
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vector] for vector in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_embeddings(config: EmbeddingConfig | None = None) -> Embeddings:
    """A ready LangChain Embeddings object for the configured provider, or
    EmbeddingConfigurationError. Never falls back to a different provider."""
    config = config or load_embedding_config()
    if config.provider == "fake":
        return HashingEmbeddings(config.dimensions)
    if config.provider == "fastembed":
        return FastEmbedEmbeddings(config.model_id)
    if config.provider == "gemini":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as exc:
            raise EmbeddingConfigurationError(
                "langchain-google-genai is not installed: pip install langchain-google-genai") from exc
        return GoogleGenerativeAIEmbeddings(model=config.model_id, google_api_key=config.api_token)
    raise EmbeddingConfigurationError(f"No embeddings wiring for provider={config.provider!r}.")


def embed_texts(embeddings: Embeddings, texts: list[str], dimensions: int) -> list[list[float]]:
    """Embed documents and verify count + width. A wrong width means the configured
    model does not match the vector column, which must be a loud error, not a
    database insert failure three layers down."""
    if not texts:
        return []
    try:
        vectors = embeddings.embed_documents(texts)
    except Exception as exc:                                  # noqa: BLE001 - normalize provider errors
        raise EmbeddingError(f"Embedding call failed: {exc}") from exc
    _check(vectors, expected_count=len(texts), dimensions=dimensions)
    return vectors


def embed_query(embeddings: Embeddings, text: str, dimensions: int) -> list[float]:
    try:
        vector = embeddings.embed_query(text)
    except Exception as exc:                                  # noqa: BLE001
        raise EmbeddingError(f"Embedding call failed: {exc}") from exc
    _check([vector], expected_count=1, dimensions=dimensions)
    return vector


def _check(vectors: list[list[float]], expected_count: int, dimensions: int) -> None:
    if len(vectors) != expected_count:
        raise EmbeddingError(f"Expected {expected_count} vectors, got {len(vectors)}.")
    for vector in vectors:
        if len(vector) != dimensions:
            raise EmbeddingError(
                f"Embedding model returned {len(vector)} dimensions but AI_EMBEDDING_DIMENSIONS="
                f"{dimensions}. The vector column width must match the model - see README.")
        if not all(math.isfinite(x) for x in vector):
            raise EmbeddingError("Embedding contains NaN or infinite values.")