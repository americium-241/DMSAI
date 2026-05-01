"""Unit tests for nodes/ingestion_node/src/ingestion_logic.py."""

from __future__ import annotations

import base64
import sys
import uuid

import pytest
from sqlmodel import select

from dmsai_models import Document, PipelineEvent, get_session, init_db

# Modules loaded by root conftest at collection time
ingestion_logic = sys.modules["ingestion_logic"]


# ---------------------------------------------------------------------------
# validate_extension
# ---------------------------------------------------------------------------

class TestValidateExtension:
    def test_valid_pdf(self):
        assert ingestion_logic.validate_extension("doc.pdf") == ".pdf"

    def test_valid_jpg(self):
        assert ingestion_logic.validate_extension("scan.jpg") == ".jpg"

    def test_valid_jpeg(self):
        assert ingestion_logic.validate_extension("scan.JPEG") == ".jpeg"

    def test_valid_png(self):
        assert ingestion_logic.validate_extension("image.PNG") == ".png"

    def test_valid_tiff(self):
        assert ingestion_logic.validate_extension("scan.tiff") == ".tiff"

    def test_valid_bmp(self):
        assert ingestion_logic.validate_extension("image.bmp") == ".bmp"

    def test_invalid_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            ingestion_logic.validate_extension("document.docx")

    def test_invalid_txt_raises(self):
        with pytest.raises(ValueError):
            ingestion_logic.validate_extension("readme.txt")

    def test_no_extension_raises(self):
        with pytest.raises(ValueError):
            ingestion_logic.validate_extension("noextension")

    def test_case_insensitive(self):
        # .PDF should be accepted
        assert ingestion_logic.validate_extension("scan.PDF") == ".pdf"


# ---------------------------------------------------------------------------
# build_ingestion_payload
# ---------------------------------------------------------------------------

class TestBuildIngestionPayload:
    def test_returns_payload_dict(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "invoice.pdf")
        assert isinstance(payload, dict)

    def test_payload_has_required_keys(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "invoice.pdf")
        required = {"workflow_id", "filename", "original_extension", "file_bytes", "source", "mode"}
        assert required.issubset(payload.keys())

    def test_workflow_id_is_uuid(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "test.pdf")
        # Should not raise
        uuid.UUID(payload["workflow_id"])

    def test_file_bytes_base64_encoded(self):
        raw = b"Hello PDF content"
        payload = ingestion_logic.build_ingestion_payload(raw, "test.pdf")
        decoded = base64.b64decode(payload["file_bytes"])
        assert decoded == raw

    def test_document_created_in_db(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "db_test.pdf")
        doc_id = payload["workflow_id"]
        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc is not None
        assert doc.filename == "db_test.pdf"
        assert doc.status == "INGESTED"

    def test_document_extension_stored(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"JPEG", "scan.jpg")
        doc_id = payload["workflow_id"]
        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.original_extension == ".jpg"

    def test_source_parameter_stored(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-x", "t.pdf", source="email")
        doc_id = payload["workflow_id"]
        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.source == "email"

    def test_invalid_extension_raises_before_db(self):
        with pytest.raises(ValueError):
            ingestion_logic.build_ingestion_payload(b"data", "file.exe")

    def test_history_starts_empty(self):
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-x", "a.pdf")
        assert payload["history"] == []


# ---------------------------------------------------------------------------
# process_document
# ---------------------------------------------------------------------------

class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_returns_payload(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-1.4", "proc.pdf")
        result = await ingestion_logic.process_document(payload)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_adds_ingestion_to_history(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-1.4", "history.pdf")
        result = await ingestion_logic.process_document(payload)
        assert "ingestion_completed" in result["history"]

    @pytest.mark.asyncio
    async def test_records_pipeline_events(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-1.4", "events.pdf")
        doc_id = payload["workflow_id"]
        await ingestion_logic.process_document(payload)

        with get_session() as session:
            events = session.exec(
                select(PipelineEvent).where(PipelineEvent.document_id == doc_id)
            ).all()
        event_types = {e.event_type for e in events}
        assert "started" in event_types
        assert "completed" in event_types

    @pytest.mark.asyncio
    async def test_preserves_existing_history(self):
        init_db()
        payload = ingestion_logic.build_ingestion_payload(b"%PDF-1.4", "histpre.pdf")
        payload["history"] = ["previous_step"]
        result = await ingestion_logic.process_document(payload)
        assert "previous_step" in result["history"]
        assert "ingestion_completed" in result["history"]
