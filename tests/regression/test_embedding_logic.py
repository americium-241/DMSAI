"""Regression tests for shared/dmsai_models/embedding.py.

These tests exercise:
  - cosine_similarity  (pure maths, no I/O)
  - document_embedding_text  (text truncation)
  - entity_embedding_text    (structured text builder)
  - call_embedding            (provider dispatch + graceful degradation)
  - store/load helpers        (DB round-trip)

All network calls are mocked; no real embedding model is required.
"""
from __future__ import annotations

import json
import math
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

from dmsai_models.embedding import (
    cosine_similarity,
    document_embedding_text,
    entity_embedding_text,
    call_embedding,
    store_document_embedding,
    store_entity_embedding,
    load_entity_embeddings,
    _embed_ollama,
    _embed_litellm,
)
from dmsai_models import (
    DocumentEmbedding,
    EntityEmbedding,
    Entity,
    get_session,
    init_db,
)


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_empty_input(self):
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_dimension_mismatch(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0

    def test_normalised_vectors(self):
        a = [0.6, 0.8]   # |a| = 1.0
        b = [0.8, 0.6]   # |b| = 1.0
        expected = 0.6 * 0.8 + 0.8 * 0.6  # = 0.96
        assert cosine_similarity(a, b) == pytest.approx(expected, rel=1e-5)


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------

class TestDocumentEmbeddingText:
    def test_short_text_unchanged(self):
        t = "Hello world"
        assert document_embedding_text(t) == "Hello world"

    def test_truncated_to_max_chars(self):
        long = "x" * 5000
        result = document_embedding_text(long, max_chars=2000)
        assert len(result) == 2000

    def test_empty_string(self):
        assert document_embedding_text("") == ""

    def test_strips_whitespace(self):
        assert document_embedding_text("  hello  ") == "hello"


class TestEntityEmbeddingText:
    def test_minimal(self):
        data = {"entity_type": "company", "name": "ACME"}
        result = entity_embedding_text(data)
        assert result == "company: ACME"

    def test_with_fields(self):
        data = {
            "entity_type": "company",
            "name": "ACME Corp",
            "fields": {"tax_id": "FR123", "email": "a@acme.fr"},
        }
        result = entity_embedding_text(data)
        assert result.startswith("company: ACME Corp")
        assert "tax_id=FR123" in result
        assert "email=a@acme.fr" in result

    def test_empty_fields_omitted(self):
        data = {
            "entity_type": "person",
            "name": "John Doe",
            "fields": {"email": "", "phone": None},
        }
        result = entity_embedding_text(data)
        assert "fields:" not in result

    def test_missing_keys_graceful(self):
        result = entity_embedding_text({})
        assert result == "other: "


# ---------------------------------------------------------------------------
# call_embedding — provider dispatch
# ---------------------------------------------------------------------------

class TestCallEmbedding:
    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        """embedding_enabled = false → always returns None, no HTTP call."""
        cfg = {"embedding_enabled": "false"}
        with patch("dmsai_models.embedding._refresh_embedding_config", return_value=cfg):
            result = await call_embedding("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_ollama_path_happy(self):
        """When enabled with ollama provider, returns vector from _embed_ollama."""
        cfg = {
            "embedding_enabled": "true",
            "embedding_provider": "ollama",
            "ollama_base_url": "http://localhost:11434",
            "embedding_model": "nomic-embed-text",
        }
        expected = [0.1, 0.2, 0.3]
        with patch("dmsai_models.embedding._refresh_embedding_config", return_value=cfg), \
             patch("dmsai_models.embedding._embed_ollama", new_callable=AsyncMock,
                   return_value=expected) as mock_ollama:
            result = await call_embedding("hello")
        assert result == expected
        mock_ollama.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_litellm_path_happy(self):
        """When enabled with litellm provider, returns vector from _embed_litellm."""
        cfg = {
            "embedding_enabled": "true",
            "embedding_provider": "litellm",
            "litellm_base_url": "http://proxy:4000",
            "embedding_model": "text-embedding-3-small",
        }
        expected = [0.5, 0.6, 0.7]
        with patch("dmsai_models.embedding._refresh_embedding_config", return_value=cfg), \
             patch("dmsai_models.embedding._embed_litellm", new_callable=AsyncMock,
                   return_value=expected) as mock_litellm:
            result = await call_embedding("hello")
        assert result == expected
        mock_litellm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        """Any provider exception → returns None (graceful degradation)."""
        cfg = {
            "embedding_enabled": "true",
            "embedding_provider": "ollama",
            "ollama_base_url": "http://localhost:11434",
            "embedding_model": "nomic-embed-text",
        }
        with patch("dmsai_models.embedding._refresh_embedding_config", return_value=cfg), \
             patch("dmsai_models.embedding._embed_ollama",
                   side_effect=httpx.ConnectError("refused")):
            result = await call_embedding("hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_falls_back_to_llm_provider(self):
        """embedding_provider absent → falls back to llm_provider."""
        cfg = {
            "embedding_enabled": "true",
            "llm_provider": "ollama",
            "ollama_base_url": "http://localhost:11434",
            "embedding_model": "nomic-embed-text",
        }
        with patch("dmsai_models.embedding._refresh_embedding_config", return_value=cfg), \
             patch("dmsai_models.embedding._embed_ollama", new_callable=AsyncMock,
                   return_value=[0.1]) as mock_ollama:
            await call_embedding("hello")
        mock_ollama.assert_awaited_once()


# ---------------------------------------------------------------------------
# _embed_ollama — HTTP response parsing
# ---------------------------------------------------------------------------

class TestEmbedOllama:
    @pytest.mark.asyncio
    async def test_parses_embeddings_key(self):
        cfg = {"ollama_base_url": "http://localhost:11434", "embedding_model": "nomic-embed-text"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            result = await _embed_ollama("hello", cfg, timeout=10.0)

        assert result == pytest.approx([0.1, 0.2, 0.3])

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_embeddings(self):
        cfg = {"ollama_base_url": "http://localhost:11434", "embedding_model": "nomic-embed-text"}
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"embeddings": []}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            result = await _embed_ollama("hello", cfg, timeout=10.0)

        assert result is None


# ---------------------------------------------------------------------------
# _embed_litellm — HTTP response parsing
# ---------------------------------------------------------------------------

class TestEmbedLitellm:
    @pytest.mark.asyncio
    async def test_parses_data_key(self):
        cfg = {
            "litellm_base_url": "http://proxy:4000",
            "embedding_model": "text-embedding-3-small",
            "litellm_api_key": "sk-test",
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"embedding": [0.5, 0.6]}]}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            result = await _embed_litellm("hello", cfg, timeout=10.0)

        assert result == pytest.approx([0.5, 0.6])

    @pytest.mark.asyncio
    async def test_raises_when_base_url_missing(self):
        cfg = {"litellm_base_url": "", "embedding_model": "m"}
        with pytest.raises(RuntimeError, match="litellm_base_url"):
            await _embed_litellm("hello", cfg, timeout=10.0)


# ---------------------------------------------------------------------------
# DB storage helpers — round-trip
# ---------------------------------------------------------------------------

class TestDocumentEmbeddingStorage:
    def test_store_and_load(self):
        init_db()
        # We need a real document ID for the FK — create one quickly
        from dmsai_models import Document
        from datetime import datetime
        doc_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(Document(
                id=doc_id, filename="emb_test.pdf",
                original_extension=".pdf", status="INGESTED",
                created_at=datetime.utcnow(),
            ))
            session.commit()

        vec = [0.1, 0.2, 0.3, 0.4]
        store_document_embedding(doc_id, vec, model="test-model")

        with get_session() as session:
            row = session.exec(
                __import__("sqlmodel", fromlist=["select"]).select(DocumentEmbedding)
                .where(DocumentEmbedding.document_id == doc_id)
            ).first()

        assert row is not None
        assert json.loads(row.vector) == vec
        assert row.model == "test-model"

    def test_update_existing(self):
        init_db()
        from dmsai_models import Document
        from datetime import datetime
        from sqlmodel import select as _select
        doc_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(Document(
                id=doc_id, filename="upd_test.pdf",
                original_extension=".pdf", status="INGESTED",
                created_at=datetime.utcnow(),
            ))
            session.commit()

        store_document_embedding(doc_id, [0.1], model="m")
        store_document_embedding(doc_id, [0.9], model="m")  # update

        with get_session() as session:
            rows = session.exec(
                _select(DocumentEmbedding)
                .where(DocumentEmbedding.document_id == doc_id)
                .where(DocumentEmbedding.model == "m")
            ).all()

        assert len(rows) == 1, "Should upsert, not insert duplicate"
        assert json.loads(rows[0].vector) == [0.9]


class TestEntityEmbeddingStorage:
    def test_store_and_load_entity_embeddings(self):
        init_db()
        from datetime import datetime
        e_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(Entity(
                id=e_id, entity_type="company",
                name="StorageTestCo",
                created_at=datetime.utcnow(),
            ))
            session.commit()

        vec = [0.5, 0.6, 0.7]
        store_entity_embedding(e_id, vec, model="test-emb")

        loaded = load_entity_embeddings([e_id], model="test-emb")
        assert e_id in loaded
        assert loaded[e_id] == pytest.approx(vec)

    def test_load_returns_empty_for_unknown_ids(self):
        result = load_entity_embeddings(["non-existent-id"], model="")
        assert result == {}

    def test_load_empty_list(self):
        assert load_entity_embeddings([]) == {}

    def test_update_existing_entity_embedding(self):
        init_db()
        from datetime import datetime
        from sqlmodel import select as _select
        e_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(Entity(
                id=e_id, entity_type="person",
                name="UpdateTestPerson",
                created_at=datetime.utcnow(),
            ))
            session.commit()

        store_entity_embedding(e_id, [0.1, 0.2], model="upd")
        store_entity_embedding(e_id, [0.9, 0.8], model="upd")  # update

        with get_session() as session:
            rows = session.exec(
                _select(EntityEmbedding)
                .where(EntityEmbedding.entity_id == e_id)
                .where(EntityEmbedding.model == "upd")
            ).all()

        assert len(rows) == 1
        assert json.loads(rows[0].vector) == [0.9, 0.8]
