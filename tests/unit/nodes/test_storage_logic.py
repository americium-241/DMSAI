"""Unit tests for nodes/storage_node/src/storage_logic.py."""

from __future__ import annotations

import base64
import io
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from dmsai_models import Document, get_session, init_db

storage_logic = sys.modules["storage_logic"]
ingestion_logic = sys.modules["ingestion_logic"]
conversion_logic = sys.modules["conversion_logic"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf_bytes() -> bytes:
    img = Image.new("RGB", (100, 80), "white")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _make_pipeline_payload(pdf_bytes: bytes) -> dict:
    """Build a payload as it would arrive at the storage node."""
    init_db()
    raw = b"%PDF-1.4 minimal"
    payload = ingestion_logic.build_ingestion_payload(raw, "storage_test.pdf")
    payload["file_bytes"] = base64.b64encode(pdf_bytes).decode()
    return payload


# ---------------------------------------------------------------------------
# save_to_filesystem
# ---------------------------------------------------------------------------

class TestSaveToFilesystem:
    def test_creates_file_on_disk(self, tmp_path):
        # Temporarily override STORAGE_ROOT for this test
        original = storage_logic.STORAGE_ROOT
        storage_logic.STORAGE_ROOT = str(tmp_path)
        try:
            pdf = _make_pdf_bytes()
            doc_id = str(uuid.uuid4())
            path = storage_logic.save_to_filesystem(doc_id, pdf)
            assert os.path.isfile(path)
        finally:
            storage_logic.STORAGE_ROOT = original

    def test_file_content_matches_input(self, tmp_path):
        original = storage_logic.STORAGE_ROOT
        storage_logic.STORAGE_ROOT = str(tmp_path)
        try:
            pdf = _make_pdf_bytes()
            doc_id = str(uuid.uuid4())
            path = storage_logic.save_to_filesystem(doc_id, pdf)
            with open(path, "rb") as f:
                content = f.read()
            assert content == pdf
        finally:
            storage_logic.STORAGE_ROOT = original

    def test_path_is_date_partitioned(self, tmp_path):
        original = storage_logic.STORAGE_ROOT
        storage_logic.STORAGE_ROOT = str(tmp_path)
        try:
            doc_id = str(uuid.uuid4())
            path = storage_logic.save_to_filesystem(doc_id, b"%PDF-1.4")
            now = datetime.utcnow()
            # Path should contain year/month sub-directories
            assert str(now.year) in path
            assert f"{now.month:02d}" in path
        finally:
            storage_logic.STORAGE_ROOT = original

    def test_filename_contains_doc_id(self, tmp_path):
        original = storage_logic.STORAGE_ROOT
        storage_logic.STORAGE_ROOT = str(tmp_path)
        try:
            doc_id = str(uuid.uuid4())
            path = storage_logic.save_to_filesystem(doc_id, b"%PDF-1.4")
            assert doc_id in path
        finally:
            storage_logic.STORAGE_ROOT = original


# ---------------------------------------------------------------------------
# create_symlink
# ---------------------------------------------------------------------------

class TestCreateSymlink:
    def test_returns_empty_when_symlink_root_empty(self, tmp_path):
        original = storage_logic.SYMLINK_ROOT
        storage_logic.SYMLINK_ROOT = ""
        try:
            result = storage_logic.create_symlink("doc-id", str(tmp_path / "file.pdf"))
            assert result == ""
        finally:
            storage_logic.SYMLINK_ROOT = original

    def test_creates_symlink_when_root_set(self, tmp_path):
        link_root = str(tmp_path / "links")
        os.makedirs(link_root, exist_ok=True)

        # Create a real file to link to
        target = tmp_path / "real.pdf"
        target.write_bytes(b"%PDF-1.4")

        original = storage_logic.SYMLINK_ROOT
        storage_logic.SYMLINK_ROOT = link_root
        try:
            doc_id = str(uuid.uuid4())
            link_path = storage_logic.create_symlink(doc_id, str(target))
            if link_path:  # On Windows, os.symlink may not be available
                assert os.path.exists(link_path)
        except (OSError, NotImplementedError):
            pass  # Symlinks may not be available on Windows test env
        finally:
            storage_logic.SYMLINK_ROOT = original


# ---------------------------------------------------------------------------
# process_document
# ---------------------------------------------------------------------------

class TestStorageProcessDocument:
    @pytest.mark.asyncio
    async def test_file_bytes_removed_from_payload(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        result = await storage_logic.process_document(payload)
        assert "file_bytes" not in result

    @pytest.mark.asyncio
    async def test_storage_path_added_to_payload(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        result = await storage_logic.process_document(payload)
        assert "storage_path" in result
        assert result["storage_path"] is not None

    @pytest.mark.asyncio
    async def test_file_actually_written_to_disk(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        result = await storage_logic.process_document(payload)
        assert os.path.isfile(result["storage_path"])

    @pytest.mark.asyncio
    async def test_document_status_set_to_stored(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        doc_id = payload["workflow_id"]
        await storage_logic.process_document(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.status == "STORED"

    @pytest.mark.asyncio
    async def test_file_size_stored_in_db(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        doc_id = payload["workflow_id"]
        await storage_logic.process_document(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.file_size_bytes == len(pdf)

    @pytest.mark.asyncio
    async def test_storage_path_stored_in_db(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        doc_id = payload["workflow_id"]
        result = await storage_logic.process_document(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.storage_path == result["storage_path"]

    @pytest.mark.asyncio
    async def test_adds_to_history(self):
        pdf = _make_pdf_bytes()
        payload = _make_pipeline_payload(pdf)
        result = await storage_logic.process_document(payload)
        assert "storage_completed" in result["history"]
