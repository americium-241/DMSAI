"""Unit tests for shared/dmsai_models/pipeline_events.py."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from dmsai_models import Document, Organization, PipelineEvent, get_session, init_db
from dmsai_models.pipeline_events import record_pipeline_event


def _make_doc_in_db() -> str:
    """Insert a Document into the test DB and return its id."""
    init_db()
    doc_id = str(uuid.uuid4())
    with get_session() as session:
        org = Organization(id=str(uuid.uuid4()), name=f"PEOrg-{doc_id[:8]}")
        session.add(org)
        session.flush()
        doc = Document(
            id=doc_id, filename="pe_test.pdf",
            original_extension=".pdf", organization_id=org.id,
        )
        session.add(doc)
        session.commit()
    return doc_id


class TestRecordPipelineEvent:
    def test_inserts_event_row(self):
        doc_id = _make_doc_in_db()
        record_pipeline_event(doc_id, "ocr", "started")

        with get_session() as session:
            events = session.exec(
                select(PipelineEvent).where(PipelineEvent.document_id == doc_id)
            ).all()
        assert len(events) >= 1
        assert events[0].stage == "ocr"
        assert events[0].event_type == "started"

    def test_stage_and_event_type_stored(self):
        doc_id = _make_doc_in_db()
        record_pipeline_event(doc_id, "classification", "completed")

        with get_session() as session:
            event = session.exec(
                select(PipelineEvent).where(
                    PipelineEvent.document_id == doc_id,
                    PipelineEvent.stage == "classification",
                )
            ).first()
        assert event is not None
        assert event.event_type == "completed"

    def test_details_stored_when_provided(self):
        doc_id = _make_doc_in_db()
        record_pipeline_event(doc_id, "ingestion", "failed", details="timeout")

        with get_session() as session:
            event = session.exec(
                select(PipelineEvent).where(
                    PipelineEvent.document_id == doc_id,
                    PipelineEvent.event_type == "failed",
                )
            ).first()
        assert event is not None
        assert event.details == "timeout"

    def test_multiple_events_for_same_document(self):
        doc_id = _make_doc_in_db()
        stages = [
            ("ingestion", "started"),
            ("ingestion", "completed"),
            ("conversion", "started"),
            ("conversion", "completed"),
        ]
        for stage, event_type in stages:
            record_pipeline_event(doc_id, stage, event_type)

        with get_session() as session:
            events = session.exec(
                select(PipelineEvent).where(PipelineEvent.document_id == doc_id)
            ).all()
        assert len(events) >= 4
        recorded = {(e.stage, e.event_type) for e in events}
        for stage, event_type in stages:
            assert (stage, event_type) in recorded

    def test_event_has_timestamp(self):
        doc_id = _make_doc_in_db()
        record_pipeline_event(doc_id, "storage", "started")

        with get_session() as session:
            event = session.exec(
                select(PipelineEvent).where(
                    PipelineEvent.document_id == doc_id,
                    PipelineEvent.stage == "storage",
                )
            ).first()
        assert event is not None
        assert event.timestamp is not None

    def test_each_event_has_unique_id(self):
        doc_id = _make_doc_in_db()
        record_pipeline_event(doc_id, "ocr", "started")
        record_pipeline_event(doc_id, "ocr", "completed")

        with get_session() as session:
            events = session.exec(
                select(PipelineEvent).where(PipelineEvent.document_id == doc_id)
            ).all()
        ids = [e.id for e in events]
        assert len(ids) == len(set(ids)), "Event IDs should be unique"
