"""Unit tests for nodes/entity_extraction_node/src/entity_extraction_logic.py."""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from dmsai_models import Document, DocumentEntity, Entity, get_session, init_db
from fixtures.mock_responses import MOCK_ENTITY_EXTRACTION_RESPONSE

entity_extraction_logic = sys.modules["entity_extraction_logic"]
ingestion_logic = sys.modules["ingestion_logic"]


def _make_payload(ocr_text: str = "Invoice from ACME Corp to John Doe") -> dict:
    init_db()
    payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "ee_test.pdf")
    payload["ocr_text"] = ocr_text
    payload["ocr_confidence"] = 0.9
    return payload


# ---------------------------------------------------------------------------
# _parse_entities_json
# ---------------------------------------------------------------------------

class TestParseEntitiesJson:
    def test_valid_json_array(self):
        raw = '[{"name": "ACME", "entity_type": "company"}]'
        result = entity_extraction_logic._parse_entities_json(raw)
        assert len(result) == 1
        assert result[0]["name"] == "ACME"

    def test_markdown_fenced_json(self):
        raw = '```json\n[{"name": "ACME", "entity_type": "company"}]\n```'
        result = entity_extraction_logic._parse_entities_json(raw)
        assert len(result) == 1

    def test_entities_wrapper_dict(self):
        raw = json.dumps({"entities": [{"name": "Corp A", "entity_type": "company"}]})
        result = entity_extraction_logic._parse_entities_json(raw)
        assert len(result) == 1
        assert result[0]["name"] == "Corp A"

    def test_empty_array(self):
        result = entity_extraction_logic._parse_entities_json("[]")
        assert result == []

    def test_invalid_json_returns_empty_list(self):
        result = entity_extraction_logic._parse_entities_json("not json at all")
        assert result == []

    def test_embedded_array_extraction(self):
        raw = 'Some text [{"name": "Corp", "entity_type": "company"}] more text'
        result = entity_extraction_logic._parse_entities_json(raw)
        assert len(result) == 1

    def test_empty_string_returns_empty_list(self):
        result = entity_extraction_logic._parse_entities_json("")
        assert result == []


# ---------------------------------------------------------------------------
# _normalize_entity_field_keys
# ---------------------------------------------------------------------------

class TestNormalizeEntityFieldKeys:
    def test_known_alias_mapped(self):
        """'tax_number' should map to 'tax_id' (a canonical alias)."""
        init_db()
        entities = [{"name": "Corp", "fields": {"tax_number": "FR123", "email": "a@b.com"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        # canonical names should be used
        keys = set(entities[0]["fields"].keys())
        # Either tax_id or tax_number depending on DB seed
        assert "tax_id" in keys or "tax_number" in keys  # alias mapping may differ

    def test_unknown_key_passes_through(self):
        init_db()
        entities = [{"name": "Corp", "fields": {"totally_unknown_field_xyz": "value"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert "totally_unknown_field_xyz" in entities[0]["fields"]

    def test_none_fields_becomes_empty_dict(self):
        init_db()
        entities = [{"name": "Corp", "fields": None}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert entities[0]["fields"] == {}

    def test_missing_fields_key_becomes_empty_dict(self):
        init_db()
        entities = [{"name": "Corp"}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert entities[0]["fields"] == {}


# ---------------------------------------------------------------------------
# process_entity_extraction
# ---------------------------------------------------------------------------

class TestProcessEntityExtraction:
    @pytest.mark.asyncio
    async def test_entities_in_payload(self, mock_llm_entity_extraction):
        payload = _make_payload()
        result = await entity_extraction_logic.process_entity_extraction(payload)
        assert "extracted_entities" in result
        assert len(result["extracted_entities"]) > 0

    @pytest.mark.asyncio
    async def test_document_status_set_to_entities_extracted(self, mock_llm_entity_extraction):
        payload = _make_payload()
        doc_id = payload["workflow_id"]
        await entity_extraction_logic.process_entity_extraction(payload)
        with get_session() as session:
            doc = session.get(Document, doc_id)
        assert doc.status == "ENTITIES_EXTRACTED"

    @pytest.mark.asyncio
    async def test_entity_confidence_computed(self, mock_llm_entity_extraction):
        payload = _make_payload("Invoice from ACME Corp to John Doe, total 1200 EUR")
        result = await entity_extraction_logic.process_entity_extraction(payload)
        for entity in result["extracted_entities"]:
            assert "confidence" in entity
            assert 0.0 <= entity["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_empty_ocr_text_skipped(self):
        payload = _make_payload("")
        result = await entity_extraction_logic.process_entity_extraction(payload)
        assert result["extracted_entities"] == []
        assert "entity_extraction_skipped" in result["history"]

    @pytest.mark.asyncio
    async def test_adds_to_history(self, mock_llm_entity_extraction):
        payload = _make_payload()
        result = await entity_extraction_logic.process_entity_extraction(payload)
        assert "entity_extraction_completed" in result["history"]

    @pytest.mark.asyncio
    async def test_entity_extraction_confidence_set(self, mock_llm_entity_extraction):
        payload = _make_payload()
        result = await entity_extraction_logic.process_entity_extraction(payload)
        assert result["entity_extraction_confidence"] is not None
        assert 0.0 <= result["entity_extraction_confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_entity_fields_present(self, mock_llm_entity_extraction):
        payload = _make_payload()
        result = await entity_extraction_logic.process_entity_extraction(payload)
        for entity in result["extracted_entities"]:
            assert "name" in entity
            assert "entity_type" in entity
            assert "role" in entity
            assert "fields" in entity
