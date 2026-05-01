"""Unit tests for gateway /api/documents and /api/upload endpoints."""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from dmsai_models import (
    Document, DocumentField, DocumentEntity, Entity,
    Organization, PipelineEvent, get_session, init_db,
)


def _make_pdf_bytes() -> bytes:
    img = Image.new("RGB", (612, 792), "white")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _seed_completed_document(org_id: str) -> str:
    """Create a fully-processed Document in the test DB and return its id."""
    init_db()
    doc_id = str(uuid.uuid4())
    with get_session() as session:
        doc = Document(
            id=doc_id,
            filename="gateway_test.pdf",
            original_extension=".pdf",
            organization_id=org_id,
            status="COMPLETED",
            ocr_text="Invoice total 1200 EUR ACME Corp",
            ocr_confidence=0.95,
            classification_label="invoice",
            classification_confidence=0.92,
            pipeline_confidence=0.88,
            processed_at=datetime.utcnow(),
        )
        session.add(doc)

        field = DocumentField(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            field_name="invoice_number",
            field_value="INV-2026-001",
            confidence=0.95,
        )
        session.add(field)

        entity = Entity(
            id=str(uuid.uuid4()), entity_type="company",
            name="ACME Corp", canonical_name="ACME Corp",
        )
        session.add(entity)
        session.flush()

        de = DocumentEntity(
            id=str(uuid.uuid4()), document_id=doc_id,
            entity_id=entity.id, role="issuer", confidence=0.9,
        )
        session.add(de)

        ev = PipelineEvent(
            id=str(uuid.uuid4()), document_id=doc_id,
            stage="field_extraction", event_type="completed",
        )
        session.add(ev)
        session.commit()

    return doc_id


class TestListDocuments:
    def test_returns_list(self, gw_client, admin_headers):
        resp = gw_client.get("/api/documents", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert "total" in data

    def test_unauthenticated_returns_401(self, gw_client):
        resp = gw_client.get("/api/documents")
        assert resp.status_code == 401

    def test_pagination_params_accepted(self, gw_client, admin_headers):
        resp = gw_client.get("/api/documents?page=1&page_size=5", headers=admin_headers)
        assert resp.status_code == 200


class TestGetDocument:
    def test_existing_document_returns_200(self, gw_client, admin_headers, org_id):
        doc_id = _seed_completed_document(org_id)
        resp = gw_client.get(f"/api/documents/{doc_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == doc_id
        assert data["status"] == "COMPLETED"

    def test_nonexistent_document_returns_404(self, gw_client, admin_headers):
        resp = gw_client.get(f"/api/documents/{uuid.uuid4()}", headers=admin_headers)
        assert resp.status_code == 404

    def test_document_from_other_org_returns_404(self, gw_client, admin_headers):
        # Create a document in a different org
        other_org_id = str(uuid.uuid4())
        with get_session() as session:
            other_org = Organization(id=other_org_id, name="Other Org")
            session.add(other_org)
            session.commit()

        other_doc_id = _seed_completed_document(other_org_id)
        resp = gw_client.get(f"/api/documents/{other_doc_id}", headers=admin_headers)
        assert resp.status_code == 404


class TestDocumentFields:
    def test_get_fields_returns_list(self, gw_client, admin_headers, org_id):
        doc_id = _seed_completed_document(org_id)
        resp = gw_client.get(f"/api/documents/{doc_id}/fields", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            assert "field_name" in data[0]
            assert "field_value" in data[0]

    def test_missing_doc_returns_404(self, gw_client, admin_headers):
        resp = gw_client.get(f"/api/documents/{uuid.uuid4()}/fields", headers=admin_headers)
        assert resp.status_code == 404


class TestDocumentEntities:
    def test_get_entities_returns_list(self, gw_client, admin_headers, org_id):
        doc_id = _seed_completed_document(org_id)
        resp = gw_client.get(f"/api/documents/{doc_id}/entities", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_missing_doc_returns_404(self, gw_client, admin_headers):
        resp = gw_client.get(f"/api/documents/{uuid.uuid4()}/entities", headers=admin_headers)
        assert resp.status_code == 404


class TestDocumentEvents:
    def test_get_events_returns_list(self, gw_client, admin_headers, org_id):
        doc_id = _seed_completed_document(org_id)
        resp = gw_client.get(f"/api/documents/{doc_id}/events", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Endpoint wraps results: {"events": [...]}
        assert isinstance(data.get("events"), list)


class TestSearch:
    def test_search_returns_results_shape(self, gw_client, admin_headers):
        resp = gw_client.get("/api/search?q=invoice", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data


class TestUpload:
    def test_upload_pdf_returns_document_id(self, gw_client, admin_headers):
        import uuid as _uuid
        pdf = _make_pdf_bytes()
        fake_doc_id = str(_uuid.uuid4())
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"document_id": fake_doc_id, "status": "queued"}
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            resp = gw_client.post(
                "/api/upload",
                headers=admin_headers,
                files={"file": ("invoice.pdf", pdf, "application/pdf")},
                data={"priority": "0", "mode": "auto"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "document_id" in data
