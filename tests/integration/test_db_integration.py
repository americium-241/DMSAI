"""Integration tests for the shared database layer."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import inspect
from sqlmodel import select

from dmsai_models import (
    CanonicalField, Document, DocumentEntity, DocumentField,
    Entity, EntityField, Organization, PipelineEvent,
    User, get_session, init_db,
)
from dmsai_models.connection import get_engine


def _uuid() -> str:
    return str(uuid.uuid4())


def _create_org_and_doc() -> tuple[str, str]:
    """Create an Organization + Document and return (org_id, doc_id)."""
    init_db()
    org_id = _uuid()
    doc_id = _uuid()
    with get_session() as session:
        org = Organization(id=org_id, name=f"Integration Org {org_id[:8]}")
        session.add(org)
        session.flush()
        doc = Document(
            id=doc_id, filename="integration.pdf",
            original_extension=".pdf", organization_id=org_id,
        )
        session.add(doc)
        session.commit()
    return org_id, doc_id


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------

class TestSchemaIntegrity:
    def test_all_expected_tables_present(self):
        init_db()
        engine = get_engine()
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        for table in ["document", "organization", "user", "entity", "systemconfig"]:
            assert table in tables

    def test_document_table_has_all_columns(self):
        init_db()
        engine = get_engine()
        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("document")}
        expected = {
            "id", "filename", "status", "ocr_text", "ocr_confidence",
            "classification_label", "pipeline_confidence",
            "archived_at", "trashed_at", "confidence_details",
        }
        assert expected.issubset(cols)


# ---------------------------------------------------------------------------
# Cascade: Document → related tables
# ---------------------------------------------------------------------------

class TestCascadeRelations:
    def test_document_with_fields_and_entities(self):
        """Insert Document + DocumentField + DocumentEntity and query them back."""
        init_db()
        org_id, doc_id = _create_org_and_doc()

        entity_id = _uuid()
        with get_session() as session:
            entity = Entity(
                id=entity_id, entity_type="company",
                name="Cascade Corp", canonical_name="Cascade Corp",
            )
            session.add(entity)
            session.flush()

            df = DocumentField(
                id=_uuid(), document_id=doc_id,
                field_name="invoice_number", field_value="INV-INT-001",
                confidence=0.95,
            )
            session.add(df)

            de = DocumentEntity(
                id=_uuid(), document_id=doc_id,
                entity_id=entity_id, role="issuer", confidence=0.9,
            )
            session.add(de)
            session.commit()

        with get_session() as session:
            fields = session.exec(
                select(DocumentField).where(DocumentField.document_id == doc_id)
            ).all()
            entities = session.exec(
                select(DocumentEntity).where(DocumentEntity.document_id == doc_id)
            ).all()

        assert len(fields) >= 1
        assert fields[0].field_name == "invoice_number"
        assert len(entities) >= 1
        assert entities[0].role == "issuer"

    def test_entity_fields_attached_to_entity(self):
        init_db()
        entity_id = _uuid()
        with get_session() as session:
            entity = Entity(id=entity_id, entity_type="person", name="Jane Smith")
            session.add(entity)
            session.flush()
            for key, val in [("email", "jane@example.com"), ("phone", "+33123456789")]:
                ef = EntityField(
                    id=_uuid(), entity_id=entity_id,
                    field_name=key, field_value=val,
                )
                session.add(ef)
            session.commit()

        with get_session() as session:
            efs = session.exec(
                select(EntityField).where(EntityField.entity_id == entity_id)
            ).all()
        assert len(efs) == 2
        keys = {ef.field_name for ef in efs}
        assert "email" in keys and "phone" in keys


# ---------------------------------------------------------------------------
# Transaction isolation
# ---------------------------------------------------------------------------

class TestTransactionIsolation:
    def test_uncommitted_changes_not_visible_in_other_session(self):
        init_db()
        doc_id = _uuid()
        org_id = _uuid()

        with get_session() as session:
            org = Organization(id=org_id, name="TX Org")
            session.add(org)
            session.commit()

        # Start session A, add doc but don't commit
        session_a = get_session()
        doc = Document(
            id=doc_id, filename="tx_test.pdf",
            original_extension=".pdf", organization_id=org_id,
        )
        session_a.add(doc)
        # Don't commit

        # In session B, the doc should not be visible
        with get_session() as session_b:
            result = session_b.get(Document, doc_id)
        assert result is None

        session_a.rollback()
        session_a.close()

    def test_commit_makes_changes_visible(self):
        init_db()
        org_id, doc_id = _create_org_and_doc()

        with get_session() as session:
            doc = session.get(Document, doc_id)
            assert doc is not None
            assert doc.status == "INGESTED"

        with get_session() as session:
            doc = session.get(Document, doc_id)
            doc.status = "OCR_DONE"
            session.add(doc)
            session.commit()

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.status == "OCR_DONE"


# ---------------------------------------------------------------------------
# Canonical fields seeding
# ---------------------------------------------------------------------------

class TestCanonicalFieldSeeding:
    def test_entity_scope_fields_seeded(self):
        init_db()
        with get_session() as session:
            fields = session.exec(
                select(CanonicalField).where(CanonicalField.scope == "entity")
            ).all()
        assert len(fields) >= 5  # At least tax_id, email, phone, address, registration_number

    def test_field_aliases_are_valid_json(self):
        init_db()
        with get_session() as session:
            fields = session.exec(select(CanonicalField)).all()
        for cf in fields:
            # Each aliases field should be valid JSON array
            parsed = json.loads(cf.aliases)
            assert isinstance(parsed, list)

    def test_canonical_field_tax_id_has_aliases(self):
        init_db()
        with get_session() as session:
            cf = session.exec(
                select(CanonicalField).where(
                    CanonicalField.canonical_name == "tax_id",
                    CanonicalField.scope == "entity",
                )
            ).first()
        assert cf is not None
        aliases = json.loads(cf.aliases)
        assert len(aliases) > 0  # Should have at least one alias


# ---------------------------------------------------------------------------
# Pipeline events
# ---------------------------------------------------------------------------

class TestPipelineEventIntegration:
    def test_multiple_stages_recorded(self):
        init_db()
        _, doc_id = _create_org_and_doc()

        stages = [
            ("ingestion", "started"), ("ingestion", "completed"),
            ("ocr", "started"), ("ocr", "completed"),
            ("classification", "started"), ("classification", "completed"),
        ]
        for stage, event_type in stages:
            ev = PipelineEvent(
                id=_uuid(), document_id=doc_id,
                stage=stage, event_type=event_type,
            )
            with get_session() as session:
                session.add(ev)
                session.commit()

        with get_session() as session:
            events = session.exec(
                select(PipelineEvent).where(PipelineEvent.document_id == doc_id)
            ).all()

        assert len(events) == len(stages)
        stage_names = {e.stage for e in events}
        assert {"ingestion", "ocr", "classification"}.issubset(stage_names)
