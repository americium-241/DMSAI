"""Unit tests for shared/dmsai_models/models.py — SQLModel definitions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from dmsai_models import (
    Document, Organization, User, Bucket, BucketRule, BucketDocument,
    BucketPermission, Entity, EntityField, DocumentEntity, DocumentField,
    CanonicalField, CanonicalDocumentClass, DocumentComment, PipelineEvent,
    SystemConfig, Correction, DocumentAuditLog, DocumentVersion,
    get_session, init_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _make_org(session, name="Test Org") -> Organization:
    org = Organization(id=_uuid(), name=name)
    session.add(org)
    session.flush()
    return org


def _make_user(session, org_id: str, email=None, role="user") -> User:
    email = email or f"user-{_uuid()[:8]}@test.com"
    user = User(
        id=_uuid(), email=email, password_hash="hashed",
        full_name="Test User", role=role, organization_id=org_id,
    )
    session.add(user)
    session.flush()
    return user


def _make_doc(session, org_id: str | None = None) -> Document:
    doc = Document(
        id=_uuid(), filename="test.pdf", original_extension=".pdf",
        organization_id=org_id,
    )
    session.add(doc)
    session.flush()
    return doc


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

class TestDocument:
    def test_default_status(self):
        doc = Document(id=_uuid(), filename="a.pdf", original_extension=".pdf")
        assert doc.status == "INGESTED"

    def test_default_source(self):
        doc = Document(id=_uuid(), filename="a.pdf", original_extension=".pdf")
        assert doc.source == "api"

    def test_default_mode(self):
        doc = Document(id=_uuid(), filename="a.pdf", original_extension=".pdf")
        assert doc.mode == "auto"

    def test_optional_fields_none_by_default(self):
        doc = Document(id=_uuid(), filename="a.pdf", original_extension=".pdf")
        assert doc.ocr_text is None
        assert doc.ocr_confidence is None
        assert doc.classification_label is None
        assert doc.pipeline_confidence is None
        assert doc.archived_at is None
        assert doc.trashed_at is None

    def test_document_persists_to_db(self):
        init_db()
        with get_session() as session:
            org = _make_org(session)
            doc = _make_doc(session, org.id)
            doc_id = doc.id
            session.commit()

        with get_session() as session:
            fetched = session.get(Document, doc_id)
            assert fetched is not None
            assert fetched.filename == "test.pdf"

    def test_status_update(self):
        init_db()
        with get_session() as session:
            org = _make_org(session)
            doc = _make_doc(session, org.id)
            doc_id = doc.id
            session.commit()

        with get_session() as session:
            doc = session.get(Document, doc_id)
            doc.status = "OCR_DONE"
            doc.ocr_text = "Some text"
            doc.ocr_confidence = 0.95
            session.add(doc)
            session.commit()

        with get_session() as session:
            doc = session.get(Document, doc_id)
            assert doc.status == "OCR_DONE"
            assert doc.ocr_confidence == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# Organization and User models
# ---------------------------------------------------------------------------

class TestOrganizationUser:
    def test_organization_persists(self):
        init_db()
        with get_session() as session:
            org_id = _uuid()
            org = Organization(id=org_id, name="Acme Inc.")
            session.add(org)
            session.commit()

        with get_session() as session:
            fetched = session.get(Organization, org_id)
            assert fetched.name == "Acme Inc."

    def test_user_defaults(self):
        user = User(
            id=_uuid(), email="a@b.com", full_name="A B",
            organization_id=_uuid(),
        )
        assert user.role == "user"
        assert user.is_active is True
        assert user.auth_provider == "local"
        assert user.email_verified is False
        assert user.failed_login_attempts == 0

    def test_user_unique_email_constraint(self):
        init_db()
        with get_session() as session:
            org = _make_org(session)
            email = f"unique-{_uuid()[:8]}@test.com"
            _make_user(session, org.id, email=email)
            session.commit()

        # Second user with same email should raise
        with get_session() as session:
            org2 = _make_org(session, name="Org2")
            user2 = User(
                id=_uuid(), email=email, password_hash="h",
                full_name="X", organization_id=org2.id,
            )
            session.add(user2)
            with pytest.raises(Exception):
                session.commit()


# ---------------------------------------------------------------------------
# Bucket models
# ---------------------------------------------------------------------------

class TestBucketModels:
    def test_bucket_defaults(self):
        bucket = Bucket(id=_uuid(), name="My Bucket", organization_id=_uuid(), created_by=_uuid())
        assert bucket.description is None

    def test_bucket_rule_defaults(self):
        rule = BucketRule(id=_uuid(), bucket_id=_uuid(), field="status", value="COMPLETED")
        assert rule.operator == "equals"

    def test_bucket_document_defaults(self):
        bd = BucketDocument(id=_uuid(), bucket_id=_uuid(), document_id=_uuid())
        assert bd.workflow_state == "open"
        assert bd.locked_by is None

    def test_bucket_permission_defaults(self):
        bp = BucketPermission(id=_uuid(), bucket_id=_uuid(), user_id=_uuid())
        assert bp.permission == "view"


# ---------------------------------------------------------------------------
# Entity and Field models
# ---------------------------------------------------------------------------

class TestEntityModels:
    def test_entity_defaults(self):
        entity = Entity(id=_uuid(), entity_type="company", name="ACME Corp")
        assert entity.canonical_name is None
        assert entity.updated_at is None

    def test_entity_field_defaults(self):
        ef = EntityField(id=_uuid(), entity_id=_uuid(), field_name="email", field_value="a@b.com")
        assert ef.confidence == pytest.approx(1.0)

    def test_document_entity_defaults(self):
        de = DocumentEntity(id=_uuid(), document_id=_uuid(), entity_id=_uuid(), role="issuer")
        assert de.confidence == pytest.approx(1.0)

    def test_document_field_defaults(self):
        df = DocumentField(
            id=_uuid(), document_id=_uuid(), field_name="invoice_number", field_value="INV-001"
        )
        assert df.confidence == pytest.approx(1.0)
        assert df.extraction_method == "auto"

    def test_canonical_field_aliases_json(self):
        cf = CanonicalField(
            id=_uuid(), scope="document", canonical_name="invoice_number",
            aliases=json.dumps(["numero_facture", "inv_num"]),
        )
        parsed = json.loads(cf.aliases)
        assert "numero_facture" in parsed

    def test_canonical_document_class_unique_name(self):
        """CanonicalDocumentClass.canonical_name has a unique constraint."""
        init_db()
        with get_session() as session:
            name = f"test_class_{_uuid()[:8]}"
            cdc = CanonicalDocumentClass(id=_uuid(), canonical_name=name)
            session.add(cdc)
            session.commit()

        with get_session() as session:
            duplicate = CanonicalDocumentClass(id=_uuid(), canonical_name=name)
            session.add(duplicate)
            with pytest.raises(Exception):
                session.commit()


# ---------------------------------------------------------------------------
# Pipeline event and SystemConfig models
# ---------------------------------------------------------------------------

class TestObservabilityModels:
    def test_pipeline_event_defaults(self):
        ev = PipelineEvent(
            id=_uuid(), document_id=_uuid(), stage="ocr", event_type="started"
        )
        assert ev.details is None

    def test_system_config_defaults(self):
        sc = SystemConfig(key="test_key", value="test_value")
        assert sc.category == "general"

    def test_document_audit_log_defaults(self):
        log = DocumentAuditLog(
            id=_uuid(), document_id=_uuid(), action="field_updated"
        )
        assert log.user_id is None
        assert log.entity_id is None

    def test_document_version_defaults(self):
        ver = DocumentVersion(
            id=_uuid(), document_id=_uuid(), version_number=1
        )
        assert ver.summary == ""
        assert ver.snapshot_json is None
