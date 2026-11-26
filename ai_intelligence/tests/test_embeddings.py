# ai_intelligence/tests/test_embeddings.py
"""Embedding configuration, the offline hashing provider, and dimension validation. No network."""
import math

from django.test import SimpleTestCase, override_settings

from ai_intelligence.domain.exceptions import EmbeddingConfigurationError, EmbeddingError
from ai_intelligence.embeddings.factory import (
    HashingEmbeddings, embed_query, embed_texts, get_embeddings, load_embedding_config,
)


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))        # vectors are L2-normalised


class EmbeddingConfigTests(SimpleTestCase):
    @override_settings(AI_EMBEDDING_PROVIDER="")
    def test_unset_provider_means_rag_disabled(self):
        with self.assertRaises(EmbeddingConfigurationError):
            load_embedding_config()

    @override_settings(AI_EMBEDDING_PROVIDER="nonsense")
    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(EmbeddingConfigurationError):
            load_embedding_config()

    @override_settings(AI_EMBEDDING_PROVIDER="gemini", AI_EMBEDDING_MODEL_ID="models/x", AI_EMBEDDING_API_TOKEN="")
    def test_gemini_needs_a_token(self):
        with self.assertRaises(EmbeddingConfigurationError):
            load_embedding_config()

    @override_settings(AI_EMBEDDING_PROVIDER="gemini", AI_EMBEDDING_MODEL_ID="", AI_EMBEDDING_API_TOKEN="t")
    def test_gemini_needs_an_explicit_model(self):
        with self.assertRaises(EmbeddingConfigurationError):
            load_embedding_config()

    @override_settings(AI_EMBEDDING_PROVIDER="fake", AI_EMBEDDING_DIMENSIONS=0)
    def test_dimensions_must_be_positive(self):
        with self.assertRaises(EmbeddingConfigurationError):
            load_embedding_config()

    @override_settings(AI_EMBEDDING_PROVIDER="fastembed", AI_EMBEDDING_MODEL_ID="", AI_EMBEDDING_DIMENSIONS=384)
    def test_fastembed_has_a_default_model_and_a_label(self):
        config = load_embedding_config()
        self.assertEqual(config.model_id, "BAAI/bge-small-en-v1.5")
        self.assertEqual(config.label, "fastembed:BAAI/bge-small-en-v1.5")

    @override_settings(AI_EMBEDDING_PROVIDER="fake", AI_EMBEDDING_DIMENSIONS=384)
    def test_fake_provider_builds_without_network(self):
        self.assertIsInstance(get_embeddings(), HashingEmbeddings)


class HashingEmbeddingsTests(SimpleTestCase):
    def setUp(self):
        self.emb = HashingEmbeddings(384)

    def test_deterministic_and_normalised(self):
        a, b = self.emb.embed_query("exit load fee"), self.emb.embed_query("exit load fee")
        self.assertEqual(a, b)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in a)), 1.0, places=6)

    def test_shared_words_are_closer_than_unrelated_text(self):
        q = self.emb.embed_query("what is the exit load")
        related = self.emb.embed_query("exit load is a fee charged on redemption")
        unrelated = self.emb.embed_query("upload your statement pdf password")
        self.assertGreater(cosine(q, related), cosine(q, unrelated))

    def test_empty_text_never_produces_a_zero_vector(self):
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in self.emb.embed_query(""))), 1.0, places=6)


class DimensionValidationTests(SimpleTestCase):
    def test_wrong_width_is_a_loud_error(self):
        with self.assertRaises(EmbeddingError) as ctx:
            embed_texts(HashingEmbeddings(100), ["a"], dimensions=384)
        self.assertIn("AI_EMBEDDING_DIMENSIONS", str(ctx.exception))

    def test_wrong_width_for_a_query_too(self):
        with self.assertRaises(EmbeddingError):
            embed_query(HashingEmbeddings(100), "a", dimensions=384)

    def test_provider_exception_is_normalised(self):
        class Broken:
            def embed_documents(self, texts):
                raise RuntimeError("down")
        with self.assertRaises(EmbeddingError):
            embed_texts(Broken(), ["a"], dimensions=384)

    def test_nan_is_rejected(self):
        class Nan:
            def embed_documents(self, texts):
                return [[float("nan")] * 4 for _ in texts]
        with self.assertRaises(EmbeddingError):
            embed_texts(Nan(), ["a"], dimensions=4)

    def test_no_texts_no_call(self):
        self.assertEqual(embed_texts(HashingEmbeddings(4), [], dimensions=4), [])