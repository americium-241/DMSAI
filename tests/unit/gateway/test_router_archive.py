"""Unit tests for gateway archive/trash/version endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from dmsai_models import Document, get_session, init_db


def _create_doc(org_id: str, status: str = "COMPLETED") -> str:
    init_db()
    doc_id = str(uuid.uuid4())
    with get_session() as session:
        doc = Document(
            id=doc_id, filename="archive_test.pdf",
            original_extension=".pdf", organization_id=org_id,
            status=status, processed_at=datetime.utcnow(),
        )
        session.add(doc)
        session.commit()
    return doc_id


class TestArchiveDocument:
    def test_archive_document(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        resp = gw_client.post(f"/api/documents/{doc_id}/archive", headers=admin_headers)
        assert resp.status_code == 200

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.archived_at is not None

    def test_unarchive_document(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        gw_client.post(f"/api/documents/{doc_id}/archive", headers=admin_headers)
        resp = gw_client.post(f"/api/documents/{doc_id}/unarchive", headers=admin_headers)
        assert resp.status_code == 200

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.archived_at is None

    def test_archive_nonexistent_returns_404(self, gw_client, admin_headers):
        resp = gw_client.post(f"/api/documents/{uuid.uuid4()}/archive", headers=admin_headers)
        assert resp.status_code == 404


class TestTrashDocument:
    def test_trash_document(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        resp = gw_client.post(f"/api/documents/{doc_id}/trash", headers=admin_headers)
        assert resp.status_code == 200

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.trashed_at is not None

    def test_restore_document(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        gw_client.post(f"/api/documents/{doc_id}/trash", headers=admin_headers)
        resp = gw_client.post(f"/api/documents/{doc_id}/restore", headers=admin_headers)
        assert resp.status_code == 200

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.trashed_at is None

    def test_permanent_delete(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        gw_client.post(f"/api/documents/{doc_id}/trash", headers=admin_headers)
        resp = gw_client.delete(f"/api/documents/{doc_id}/permanent", headers=admin_headers)
        assert resp.status_code == 200

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc is None


class TestDocumentVersions:
    def test_list_versions(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        resp = gw_client.get(f"/api/documents/{doc_id}/versions", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_audit_log(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        # Perform an action to generate audit log
        gw_client.post(f"/api/documents/{doc_id}/archive", headers=admin_headers)
        resp = gw_client.get(f"/api/documents/{doc_id}/audit-log", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
