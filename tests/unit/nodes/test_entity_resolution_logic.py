"""Unit tests for nodes/entity_resolution_node/src/entity_resolution_logic.py.

Architecture under test (LLM-first):
  1. Hard identifier match  → conf = 1.0, no LLM called
  2. Token-overlap pre-filter → top-K candidates
  3. LLM open question per candidate → {"same", "confidence", "reasoning", "canonical_name"}
  4. Best LLM match above merge_threshold wins; else new entity created
"""

from __future__ import annotations

import json
import sys
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from dmsai_models import (
    Document, Entity, EntityField, DocumentEntity, get_session, init_db,
)
from fixtures.mock_responses import MOCK_ENTITY_EXTRACTION_RESPONSE

entity_resolution_logic = sys.modules["entity_resolution_logic"]
ingestion_logic = sys.modules["ingestion_logic"]

# ---------------------------------------------------------------------------
# LLM mock responses
# ---------------------------------------------------------------------------

LLM_SAME = json.dumps({
    "same": True,
    "confidence": 0.92,
    "reasoning": "Same company name with only a legal suffix difference.",
    "canonical_name": "ACME Corporation",
})
LLM_DIFFERENT = json.dumps({
    "same": False,
    "confidence": 0.88,
    "reasoning": "Similar names but conflicting tax IDs indicate distinct entities.",
    "canonical_name": "",
})
LLM_LOW_CONF_SAME = json.dumps({
    "same": True,
    "confidence": 0.50,   # Below default 0.75 threshold → should NOT merge
    "reasoning": "Maybe the same, but I'm not sure.",
    "canonical_name": "ACME",
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload_with_entities(entities: list) -> dict:
    init_db()
    payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "resolution_test.pdf")
    payload["ocr_text"] = "Invoice from ACME Corporation to John Doe"
    payload["ocr_confidence"] = 0.9
    payload["extracted_entities"] = entities
    return payload


def _sample_entities():
    return json.loads(MOCK_ENTITY_EXTRACTION_RESPONSE)


def _existing_entity(name: str = "Existing Corp", etype: str = "company") -> tuple[str, Entity]:
    eid = str(uuid.uuid4())
    e = Entity(id=eid, entity_type=etype, name=name, canonical_name=name)
    return eid, e


def _tax_id_field(entity_id: str, value: str) -> EntityField:
    return EntityField(
        id=str(uuid.uuid4()),
        entity_id=entity_id,
        field_name="tax_id",
        field_value=value,
    )


# ---------------------------------------------------------------------------
# Text-normalisation helpers (still present, still useful for pre-filtering)
# ---------------------------------------------------------------------------

class TestNormaliseHelpers:
    def test_normalize_strips_accents(self):
        assert entity_resolution_logic._normalize("Élisée Réclus") == "elisee reclus"

    def test_normalize_lowercases(self):
        assert entity_resolution_logic._normalize("ACME CORP") == "acme corp"

    def test_strip_legal_suffix_removes_sas(self):
        result = entity_resolution_logic._strip_legal_suffix("ACME SAS")
        assert "sas" not in result.lower()

    def test_strip_legal_suffix_removes_sarl(self):
        result = entity_resolution_logic._strip_legal_suffix("ACME SARL")
        assert "sarl" not in result.lower()

    def test_token_overlap_identical(self):
        score = entity_resolution_logic._token_overlap("ACME Corp", "ACME Corp")
        assert score == pytest.approx(1.0)

    def test_token_overlap_no_common_tokens(self):
        score = entity_resolution_logic._token_overlap("Alpha Bravo", "Delta Echo")
        assert score == pytest.approx(0.0)

    def test_token_overlap_partial(self):
        score = entity_resolution_logic._token_overlap("ACME Corporation", "ACME Ltd")
        # "acme" is shared, so overlap > 0
        assert 0.0 < score < 1.0

    def test_token_overlap_ignores_legal_suffix(self):
        # "acme" vs "acme" once suffixes stripped → should be 1.0
        score = entity_resolution_logic._token_overlap("ACME SAS", "ACME LLC")
        assert score == pytest.approx(1.0)

    def test_token_overlap_completely_different(self):
        score = entity_resolution_logic._token_overlap("Galactic Plumbing", "Delta Finance")
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Identifier matching
# ---------------------------------------------------------------------------

class TestIdentifierMatching:
    def test_tax_id_exact_match(self):
        incoming = {"tax_id": "FR12345678901"}
        existing = [EntityField(
            id=str(uuid.uuid4()), entity_id="x",
            field_name="tax_id", field_value="FR12345678901",
        )]
        assert entity_resolution_logic._identifiers_match(incoming, existing) is True

    def test_tax_id_normalised_match(self):
        """tax_id with spaces and dashes should match the normalised version."""
        incoming = {"tax_id": "FR 1234-5678-901"}
        existing = [EntityField(
            id=str(uuid.uuid4()), entity_id="x",
            field_name="tax_id", field_value="FR12345678901",
        )]
        assert entity_resolution_logic._identifiers_match(incoming, existing) is True

    def test_tax_id_no_match(self):
        incoming = {"tax_id": "FR000"}
        existing = [EntityField(
            id=str(uuid.uuid4()), entity_id="x",
            field_name="tax_id", field_value="DE999",
        )]
        assert entity_resolution_logic._identifiers_match(incoming, existing) is False

    def test_no_identifier_keys(self):
        incoming = {"address": "123 Main St"}
        existing = [EntityField(
            id=str(uuid.uuid4()), entity_id="x",
            field_name="address", field_value="123 Main St",
        )]
        assert entity_resolution_logic._identifiers_match(incoming, existing) is False


# ---------------------------------------------------------------------------
# LLM comparison helper
# ---------------------------------------------------------------------------

class TestLLMCompare:
    @pytest.mark.asyncio
    async def test_llm_compare_same(self):
        eid, existing = _existing_entity("ACME Corp")
        incoming = {"name": "ACME Corporation", "entity_type": "company", "fields": {}}
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_SAME):
            result = await entity_resolution_logic._llm_compare(incoming, existing, [])
        assert result["same"] is True
        assert result["confidence"] == pytest.approx(0.92)
        assert "reasoning" in result
        assert result["canonical_name"] == "ACME Corporation"

    @pytest.mark.asyncio
    async def test_llm_compare_different(self):
        eid, existing = _existing_entity("Delta Finance")
        incoming = {"name": "ACME Corp", "entity_type": "company", "fields": {}}
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            result = await entity_resolution_logic._llm_compare(incoming, existing, [])
        assert result["same"] is False

    @pytest.mark.asyncio
    async def test_llm_compare_handles_malformed_json(self):
        eid, existing = _existing_entity()
        incoming = {"name": "Anything", "entity_type": "company", "fields": {}}
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value="not json at all"):
            result = await entity_resolution_logic._llm_compare(incoming, existing, [])
        assert result["same"] is False
        assert result["confidence"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_llm_compare_strips_markdown_fences(self):
        fenced = "```json\n" + LLM_SAME + "\n```"
        eid, existing = _existing_entity("ACME Corp")
        incoming = {"name": "ACME", "entity_type": "company", "fields": {}}
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=fenced):
            result = await entity_resolution_logic._llm_compare(incoming, existing, [])
        assert result["same"] is True


# ---------------------------------------------------------------------------
# _resolve_entity (full logic)
# ---------------------------------------------------------------------------

class TestResolveEntity:
    @pytest.mark.asyncio
    async def test_identifier_match_skips_llm(self):
        """Hard identifier match should return immediately without calling LLM."""
        unique_tax = f"ID-{uuid.uuid4().hex}"
        eid, existing = _existing_entity()
        ef = _tax_id_field(eid, unique_tax)
        entity_fields_map = {eid: [ef]}
        incoming = {"name": "Whatever Corp", "entity_type": "company",
                    "fields": {"tax_id": unique_tax}}
        called = []

        async def _no_llm(*a, **kw):
            called.append(True)
            return LLM_SAME

        with patch.object(entity_resolution_logic, "_call_llm", side_effect=_no_llm):
            matched, conf, canon = await entity_resolution_logic._resolve_entity(
                incoming, [existing], entity_fields_map,
            )

        assert matched is existing
        assert conf == pytest.approx(1.0)
        assert called == [], "LLM should not be called when identifier matches"

    @pytest.mark.asyncio
    async def test_llm_match_above_threshold_merges(self):
        """LLM returning same=True with conf >= 0.75 should merge."""
        eid, existing = _existing_entity("ACME Corp")
        entity_fields_map = {eid: []}
        incoming = {"name": "ACME Corporation", "entity_type": "company", "fields": {}}

        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_SAME):
            matched, conf, canon = await entity_resolution_logic._resolve_entity(
                incoming, [existing], entity_fields_map,
            )

        assert matched is existing
        assert conf == pytest.approx(0.92)
        assert canon == "ACME Corporation"

    @pytest.mark.asyncio
    async def test_llm_match_below_threshold_creates_new(self):
        """LLM returning same=True but conf < threshold should NOT merge."""
        eid, existing = _existing_entity("ACME Corp")
        entity_fields_map = {eid: []}
        incoming = {"name": "ACME Corporation", "entity_type": "company", "fields": {}}

        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_LOW_CONF_SAME):
            matched, conf, canon = await entity_resolution_logic._resolve_entity(
                incoming, [existing], entity_fields_map,
            )

        assert matched is None, "Low confidence should not trigger merge"

    @pytest.mark.asyncio
    async def test_llm_different_creates_new(self):
        """LLM returning same=False should not merge."""
        eid, existing = _existing_entity("Delta Finance")
        entity_fields_map = {eid: []}
        incoming = {"name": "ACME Corp", "entity_type": "company", "fields": {}}

        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            matched, conf, canon = await entity_resolution_logic._resolve_entity(
                incoming, [existing], entity_fields_map,
            )

        assert matched is None

    @pytest.mark.asyncio
    async def test_no_overlap_skips_llm(self):
        """Candidates with token overlap < min_overlap should not trigger LLM."""
        eid, existing = _existing_entity("Completely Unrelated XYZ")
        entity_fields_map = {eid: []}
        incoming = {"name": "Alpha Beta Gamma Delta", "entity_type": "company", "fields": {}}
        called = []

        async def _track(*a, **kw):
            called.append(True)
            return LLM_SAME

        with patch.object(entity_resolution_logic, "_call_llm", side_effect=_track):
            matched, conf, canon = await entity_resolution_logic._resolve_entity(
                incoming, [existing], entity_fields_map,
            )

        assert matched is None
        assert called == [], "LLM should not be called when overlap is below min_overlap"

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_none(self):
        incoming = {"name": "Nobody Corp", "entity_type": "company", "fields": {}}
        matched, conf, canon = await entity_resolution_logic._resolve_entity(
            incoming, [], {},
        )
        assert matched is None
        assert conf == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# process_entity_resolution (integration)
# ---------------------------------------------------------------------------

class TestProcessEntityResolution:
    @pytest.mark.asyncio
    async def test_no_entities_skipped(self):
        payload = _make_payload_with_entities([])
        result = await entity_resolution_logic.process_entity_resolution(payload)
        assert result["resolved_entities"] == []
        assert "entity_resolution_skipped" in result["history"]

    @pytest.mark.asyncio
    async def test_new_entity_created_in_db(self):
        entities = _sample_entities()
        payload = _make_payload_with_entities(entities)
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            result = await entity_resolution_logic.process_entity_resolution(payload)

        resolved = result["resolved_entities"]
        assert len(resolved) > 0
        with get_session() as session:
            for r in resolved:
                assert session.get(Entity, r["entity_id"]) is not None

    @pytest.mark.asyncio
    async def test_document_entity_links_created(self):
        entities = _sample_entities()
        payload = _make_payload_with_entities(entities)
        doc_id = payload["workflow_id"]
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            await entity_resolution_logic.process_entity_resolution(payload)

        with get_session() as session:
            links = session.exec(
                select(DocumentEntity).where(DocumentEntity.document_id == doc_id)
            ).all()
        assert len(links) > 0

    @pytest.mark.asyncio
    async def test_document_status_set_to_entities_resolved(self):
        entities = _sample_entities()
        payload = _make_payload_with_entities(entities)
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            result = await entity_resolution_logic.process_entity_resolution(payload)
        with get_session() as session:
            doc = session.get(Document, result["workflow_id"])
        assert doc.status == "ENTITIES_RESOLVED"

    @pytest.mark.asyncio
    async def test_adds_to_history(self):
        entities = _sample_entities()
        payload = _make_payload_with_entities(entities)
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            result = await entity_resolution_logic.process_entity_resolution(payload)
        assert "entity_resolution_completed" in result["history"]

    @pytest.mark.asyncio
    async def test_resolution_confidence_computed(self):
        entities = _sample_entities()
        payload = _make_payload_with_entities(entities)
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_DIFFERENT):
            result = await entity_resolution_logic.process_entity_resolution(payload)
        assert result["entity_resolution_confidence"] is not None
        assert 0.0 <= result["entity_resolution_confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_identifier_match_reuses_existing_entity(self):
        """Exact identifier match (tax_id) should reuse existing entity without LLM."""
        unique_tax_id = f"UNIQUE-{uuid.uuid4().hex}"
        init_db()
        existing_id = str(uuid.uuid4())
        with get_session() as session:
            entity = Entity(
                id=existing_id, entity_type="company",
                name=f"UniqueCo {existing_id[:8]}",
                canonical_name=f"UniqueCo {existing_id[:8]}",
            )
            session.add(entity)
            session.add(EntityField(
                id=str(uuid.uuid4()), entity_id=existing_id,
                field_name="tax_id", field_value=unique_tax_id,
            ))
            session.commit()

        entities = [{
            "name": f"UniqueCo {existing_id[:8]}",
            "entity_type": "company",
            "role": "issuer",
            "confidence": 0.9,
            "fields": {"tax_id": unique_tax_id},
            "evidence": "UniqueCo",
        }]
        payload = _make_payload_with_entities(entities)
        called = []

        async def _no_llm(*a, **kw):
            called.append(True)
            return LLM_DIFFERENT

        with patch.object(entity_resolution_logic, "_call_llm", side_effect=_no_llm):
            result = await entity_resolution_logic.process_entity_resolution(payload)

        resolved = result["resolved_entities"]
        assert len(resolved) == 1
        assert resolved[0]["entity_id"] == existing_id
        assert resolved[0]["is_new"] is False
        assert called == [], "LLM should not be called for identifier match"

    @pytest.mark.asyncio
    async def test_llm_merge_reuses_existing_entity(self):
        """LLM saying same=True at high confidence should reuse existing entity."""
        # Use a unique suffix so we don't collide with entities from other tests
        unique_suffix = uuid.uuid4().hex[:8]
        unique_name = f"Uniqueco {unique_suffix}"
        incoming_name = f"Uniqueco {unique_suffix} Inc"

        init_db()
        existing_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(Entity(
                id=existing_id, entity_type="company",
                name=unique_name, canonical_name=unique_name,
            ))
            session.commit()

        entities = [{
            "name": incoming_name,
            "entity_type": "company",
            "role": "issuer",
            "confidence": 0.9,
            "fields": {},
            "evidence": incoming_name,
        }]
        payload = _make_payload_with_entities(entities)
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_SAME):
            result = await entity_resolution_logic.process_entity_resolution(payload)

        resolved = result["resolved_entities"]
        assert len(resolved) == 1
        assert resolved[0]["entity_id"] == existing_id
        assert resolved[0]["is_new"] is False
        assert resolved[0]["match_confidence"] == pytest.approx(0.92)

    @pytest.mark.asyncio
    async def test_llm_low_conf_creates_new_entity(self):
        """LLM saying same=True but confidence < threshold should create a new entity."""
        unique_suffix = uuid.uuid4().hex[:8]
        unique_name = f"Lowconfco {unique_suffix}"
        incoming_name = f"Lowconfco {unique_suffix} Inc"

        init_db()
        existing_id = str(uuid.uuid4())
        with get_session() as session:
            session.add(Entity(
                id=existing_id, entity_type="company",
                name=unique_name, canonical_name=unique_name,
            ))
            session.commit()

        entities = [{
            "name": incoming_name,
            "entity_type": "company",
            "role": "issuer",
            "confidence": 0.9,
            "fields": {},
        }]
        payload = _make_payload_with_entities(entities)
        with patch.object(entity_resolution_logic, "_call_llm", new_callable=AsyncMock,
                          return_value=LLM_LOW_CONF_SAME):
            result = await entity_resolution_logic.process_entity_resolution(payload)

        resolved = result["resolved_entities"]
        assert len(resolved) == 1
        assert resolved[0]["is_new"] is True, "Low LLM confidence should create new entity"
