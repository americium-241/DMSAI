"""Unit tests for gateway collaboration (comments) endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from dmsai_models import Document, DocumentComment, get_session, init_db


def _create_doc(org_id: str) -> str:
    init_db()
    doc_id = str(uuid.uuid4())
    with get_session() as session:
        doc = Document(
            id=doc_id, filename="collab_test.pdf",
            original_extension=".pdf", organization_id=org_id,
        )
        session.add(doc)
        session.commit()
    return doc_id


class TestDocumentComments:
    def test_create_comment(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        resp = gw_client.post(
            f"/api/documents/{doc_id}/comments",
            headers=admin_headers,
            json={"content": "This looks like an invoice from ACME."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        # The create endpoint returns {"id": ..., "status": "created"} (not full comment object)
        assert data.get("status") == "created"

    def test_list_comments(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        # Create a comment first
        gw_client.post(
            f"/api/documents/{doc_id}/comments",
            headers=admin_headers,
            json={"content": "A test comment"},
        )
        resp = gw_client.get(f"/api/documents/{doc_id}/comments", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert any(c["content"] == "A test comment" for c in data)

    def test_update_comment(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        create_resp = gw_client.post(
            f"/api/documents/{doc_id}/comments",
            headers=admin_headers,
            json={"content": "Original comment"},
        )
        comment_id = create_resp.json()["id"]

        resp = gw_client.put(
            f"/api/documents/{doc_id}/comments/{comment_id}",
            headers=admin_headers,
            json={"content": "Updated comment"},
        )
        assert resp.status_code == 200

    def test_delete_comment(self, gw_client, admin_headers, org_id):
        doc_id = _create_doc(org_id)
        create_resp = gw_client.post(
            f"/api/documents/{doc_id}/comments",
            headers=admin_headers,
            json={"content": "To be deleted"},
        )
        comment_id = create_resp.json()["id"]

        resp = gw_client.delete(
            f"/api/documents/{doc_id}/comments/{comment_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_comment_missing_doc_returns_404(self, gw_client, admin_headers):
        resp = gw_client.post(
            f"/api/documents/{uuid.uuid4()}/comments",
            headers=admin_headers,
            json={"content": "ghost comment"},
        )
        assert resp.status_code == 404

    def test_unauthenticated_returns_401(self, gw_client, org_id):
        doc_id = _create_doc(org_id)
        resp = gw_client.get(f"/api/documents/{doc_id}/comments")
        assert resp.status_code == 401
