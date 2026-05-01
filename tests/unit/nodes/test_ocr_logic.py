"""Unit tests for nodes/ocr_node/src/ocr_logic.py."""

from __future__ import annotations

import base64
import io
import sys
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from dmsai_models import Document, get_session, init_db

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
