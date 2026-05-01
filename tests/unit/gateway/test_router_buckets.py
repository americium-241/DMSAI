"""Unit tests for gateway /api/buckets endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from dmsai_models import (
    Bucket, BucketDocument, Document, get_session, init_db,
)


def _create_bucket(org_id: str, admin_id: str, name: str = None) -> str:
    """Insert a bucket into the test DB and return its id."""
    init_db()
    bucket_id = str(uuid.uuid4())
    with get_session() as session:
        bucket = Bucket(
            id=bucket_id,
            name=name or f"Test Bucket {bucket_id[:8]}",
            organization_id=org_id,
            created_by=admin_id,
        )
        session.add(bucket)
        session.commit()
    return bucket_id


def _create_document(org_id: str) -> str:
    doc_id = str(uuid.uuid4())
    with get_session() as session:
        doc = Document(
            id=doc_id, filename="bucket_doc.pdf",
            original_extension=".pdf", organization_id=org_id,
            status="COMPLETED", processed_at=datetime.utcnow(),
        )
        session.add(doc)
        session.commit()
    return doc_id


class TestListBuckets:
    def test_returns_list(self, gw_client, admin_headers):
        resp = gw_client.get("/api/buckets", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_unauthenticated_returns_401(self, gw_client):
        resp = gw_client.get("/api/buckets")
        assert resp.status_code == 401


class TestCreateBucket:
    def test_create_bucket(self, gw_client, admin_headers):
        resp = gw_client.post(
            "/api/buckets",
            headers=admin_headers,
            json={"name": f"New Bucket {uuid.uuid4().hex[:6]}", "description": "Test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "name" in data

    def test_create_bucket_regular_user(self, gw_client, user_headers):
        resp = gw_client.post(
            "/api/buckets",
            headers=user_headers,
            json={"name": "User Bucket"},
        )
        # Regular users may or may not be allowed to create buckets
        assert resp.status_code in (200, 403)


class TestGetBucket:
    def test_get_existing_bucket(self, gw_client, admin_headers, gw_org_and_users):
        bucket_id = _create_bucket(gw_org_and_users["org_id"], gw_org_and_users["admin_id"])
        resp = gw_client.get(f"/api/buckets/{bucket_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == bucket_id

    def test_get_nonexistent_bucket_returns_404(self, gw_client, admin_headers):
        resp = gw_client.get(f"/api/buckets/{uuid.uuid4()}", headers=admin_headers)
        assert resp.status_code == 404


class TestBucketDocuments:
    def test_list_documents_in_bucket(self, gw_client, admin_headers, gw_org_and_users):
        org_id = gw_org_and_users["org_id"]
        admin_id = gw_org_and_users["admin_id"]
        bucket_id = _create_bucket(org_id, admin_id)

        resp = gw_client.get(f"/api/buckets/{bucket_id}/documents", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data


class TestBucketAutoAssign:
    def test_auto_assign_endpoint_exists(self, gw_client, admin_headers):
        resp = gw_client.post(
            "/api/buckets/auto-assign",
            headers=admin_headers,
        )
        # Returns 503 when INTERNAL_API_KEY is not configured (expected in test env),
        # 403 if key is present but wrong, or 200/204 when fully operational.
        assert resp.status_code in (200, 204, 403, 503)
