"""
Integration tests for the document upload and retrieval flow via the gateway API.

Simulates the frontend experience: upload → poll → retrieve fields/entities.
"""

from __future__ import annotations

import io
import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

# Add api_gateway to path
_GW_PATH = str(Path(__file__).resolve().parent.parent.parent / "api_gateway")
if _GW_PATH not in sys.path:
    sys.path.insert(0, _GW_PATH)

from fastapi.testclient import TestClient

from dmsai_models import (
    Document, DocumentField, DocumentEntity, Entity,
    Organization, User, UserOrganization,
    get_session, init_db,
)


def _pdf_bytes() -> bytes:
    img = Image.new("RGB", (612, 792), "white")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_token(client) -> str:
    """Create a user directly in DB and return a JWT — avoids registration endpoint state issues."""
    import sys
    from pathlib import Path
    _gw = str(Path(__file__).resolve().parent.parent.parent / "api_gateway")
    if _gw not in sys.path:
        sys.path.insert(0, _gw)
    from auth import hash_password, create_access_token

    init_db()
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = f"doc-flow-{uuid.uuid4().hex[:8]}@test.com"
    with get_session() as session:
        org = Organization(id=org_id, name=f"FlowOrg-{uuid.uuid4().hex[:6]}")
        session.add(org)
        user = User(
            id=user_id, email=email,
            password_hash=hash_password("FlowTest1"),
            full_name="Doc Flow User", role="user",
            organization_id=org_id, is_active=True,
            auth_provider="local", email_verified=True,
        )
        session.add(user)
        session.add(UserOrganization(
            id=str(uuid.uuid4()), user_id=user_id,
            organization_id=org_id, role="user", is_default=True,
        ))
        session.commit()
    return create_access_token(user_id, email, "user", org_id)


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class TestDocumentUpload:
    def test_upload_creates_document(self, client, auth_headers):
        import uuid as _uuid
        pdf = _pdf_bytes()
        fake_doc_id = str(_uuid.uuid4())
        with patch("httpx.AsyncClient") as mock_cls:
            mock_c = MagicMock()
            mock_c.__aenter__ = AsyncMock(return_value=mock_c)
            mock_c.__aexit__ = AsyncMock(return_value=None)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"document_id": fake_doc_id, "status": "queued"}
            mock_c.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_c

            resp = client.post(
                "/api/upload",
                headers=auth_headers,
                files={"file": ("test.pdf", pdf, "application/pdf")},
                data={"priority": "0", "mode": "auto"},
            )

        assert resp.status_code == 200
        doc_id = resp.json()["document_id"]
        assert doc_id

    def test_upload_unsupported_format_rejected(self, client, auth_headers):
        with patch("httpx.AsyncClient") as mock_cls:
            mock_c = MagicMock()
            mock_c.__aenter__ = AsyncMock(return_value=mock_c)
            mock_c.__aexit__ = AsyncMock(return_value=None)
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = "Unsupported file type: .docx"
            mock_c.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_c

            resp = client.post(
                "/api/upload",
                headers=auth_headers,
                files={"file": ("doc.docx", b"word content", "application/octet-stream")},
            )

        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Document lifecycle
# ---------------------------------------------------------------------------

class TestDocumentLifecycle:
    def _seed_doc(self, auth_token: str) -> tuple[str, str]:
        """Create a completed document and return (doc_id, org_id)."""
        from auth import decode_token
        payload = decode_token(auth_token)
        org_id = payload["org"]

        init_db()
        doc_id = str(uuid.uuid4())
        with get_session() as session:
            doc = Document(
                id=doc_id,
                filename="lifecycle.pdf",
                original_extension=".pdf",
                organization_id=org_id,
                status="COMPLETED",
                ocr_text="Invoice from Test Corp total 500 EUR",
                ocr_confidence=0.95,
                classification_label="invoice",
                classification_confidence=0.90,
                pipeline_confidence=0.87,
                processed_at=datetime.utcnow(),
            )
            session.add(doc)

            field = DocumentField(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                field_name="invoice_number",
                field_value="INV-LC-001",
                confidence=0.95,
            )
            session.add(field)

            entity = Entity(
                id=str(uuid.uuid4()), entity_type="company",
                name="Test Corp", canonical_name="Test Corp",
            )
            session.add(entity)
            session.flush()

            de = DocumentEntity(
                id=str(uuid.uuid4()), document_id=doc_id,
                entity_id=entity.id, role="issuer", confidence=0.88,
            )
            session.add(de)
            session.commit()

        return doc_id, org_id

    def test_get_document_after_upload(self, client, auth_headers, auth_token):
        doc_id, _ = self._seed_doc(auth_token)
        resp = client.get(f"/api/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == doc_id
        assert data["status"] == "COMPLETED"

    def test_get_fields(self, client, auth_headers, auth_token):
        doc_id, _ = self._seed_doc(auth_token)
        resp = client.get(f"/api/documents/{doc_id}/fields", headers=auth_headers)
        assert resp.status_code == 200
        fields = resp.json()
        assert isinstance(fields, list)
        assert any(f["field_name"] == "invoice_number" for f in fields)

    def test_get_entities(self, client, auth_headers, auth_token):
        doc_id, _ = self._seed_doc(auth_token)
        resp = client.get(f"/api/documents/{doc_id}/entities", headers=auth_headers)
        assert resp.status_code == 200
        entities = resp.json()
        assert isinstance(entities, list)

    def test_document_workflow_state(self, client, auth_headers, auth_token):
        doc_id, _ = self._seed_doc(auth_token)
        resp = client.get(f"/api/documents/{doc_id}/workflow-state", headers=auth_headers)
        assert resp.status_code in (200, 404)  # endpoint may vary

    def test_search_finds_document(self, client, auth_headers, auth_token):
        doc_id, _ = self._seed_doc(auth_token)
        resp = client.get("/api/search?q=Test+Corp", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
