"""Unit tests for nodes/conversion_node/src/conversion_logic.py."""

from __future__ import annotations

import base64
import io
import sys
from unittest.mock import patch

import pytest
from PIL import Image

from dmsai_models import Document, get_session, init_db

conversion_logic = sys.modules["conversion_logic"]
ingestion_logic = sys.modules["ingestion_logic"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jpeg_bytes() -> bytes:
    """Create a minimal in-memory JPEG image."""
    img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_payload(file_bytes: bytes, filename: str) -> dict:
    init_db()
    payload = ingestion_logic.build_ingestion_payload(file_bytes, filename)
    return payload


# ---------------------------------------------------------------------------
# convert_image_to_pdf
# ---------------------------------------------------------------------------

class TestConvertImageToPdf:
    def test_jpeg_produces_pdf_magic_bytes(self):
        jpeg = _jpeg_bytes()
        result = conversion_logic.convert_image_to_pdf(jpeg)
        assert result[:4] == b"%PDF"

    def test_png_produces_pdf_magic_bytes(self):
        png = _png_bytes()
        result = conversion_logic.convert_image_to_pdf(png)
        assert result[:4] == b"%PDF"

    def test_result_is_bytes(self):
        jpeg = _jpeg_bytes()
        result = conversion_logic.convert_image_to_pdf(jpeg)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_rgba_image_converted(self):
        img = Image.new("RGBA", (50, 50), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_with_alpha = buf.getvalue()
        result = conversion_logic.convert_image_to_pdf(png_with_alpha)
        assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# process_document
# ---------------------------------------------------------------------------

class TestConversionProcessDocument:
    @pytest.mark.asyncio
    async def test_pdf_passthrough(self):
        """PDF input should pass through unchanged (bytes preserved)."""
        raw_pdf = b"%PDF-1.4 fake content"
        payload = _make_payload(raw_pdf, "invoice.pdf")
        original_b64 = payload["file_bytes"]

        with patch.object(
            sys.modules.get("dmsai_models", type(sys)("fake")),
            "record_pipeline_event",
            return_value=None,
        ):
            result = await conversion_logic.process_document(payload)

        decoded = base64.b64decode(result["file_bytes"])
        assert decoded == raw_pdf

    @pytest.mark.asyncio
    async def test_jpeg_converted_to_pdf(self):
        jpeg = _jpeg_bytes()
        payload = _make_payload(jpeg, "scan.jpg")
        result = await conversion_logic.process_document(payload)
        pdf_bytes = base64.b64decode(result["file_bytes"])
        assert pdf_bytes[:4] == b"%PDF"

    @pytest.mark.asyncio
    async def test_png_converted_to_pdf(self):
        png = _png_bytes()
        payload = _make_payload(png, "scan.png")
        result = await conversion_logic.process_document(payload)
        pdf_bytes = base64.b64decode(result["file_bytes"])
        assert pdf_bytes[:4] == b"%PDF"

    @pytest.mark.asyncio
    async def test_adds_to_history(self):
        payload = _make_payload(b"%PDF-1.4", "doc.pdf")
        result = await conversion_logic.process_document(payload)
        assert "conversion_completed" in result["history"]

    @pytest.mark.asyncio
    async def test_sets_unified_extension_pdf(self):
        payload = _make_payload(_jpeg_bytes(), "scan.jpg")
        result = await conversion_logic.process_document(payload)
        assert result["unified_extension"] == ".pdf"

    @pytest.mark.asyncio
    async def test_unsupported_extension_raises(self):
        payload = _make_payload(b"", "doc.pdf")
        payload["original_extension"] = ".docx"
        with pytest.raises(ValueError, match="Unsupported format"):
            await conversion_logic.process_document(payload)
