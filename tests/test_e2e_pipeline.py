"""
DMSAI – End-to-end pipeline test suite.

Tests every stage of the document processing pipeline in order:
  1. Ingestion
  2. Conversion (image -> PDF)
  3. Storage (write PDF to disk, update DB)
  4. OCR (Vision LLM)
  5. Classification (LLM-mocked)
  6. Entity extraction (LLM-mocked)
  7. Entity resolution (LLM-first: identifier match → token-overlap pre-filter → LLM)
  8. Field extraction (LLM-mocked) + pipeline confidence
  9. Multi-document entity resolution (same entity across docs, identifier path)
 10. Final DB state verification

All LLM calls are mocked with realistic deterministic responses.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from dmsai_models import (
    Document,
    DocumentField,
    DocumentEntity,
    Entity,
    EntityField,
    CanonicalField,
    CanonicalDocumentClass,
    get_session,
    init_db,
)

# Import pre-loaded modules from conftest
from conftest import (
    ingestion_logic,
    conversion_logic,
    storage_logic,
    ocr_logic,
    classification_logic,
    entity_extraction_logic,
    entity_resolution_logic,
    field_extraction_logic,
    MOCK_CLASSIFICATION_RESPONSE,
    MOCK_ENTITY_EXTRACTION_RESPONSE,
    MOCK_ENTITY_EXTRACTION_RESPONSE_2,
    MOCK_FIELD_DETECT_RESPONSE,
    MOCK_FIELD_EXTRACT_RESPONSE,
    MOCK_CANONICAL_MAP_EXISTING,
    MOCK_CANONICAL_MAP_NEW,
    MOCK_ENTITY_RESOLUTION_SAME,
    MOCK_ENTITY_RESOLUTION_DIFFERENT,
    make_llm_side_effect,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_doc(doc_id: str) -> Document | None:
    with get_session() as s:
        return s.get(Document, doc_id)


# ---------------------------------------------------------------------------
# Pipeline step runners
# ---------------------------------------------------------------------------

async def _run_up_to_ocr(doc_path: Path, doc_bytes: bytes) -> dict:
    payload = ingestion_logic.build_ingestion_payload(doc_bytes, doc_path.name, source="test")
    payload = await ingestion_logic.process_document(payload)
    payload = await conversion_logic.process_document(payload)
    payload = await storage_logic.process_document(payload)
    payload = await ocr_logic.process_document(payload)
    return payload


async def _run_up_to_classification(doc_path: Path, doc_bytes: bytes) -> dict:
    payload = await _run_up_to_ocr(doc_path, doc_bytes)
    payload = await classification_logic.process_classification(payload)
    return payload


async def _run_up_to_entity_extraction(doc_path: Path, doc_bytes: bytes) -> dict:
    payload = await _run_up_to_classification(doc_path, doc_bytes)
    payload = await entity_extraction_logic.process_entity_extraction(payload)
    return payload


async def _run_full_pipeline(doc_path: Path, doc_bytes: bytes) -> dict:
    payload = await _run_up_to_entity_extraction(doc_path, doc_bytes)
    payload = await entity_resolution_logic.process_entity_resolution(payload)
    payload = await field_extraction_logic.process_field_extraction(payload)
    return payload


# ---------------------------------------------------------------------------
# 1. Ingestion
# ---------------------------------------------------------------------------

class TestIngestion:

    def test_build_payload_creates_document_in_db(self, first_doc: Path, first_doc_bytes: bytes):
        payload = ingestion_logic.build_ingestion_payload(
            first_doc_bytes, first_doc.name, source="test",
        )
        assert payload["workflow_id"]
        assert payload["filename"] == first_doc.name
        assert payload["file_bytes"]

        doc = _get_doc(payload["workflow_id"])
        assert doc is not None
        assert doc.status == "INGESTED"
        assert doc.filename == first_doc.name

    @pytest.mark.asyncio
    async def test_process_document_adds_history(self, first_doc: Path, first_doc_bytes: bytes):
        payload = ingestion_logic.build_ingestion_payload(
            first_doc_bytes, first_doc.name, source="test",
        )
        result = await ingestion_logic.process_document(payload)
        assert "ingestion_completed" in result["history"]

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            ingestion_logic.build_ingestion_payload(b"data", "test.docx", source="test")


# ---------------------------------------------------------------------------
# 2. Conversion
# ---------------------------------------------------------------------------

class TestConversion:

    @pytest.mark.asyncio
    async def test_jpg_to_pdf(self, first_doc: Path, first_doc_bytes: bytes):
        payload = ingestion_logic.build_ingestion_payload(
            first_doc_bytes, first_doc.name, source="test",
        )
        payload = await ingestion_logic.process_document(payload)
        payload = await conversion_logic.process_document(payload)

        assert payload["unified_extension"] == ".pdf"
        assert "conversion_completed" in payload["history"]

        pdf_bytes = base64.b64decode(payload["file_bytes"])
        assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 3. Storage
# ---------------------------------------------------------------------------

class TestStorage:

    @pytest.mark.asyncio
    async def test_storage_writes_file_and_updates_db(self, first_doc: Path, first_doc_bytes: bytes):
        payload = ingestion_logic.build_ingestion_payload(
            first_doc_bytes, first_doc.name, source="test",
        )
        payload = await ingestion_logic.process_document(payload)
        payload = await conversion_logic.process_document(payload)
        payload = await storage_logic.process_document(payload)

        assert "storage_completed" in payload["history"]
        assert "storage_path" in payload
        assert os.path.isfile(payload["storage_path"])
        assert "file_bytes" not in payload

        doc = _get_doc(payload["workflow_id"])
        assert doc is not None
        assert doc.status == "STORED"
        assert doc.storage_path == payload["storage_path"]


# ---------------------------------------------------------------------------
# 4. OCR
# ---------------------------------------------------------------------------

class TestOCR:

    @pytest.mark.asyncio
    async def test_ocr_extracts_text(self, first_doc: Path, first_doc_bytes: bytes):
        payload = await _run_up_to_ocr(first_doc, first_doc_bytes)

        assert "ocr_completed" in payload["history"]
        assert payload["ocr_text"]
        assert len(payload["ocr_text"]) > 10
        assert 0.0 <= payload["ocr_confidence"] <= 1.0
        assert payload["ocr_method"] == "vllm"

        doc = _get_doc(payload["workflow_id"])
        assert doc is not None
        assert doc.status == "OCR_DONE"
        assert doc.ocr_text == payload["ocr_text"]
        assert doc.ocr_confidence == payload["ocr_confidence"]


# ---------------------------------------------------------------------------
# 5. Classification (LLM mocked)
# ---------------------------------------------------------------------------

class TestClassification:

    @pytest.mark.asyncio
    async def test_classification_with_canonical_llm(
        self, first_doc: Path, first_doc_bytes: bytes, mock_llm_classification,
    ):
        payload = await _run_up_to_ocr(first_doc, first_doc_bytes)
        payload = await classification_logic.process_classification(payload)

        assert "classification_completed" in payload["history"]
        cls = payload["classification"]
        assert cls["label"] == "invoice"
        assert 0.0 <= cls["confidence"] <= 1.0
        assert cls["confidence_details"]["level"] in {"high", "medium", "low"}
        assert cls["method"] == "llm_canonical"

        doc = _get_doc(payload["workflow_id"])
        assert doc is not None
        assert doc.status == "CLASSIFIED"
        assert doc.classification_label == "invoice"
        assert doc.classification_subcategory_label is None

    @pytest.mark.asyncio
    async def test_classification_creates_canonical_subcategory(
        self, first_doc: Path, first_doc_bytes: bytes,
    ):
        payload = await _run_up_to_ocr(first_doc, first_doc_bytes)
        classification_response = json.dumps({
            "category": "invoice",
            "subcategory": "utility_bill",
            "confidence": 0.9,
            "is_new": False,
            "definition": "Commercial invoice",
            "subcategory_is_new": True,
            "subcategory_definition": "Invoice for utilities such as electricity or water",
            "reason": "The document is an invoice for utility services",
        })

        with patch.object(
            classification_logic,
            "_call_llm",
            new_callable=AsyncMock,
            side_effect=make_llm_side_effect([classification_response]),
        ):
            payload = await classification_logic.process_classification(payload)

        assert payload["classification"]["label"] == "invoice"
        assert payload["classification"]["subcategory_label"] == "utility_bill"
        assert payload["classification"]["path"] == ["invoice", "utility_bill"]

        doc = _get_doc(payload["workflow_id"])
        assert doc is not None
        assert doc.classification_label == "invoice"
        assert doc.classification_subcategory_label == "utility_bill"
        assert json.loads(doc.classification_path) == ["invoice", "utility_bill"]


# ---------------------------------------------------------------------------
# 7. Entity Extraction (LLM mocked)
# ---------------------------------------------------------------------------

class TestEntityExtraction:

    @pytest.mark.asyncio
    async def test_entity_extraction_parses_entities(
        self, first_doc: Path, first_doc_bytes: bytes,
        mock_llm_classification, mock_llm_entity_extraction,
    ):
        payload = await _run_up_to_classification(first_doc, first_doc_bytes)
        payload = await entity_extraction_logic.process_entity_extraction(payload)

        assert "entity_extraction_completed" in payload["history"]
        entities = payload["extracted_entities"]
        assert len(entities) == 2
        assert entities[0]["name"] == "ACME Corporation"
        assert entities[0]["entity_type"] == "company"
        assert entities[0]["role"] == "issuer"
        assert 0.0 <= entities[0]["confidence"] <= 1.0
        assert payload["entity_extraction_confidence"] is not None

        doc = _get_doc(payload["workflow_id"])
        assert doc.status == "ENTITIES_EXTRACTED"


# ---------------------------------------------------------------------------
# 8. Entity Resolution
# ---------------------------------------------------------------------------

class TestEntityResolution:

    @pytest.mark.asyncio
    async def test_new_entities_created(
        self, first_doc: Path, first_doc_bytes: bytes,
        mock_llm_classification, mock_llm_entity_extraction,
        mock_llm_entity_resolution,
    ):
        """Entities are resolved (new or reused) and recorded in the DB.

        The resolution LLM is mocked to say 'different' so each run creates fresh
        entities deterministically without relying on DB state from previous tests.
        """
        payload = await _run_up_to_entity_extraction(first_doc, first_doc_bytes)
        payload = await entity_resolution_logic.process_entity_resolution(payload)

        assert "entity_resolution_completed" in payload["history"]
        resolved = payload["resolved_entities"]
        assert len(resolved) == 2
        assert all("entity_id" in r for r in resolved)

        doc = _get_doc(payload["workflow_id"])
        assert doc.status == "ENTITIES_RESOLVED"

        with get_session() as s:
            links = s.exec(
                select(DocumentEntity).where(
                    DocumentEntity.document_id == payload["workflow_id"]
                )
            ).all()
        assert len(links) == 2

    @pytest.mark.asyncio
    async def test_identifier_match_on_second_doc(self, example_docs):
        """Second doc with same tax_id → entity matched by identifier (conf=1.0).

        The identifier path bypasses the LLM entirely, so no resolution mock needed.
        """
        if len(example_docs) < 2:
            pytest.skip("Need at least 2 example docs")

        doc1 = example_docs[0]
        doc1_bytes = doc1.read_bytes()
        doc2 = example_docs[1]
        doc2_bytes = doc2.read_bytes()

        with patch.object(
            classification_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value=MOCK_CLASSIFICATION_RESPONSE,
        ), patch.object(
            entity_extraction_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value=MOCK_ENTITY_EXTRACTION_RESPONSE,
        ), patch.object(
            entity_resolution_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value=MOCK_ENTITY_RESOLUTION_DIFFERENT,
        ):
            p1 = await _run_up_to_entity_extraction(doc1, doc1_bytes)
            await entity_resolution_logic.process_entity_resolution(p1)

        with patch.object(
            classification_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value=MOCK_CLASSIFICATION_RESPONSE,
        ), patch.object(
            entity_extraction_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value=MOCK_ENTITY_EXTRACTION_RESPONSE_2,
        ):
            # MOCK_ENTITY_EXTRACTION_RESPONSE_2 contains the same tax_id as doc1,
            # so the identifier match fires and the LLM is never called for ACME.
            p2 = await _run_up_to_entity_extraction(doc2, doc2_bytes)
            p2 = await entity_resolution_logic.process_entity_resolution(p2)

        resolved = p2["resolved_entities"]
        acme_match = next((r for r in resolved if "ACME" in r["name"]), None)
        assert acme_match is not None
        assert not acme_match["is_new"], "ACME should be matched via tax_id"
        assert acme_match["match_confidence"] == 1.0


# ---------------------------------------------------------------------------
# 9. Field Extraction + Pipeline Confidence
# ---------------------------------------------------------------------------

class TestFieldExtraction:

    @pytest.mark.asyncio
    async def test_field_extraction_and_pipeline_confidence(
        self, first_doc: Path, first_doc_bytes: bytes,
        mock_llm_classification, mock_llm_entity_extraction,
        mock_llm_entity_resolution,
        mock_llm_field_extraction,
    ):
        payload = await _run_up_to_entity_extraction(first_doc, first_doc_bytes)
        payload = await entity_resolution_logic.process_entity_resolution(payload)
        payload = await field_extraction_logic.process_field_extraction(payload)

        assert "field_extraction_completed" in payload["history"]
        fields = payload["extracted_fields"]
        assert len(fields) > 0

        assert payload["pipeline_confidence"] is not None
        assert 0.0 <= payload["pipeline_confidence"] <= 1.0

        details = payload["confidence_details"]
        assert "ocr" in details
        assert "classification" in details
        assert "entity_extraction" in details
        assert "entity_resolution" in details
        assert "field_extraction" in details

        doc = _get_doc(payload["workflow_id"])
        assert doc.status == "COMPLETED"
        assert doc.pipeline_confidence is not None
        assert doc.confidence_details is not None

        conf_details = json.loads(doc.confidence_details)
        assert conf_details["ocr"]["score"] is not None
        assert conf_details["field_extraction"]["count"] == len(fields)

        with get_session() as s:
            db_fields = s.exec(
                select(DocumentField).where(
                    DocumentField.document_id == payload["workflow_id"]
                )
            ).all()
        assert len(db_fields) == len(fields)
        for df in db_fields:
            assert 0.0 <= df.confidence <= 1.0


# ---------------------------------------------------------------------------
# 10. Full pipeline – multiple documents
# ---------------------------------------------------------------------------

class TestFullPipelineMultiDoc:

    @pytest.mark.asyncio
    async def test_process_multiple_documents(self, example_docs):
        """Process up to 3 example docs through the full pipeline."""
        docs_to_process = example_docs[:3]
        doc_ids: list[str] = []

        for i, doc_path in enumerate(docs_to_process):
            doc_bytes = doc_path.read_bytes()

            entity_response = (
                MOCK_ENTITY_EXTRACTION_RESPONSE if i == 0
                else MOCK_ENTITY_EXTRACTION_RESPONSE_2
            )

            field_responses = [
                MOCK_FIELD_DETECT_RESPONSE,
                MOCK_CANONICAL_MAP_EXISTING,
                MOCK_CANONICAL_MAP_EXISTING,
                MOCK_CANONICAL_MAP_NEW,
                MOCK_CANONICAL_MAP_NEW,
                MOCK_CANONICAL_MAP_NEW,
                MOCK_FIELD_EXTRACT_RESPONSE,
            ]

            with patch.object(
                classification_logic, "_call_llm",
                new_callable=AsyncMock,
                return_value=MOCK_CLASSIFICATION_RESPONSE,
            ), patch.object(
                entity_extraction_logic, "_call_llm",
                new_callable=AsyncMock,
                return_value=entity_response,
            ), patch.object(
                entity_resolution_logic, "_call_llm",
                new_callable=AsyncMock,
                return_value=MOCK_ENTITY_RESOLUTION_DIFFERENT,
            ), patch.object(
                field_extraction_logic, "_call_llm",
                new_callable=AsyncMock,
                side_effect=make_llm_side_effect(field_responses),
            ):
                payload = await _run_full_pipeline(doc_path, doc_bytes)

            doc_ids.append(payload["workflow_id"])
            assert payload["history"][-1] == "field_extraction_completed"

        with get_session() as s:
            for did in doc_ids:
                doc = s.get(Document, did)
                assert doc is not None
                assert doc.status == "COMPLETED"
                assert doc.pipeline_confidence is not None

            entities = s.exec(select(Entity)).all()
            assert len(entities) >= 2, "Should have at least ACME + one person"

            acme_entities = [e for e in entities if "ACME" in e.name.upper()]
            if len(docs_to_process) > 1:
                assert len(acme_entities) == 1, (
                    f"Expected 1 ACME entity (merged), got {len(acme_entities)}: "
                    f"{[e.name for e in acme_entities]}"
                )


# ---------------------------------------------------------------------------
# 11. DB integrity checks
# ---------------------------------------------------------------------------

class TestDBIntegrity:

    def test_canonical_fields_seeded(self):
        """Entity-scope canonical fields should be seeded by init_db."""
        init_db()
        with get_session() as s:
            entity_cfs = s.exec(
                select(CanonicalField).where(CanonicalField.scope == "entity")
            ).all()
        names = {cf.canonical_name for cf in entity_cfs}
        assert "tax_id" in names
        assert "email" in names
        assert "siret" in names

    def test_canonical_document_classes_seeded(self):
        """Document classes should have canonical labels for LLM classification."""
        init_db()
        with get_session() as s:
            classes = s.exec(select(CanonicalDocumentClass)).all()
        names = {c.canonical_name for c in classes}
        assert "invoice" in names
        assert "receipt" in names
        assert "other" in names

    def test_entity_fields_have_confidence(self):
        """All EntityField rows should have a valid confidence value."""
        with get_session() as s:
            efs = s.exec(select(EntityField)).all()
        if not efs:
            pytest.skip("No entity fields in DB yet")
        for ef in efs:
            assert 0.0 <= ef.confidence <= 1.0, f"EntityField {ef.id} confidence out of range"

    def test_document_entity_links_have_confidence(self):
        """All DocumentEntity rows should have a valid confidence value."""
        with get_session() as s:
            links = s.exec(select(DocumentEntity)).all()
        if not links:
            pytest.skip("No document-entity links in DB yet")
        for link in links:
            assert 0.0 <= link.confidence <= 1.0, f"DocumentEntity {link.id} confidence out of range"

    def test_no_orphaned_document_entity_rows(self):
        """All DocumentEntity.document_id values should have a matching Document."""
        with get_session() as s:
            links = s.exec(select(DocumentEntity)).all()
            doc_ids_in_db = {d.id for d in s.exec(select(Document)).all()}
        for link in links:
            assert link.document_id in doc_ids_in_db, (
                f"Orphaned DocumentEntity {link.id}: document_id {link.document_id} not in Document table"
            )

    def test_no_orphaned_entity_field_rows(self):
        """All EntityField.entity_id values should have a matching Entity."""
        with get_session() as s:
            efs = s.exec(select(EntityField)).all()
            entity_ids = {e.id for e in s.exec(select(Entity)).all()}
        for ef in efs:
            assert ef.entity_id in entity_ids, (
                f"Orphaned EntityField {ef.id}: entity_id {ef.entity_id} not in Entity table"
            )

    def test_completed_documents_have_pipeline_confidence(self):
        """Documents with status COMPLETED should all have a pipeline_confidence set."""
        with get_session() as s:
            completed = s.exec(
                select(Document).where(Document.status == "COMPLETED")
            ).all()
        if not completed:
            pytest.skip("No completed documents in DB yet")
        for doc in completed:
            assert doc.pipeline_confidence is not None, (
                f"Document {doc.id} is COMPLETED but has no pipeline_confidence"
            )
            assert 0.0 <= doc.pipeline_confidence <= 1.0


# ---------------------------------------------------------------------------
# 12. Pipeline recovery (partial failure scenarios)
# ---------------------------------------------------------------------------

class TestPipelineRecovery:

    @pytest.mark.asyncio
    async def test_entity_extraction_failure_leaves_document_in_ocr_done(self, first_doc: Path, first_doc_bytes: bytes):
        """If entity extraction raises, the Document should remain in its last known status."""
        payload = await _run_up_to_ocr(first_doc, first_doc_bytes)
        doc_id = payload["workflow_id"]

        # Simulate entity extraction LLM completely failing
        with patch.object(
            entity_extraction_logic, "_call_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM service unavailable"),
        ):
            try:
                await entity_extraction_logic.process_entity_extraction(payload)
            except RuntimeError:
                pass  # Expected failure

        doc = _get_doc(doc_id)
        # Document should be at OCR_DONE or ENTITIES_EXTRACTED — not COMPLETED
        assert doc.status in ("OCR_DONE", "ENTITIES_EXTRACTED", "INGESTED", "STORED")
        assert doc.status != "COMPLETED"

    @pytest.mark.asyncio
    async def test_classification_empty_ocr_text_does_not_crash(self, first_doc: Path, first_doc_bytes: bytes):
        """Empty OCR text should be handled gracefully by classification."""
        payload = ingestion_logic.build_ingestion_payload(
            first_doc_bytes, first_doc.name, source="test"
        )
        payload = await ingestion_logic.process_document(payload)
        payload = await conversion_logic.process_document(payload)
        payload = await storage_logic.process_document(payload)
        payload["ocr_text"] = ""  # Simulate empty OCR
        payload["ocr_confidence"] = 0.0

        with patch.object(
            classification_logic, "_call_llm",
            new_callable=AsyncMock,
            return_value=MOCK_CLASSIFICATION_RESPONSE,
        ):
            result = await classification_logic.process_classification(payload)

        assert isinstance(result, dict)
        assert "history" in result

    @pytest.mark.asyncio
    async def test_field_extraction_skipped_without_ocr_text(self, first_doc: Path, first_doc_bytes: bytes):
        """Field extraction should gracefully skip when ocr_text is missing."""
        payload = ingestion_logic.build_ingestion_payload(
            first_doc_bytes, first_doc.name, source="test"
        )
        payload["ocr_text"] = ""

        with patch.object(
            field_extraction_logic, "_trigger_bucket_assignment",
            new_callable=AsyncMock,
        ):
            result = await field_extraction_logic.process_field_extraction(payload)

        assert result["extracted_fields"] == []
        assert "field_extraction_skipped" in result["history"]


# ---------------------------------------------------------------------------
# 13. Multi-file-type parametrised E2E
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def multi_doc_params(example_docs: list):
    """Return up to 3 example docs (different file types if available)."""
    # Select up to one PDF and one JPEG to cover image + PDF paths
    pdfs = [d for d in example_docs if d.suffix.lower() == ".pdf"]
    images = [d for d in example_docs if d.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    selected = []
    if pdfs:
        selected.append(pdfs[0])
    if images:
        selected.append(images[0])
    if not selected:
        selected = example_docs[:2]
    return selected


class TestMultiFileTypeE2E:

    @pytest.mark.asyncio
    async def test_pdf_and_image_both_convert_to_pdf(self, multi_doc_params: list):
        """Both PDF and image inputs should produce a valid PDF payload after conversion."""
        for doc_path in multi_doc_params:
            doc_bytes = doc_path.read_bytes()
            payload = ingestion_logic.build_ingestion_payload(doc_bytes, doc_path.name)
            payload = await ingestion_logic.process_document(payload)
            payload = await conversion_logic.process_document(payload)

            pdf_bytes = base64.b64decode(payload["file_bytes"])
            assert pdf_bytes[:4] == b"%PDF", (
                f"{doc_path.name} ({doc_path.suffix}) should produce PDF after conversion"
            )
            assert payload["unified_extension"] == ".pdf"

    @pytest.mark.asyncio
    async def test_all_file_types_reach_stored_status(self, multi_doc_params: list):
        """All file types should reach STORED status after storage node."""
        for doc_path in multi_doc_params:
            doc_bytes = doc_path.read_bytes()
            payload = ingestion_logic.build_ingestion_payload(doc_bytes, doc_path.name)
            payload = await ingestion_logic.process_document(payload)
            payload = await conversion_logic.process_document(payload)
            payload = await storage_logic.process_document(payload)

            doc = _get_doc(payload["workflow_id"])
            assert doc.status == "STORED", (
                f"{doc_path.name}: expected STORED, got {doc.status}"
            )
            assert os.path.isfile(payload["storage_path"])
