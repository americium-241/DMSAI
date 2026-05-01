"""Unit tests for nodes/field_extraction_node/src/field_extraction_logic.py."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from dmsai_models import (
    CanonicalField, Document, DocumentField, get_session, init_db,
)
from fixtures.mock_responses import (
    MOCK_FIELD_DETECT_RESPONSE,
    MOCK_FIELD_EXTRACT_RESPONSE,
    MOCK_CANONICAL_MAP_EXISTING,
    MOCK_CANONICAL_MAP_NEW,
    make_llm_side_effect,
)

field_extraction_logic = sys.modules["field_extraction_logic"]
ingestion_logic = sys.modules["ingestion_logic"]


def _make_payload(ocr_text: str = "Invoice INV-2026-001 total 1200 EUR date 2026-04-15") -> dict:
    init_db()
    payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "field_test.pdf")
    payload["ocr_text"] = ocr_text
    payload["ocr_confidence"] = 0.9
    payload["classification"] = {"label": "invoice", "confidence": 0.92}
    payload["extracted_entities"] = []
    payload["resolved_entities"] = []
    payload["entity_extraction_confidence"] = 0.85
    payload["entity_resolution_confidence"] = 0.80
    return payload


# ---------------------------------------------------------------------------
# _parse_json_array
# ---------------------------------------------------------------------------

class TestParseJsonArray:
    def test_valid_array(self):
        result = field_extraction_logic._parse_json_array('["invoice_number", "date"]')
        assert result == ["invoice_number", "date"]

    def test_markdown_fenced(self):
        raw = '```\n["invoice_number", "date"]\n```'
        result = field_extraction_logic._parse_json_array(raw)
        assert result == ["invoice_number", "date"]

    def test_embedded_array(self):
        raw = 'Here are the fields: ["invoice_number", "date"] end'
        result = field_extraction_logic._parse_json_array(raw)
        assert result == ["invoice_number", "date"]

    def test_invalid_json_returns_empty(self):
        result = field_extraction_logic._parse_json_array("not json")
        assert result == []

    def test_empty_string_returns_empty(self):
        result = field_extraction_logic._parse_json_array("")
        assert result == []


# ---------------------------------------------------------------------------
# _parse_json_object
# ---------------------------------------------------------------------------

class TestParseJsonObject:
    def test_valid_object(self):
        result = field_extraction_logic._parse_json_object('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fenced(self):
        raw = '```json\n{"key": "value"}\n```'
        result = field_extraction_logic._parse_json_object(raw)
        assert result == {"key": "value"}

    def test_invalid_json_returns_empty(self):
        result = field_extraction_logic._parse_json_object("not json")
        assert result == {}


# ---------------------------------------------------------------------------
# _split_values_and_confidences
# ---------------------------------------------------------------------------

class TestSplitValuesAndConfidences:
    def test_new_format(self):
        parsed = {
            "values": {"invoice_number": "INV-001"},
            "confidences": {"invoice_number": 0.95},
        }
        vals, confs = field_extraction_logic._split_values_and_confidences(parsed)
        assert vals == {"invoice_number": "INV-001"}
        assert confs == {"invoice_number": pytest.approx(0.95)}

    def test_legacy_flat_format(self):
        parsed = {"invoice_number": "INV-001", "date": "2026-04-15"}
        vals, confs = field_extraction_logic._split_values_and_confidences(parsed)
        assert vals == parsed
        assert confs == {}

    def test_empty_dict(self):
        vals, confs = field_extraction_logic._split_values_and_confidences({})
        assert vals == {}
        assert confs == {}

    def test_confidence_clamped(self):
        parsed = {
            "values": {"field": "val"},
            "confidences": {"field": 1.5},  # Should be clamped to 1.0
        }
        _, confs = field_extraction_logic._split_values_and_confidences(parsed)
        assert confs["field"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# process_field_extraction
# ---------------------------------------------------------------------------

class TestProcessFieldExtraction:
    def _make_llm_responses(self):
        return [
            MOCK_FIELD_DETECT_RESPONSE,
            MOCK_CANONICAL_MAP_EXISTING,  # invoice_number
            MOCK_CANONICAL_MAP_EXISTING,  # date
            MOCK_CANONICAL_MAP_NEW,        # total_amount
            MOCK_CANONICAL_MAP_NEW,        # tax_amount
            MOCK_CANONICAL_MAP_NEW,        # due_date
            MOCK_FIELD_EXTRACT_RESPONSE,
        ]

    @pytest.mark.asyncio
    async def test_empty_ocr_text_skipped(self):
        payload = _make_payload("")
        result = await field_extraction_logic.process_field_extraction(payload)
        assert result["extracted_fields"] == []
        assert "field_extraction_skipped" in result["history"]

    @pytest.mark.asyncio
    async def test_fields_saved_to_db(self, mock_llm_field_extraction):
        payload = _make_payload()
        doc_id = payload["workflow_id"]
        result = await field_extraction_logic.process_field_extraction(payload)

        with get_session() as session:
            fields = session.exec(
                select(DocumentField).where(DocumentField.document_id == doc_id)
            ).all()
        assert len(fields) > 0

    @pytest.mark.asyncio
    async def test_document_status_set_to_completed(self, mock_llm_field_extraction):
        payload = _make_payload()
        doc_id = payload["workflow_id"]
        await field_extraction_logic.process_field_extraction(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_pipeline_confidence_computed(self, mock_llm_field_extraction):
        payload = _make_payload()
        result = await field_extraction_logic.process_field_extraction(payload)
        assert "pipeline_confidence" in result
        assert result["pipeline_confidence"] is not None
        assert 0.0 <= result["pipeline_confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_pipeline_confidence_stored_in_db(self, mock_llm_field_extraction):
        payload = _make_payload()
        doc_id = payload["workflow_id"]
        await field_extraction_logic.process_field_extraction(payload)

        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.pipeline_confidence is not None

    @pytest.mark.asyncio
    async def test_adds_to_history(self, mock_llm_field_extraction):
        payload = _make_payload()
        result = await field_extraction_logic.process_field_extraction(payload)
        assert "field_extraction_completed" in result["history"]

    @pytest.mark.asyncio
    async def test_extracted_fields_have_required_keys(self, mock_llm_field_extraction):
        payload = _make_payload()
        result = await field_extraction_logic.process_field_extraction(payload)
        for field in result["extracted_fields"]:
            assert "field_name" in field
            assert "confidence" in field
            assert 0.0 <= field["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_no_llm_calls_when_no_fields_detected(self):
        """If LLM returns empty field list, no extraction call should be made."""
        payload = _make_payload("some text")

        with patch.object(
            field_extraction_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value="[]",
        ) as mock:
            result = await field_extraction_logic.process_field_extraction(payload)

        assert result["extracted_fields"] == []
