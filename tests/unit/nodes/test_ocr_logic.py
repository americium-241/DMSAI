"""Unit tests for nodes/ocr_node/src/ocr_logic.py."""

from __future__ import annotations

import base64
import io
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from dmsai_models import Document, DocumentEmbedding, get_session, init_db

ocr_logic = sys.modules.get("ocr_src.ocr_logic")
ingestion_logic = sys.modules["ingestion_logic"]
storage_logic = sys.modules["storage_logic"]
conversion_logic = sys.modules["conversion_logic"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pdf_bytes() -> bytes:
    img = Image.new("RGB", (612, 792), "white")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


async def _make_stored_payload() -> dict:
    """Run ingestion → conversion → storage to get a payload with storage_path."""
    init_db()
    pdf = _pdf_bytes()
    payload = ingestion_logic.build_ingestion_payload(pdf, "ocr_test.pdf")
    payload = await conversion_logic.process_document(payload)
    payload = await storage_logic.process_document(payload)
    return payload


# ---------------------------------------------------------------------------
# process_document (OCR)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(ocr_logic is None, reason="OCR module not loaded")
class TestOcrProcessDocument:
    @pytest.mark.asyncio
    async def test_ocr_text_set_in_payload(self):
        payload = await _make_stored_payload()
        mock_text = "Invoice INV-2026-001\nTotal: 1200 EUR"

        with patch.object(
            sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
            new_callable=AsyncMock,
            return_value=mock_text,
        ):
            result = await ocr_logic.process_document(payload)

        assert result["ocr_text"] == mock_text

    @pytest.mark.asyncio
    async def test_document_status_set_to_ocr_done(self):
        payload = await _make_stored_payload()
        doc_id = payload["workflow_id"]

        with patch.object(
            sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
            new_callable=AsyncMock,
            return_value="some text",
        ):
            await ocr_logic.process_document(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.status == "OCR_DONE"

    @pytest.mark.asyncio
    async def test_ocr_text_stored_in_db(self):
        payload = await _make_stored_payload()
        doc_id = payload["workflow_id"]
        expected_text = "Contract details here"

        with patch.object(
            sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
            new_callable=AsyncMock,
            return_value=expected_text,
        ):
            await ocr_logic.process_document(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.ocr_text == expected_text

    @pytest.mark.asyncio
    async def test_empty_ocr_text_gives_zero_confidence(self):
        payload = await _make_stored_payload()
        doc_id = payload["workflow_id"]

        with patch.object(
            sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await ocr_logic.process_document(payload)

        assert result["ocr_confidence"] == pytest.approx(0.0)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.ocr_confidence == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_non_empty_ocr_text_gives_one_confidence(self):
        payload = await _make_stored_payload()

        with patch.object(
            sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
            new_callable=AsyncMock,
            return_value="Some extracted text",
        ):
            result = await ocr_logic.process_document(payload)

        assert result["ocr_confidence"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_adds_to_history(self):
        payload = await _make_stored_payload()

        with patch.object(
            sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
            new_callable=AsyncMock,
            return_value="text",
        ):
            result = await ocr_logic.process_document(payload)

        assert "ocr_completed" in result["history"]


# ---------------------------------------------------------------------------
# Embedding integration tests (embedding enabled path)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(ocr_logic is None, reason="OCR module not loaded")
class TestOcrEmbedding:
    """Verify that ocr_logic stores a DocumentEmbedding when embedding is on."""

    @pytest.mark.asyncio
    async def test_document_embedding_stored_when_enabled(self):
        """When call_embedding returns a vector, it is persisted in DocumentEmbedding."""
        import dmsai_models.embedding as _emb
        from fixtures.mock_responses import MOCK_EMBEDDING_VECTOR

        payload = await _make_stored_payload()
        doc_id = payload["workflow_id"]

        # Override the autouse mock: return a real vector for this test
        with patch.object(_emb, "call_embedding", new_callable=AsyncMock, return_value=MOCK_EMBEDDING_VECTOR), \
             patch.object(sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
                          new_callable=AsyncMock, return_value="Invoice text here"):
            await ocr_logic.process_document(payload)

        with get_session() as session:
            emb = session.exec(
                __import__("sqlmodel", fromlist=["select"]).select(DocumentEmbedding)
                .where(DocumentEmbedding.document_id == doc_id)
            ).first()

        assert emb is not None, "DocumentEmbedding row expected"
        import json
        stored_vec = json.loads(emb.vector)
        assert stored_vec == MOCK_EMBEDDING_VECTOR

    @pytest.mark.asyncio
    async def test_no_embedding_stored_when_disabled(self):
        """When call_embedding returns None (disabled), no DocumentEmbedding row is written."""
        import dmsai_models.embedding as _emb
        from sqlmodel import select as _select

        payload = await _make_stored_payload()
        doc_id = payload["workflow_id"]

        # autouse fixture already returns None — just confirm no row is created
        with patch.object(sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
                          new_callable=AsyncMock, return_value="Some text"):
            await ocr_logic.process_document(payload)

        with get_session() as session:
            count = session.exec(
                _select(DocumentEmbedding).where(DocumentEmbedding.document_id == doc_id)
            ).first()

        assert count is None, "No DocumentEmbedding row expected when embedding is disabled"

    @pytest.mark.asyncio
    async def test_pipeline_succeeds_when_embedding_raises(self):
        """A crashing embedding call must NOT fail the OCR pipeline stage."""
        import dmsai_models.embedding as _emb

        payload = await _make_stored_payload()

        async def _crash(*args, **kwargs):
            raise RuntimeError("embedding service unreachable")

        with patch.object(_emb, "call_embedding", side_effect=_crash), \
             patch.object(sys.modules.get("ocr_src.ocr_logic"), "run_vision_llm",
                          new_callable=AsyncMock, return_value="Recovered text"):
            result = await ocr_logic.process_document(payload)

        assert result["ocr_text"] == "Recovered text"
        assert "ocr_completed" in result["history"]
