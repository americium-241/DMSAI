from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlmodel import select

from dmsai_models import (
    Document, CanonicalField, SystemConfig, compute_item_confidence,
    get_session, init_db, record_pipeline_event,
)

logger = logging.getLogger("entity_extraction_node")

AUTO_PROMPT = """Analyze the following document text and identify ALL entities present.
Entities can be: people, companies, organizations, government agencies, etc.

For each entity, provide:
- "name": the full canonical name
- "entity_type": one of "person", "company", "organization", "government", "other"
- "role": the entity's role in the document (e.g. "issuer", "recipient", "mentioned", "service_provider", "client")
- "confidence": a number from 0.0 to 1.0 indicating how confident you are in this extraction (name, type, and fields combined)
- "evidence": a short exact quote from the document that supports the entity, or null
- "fields": a dictionary of identifying attributes you can find (address, phone, email, tax_id, registration_number, website, etc.)

Return ONLY a JSON array of entities. No explanation, no markdown fences. Example:
[
  {{"name": "ACME Corp", "entity_type": "company", "role": "issuer", "confidence": 0.92, "evidence": "ACME Corp ...", "fields": {{"address": "123 Main St", "tax_id": "FR12345678"}}}},
  {{"name": "John Doe", "entity_type": "person", "role": "recipient", "confidence": 0.88, "evidence": "John Doe", "fields": {{"email": "john@example.com"}}}}
]

Document text:
{ocr_text}"""


def _truncate_text(text: str, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


async def _call_llm(prompt: str) -> str:
    from dmsai_models.llm import call_llm
    return await call_llm(prompt)


def _config_value(key: str, default: str) -> str:
    try:
        init_db()
        with get_session() as session:
            row = session.get(SystemConfig, key)
            if row and row.value:
                return row.value
    except Exception as e:
        logger.warning("Failed to load config %s: %s", key, e)
    return default


def _parse_entities_json(raw: str) -> list[dict]:
    """Attempt to extract a JSON array from the LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "entities" in result:
            return result["entities"]
        return [result]
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
    logger.error(f"Failed to parse entity JSON from LLM response: {raw[:200]}")
    return []


def _normalize_entity_field_keys(entities: list[dict]) -> None:
    """Map entity fields dict keys to canonical names using CanonicalField (scope=entity)."""
    init_db()
    with get_session() as session:
        rows = session.exec(select(CanonicalField).where(CanonicalField.scope == "entity")).all()

    canonical_by_name = {cf.canonical_name.lower(): cf for cf in rows}
    alias_to_canonical: dict[str, str] = {}
    for cf in rows:
        try:
            for a in json.loads(cf.aliases):
                alias_to_canonical[a.lower()] = cf.canonical_name
        except (json.JSONDecodeError, TypeError):
            pass

    for ent in entities:
        fields = ent.get("fields")
        if not isinstance(fields, dict):
            ent["fields"] = {}
            continue
        new_fields: dict[str, object] = {}
        for k, v in fields.items():
            kl = k.lower().strip()
            if kl in canonical_by_name:
                new_fields[canonical_by_name[kl].canonical_name] = v
            elif kl in alias_to_canonical:
                new_fields[alias_to_canonical[kl]] = v
            else:
                new_fields[k] = v
        ent["fields"] = new_fields


async def process_entity_extraction(payload: dict) -> dict:
    """Extract entities from OCR text using LLM."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "entity_extraction", "started")
    ocr_text = payload.get("ocr_text", "")

    if not ocr_text:
        logger.warning(f"[{doc_id}] No OCR text, skipping entity extraction")
        payload["extracted_entities"] = []
        payload["entity_extraction_confidence"] = None
        payload["history"] = payload.get("history", []) + ["entity_extraction_skipped"]
        if doc_id:
            record_pipeline_event(doc_id, "entity_extraction", "completed", details="skipped_no_ocr")
        return payload

    truncated_text = _truncate_text(ocr_text)
    prompt = _config_value("entity_extraction_prompt", AUTO_PROMPT).format(ocr_text=truncated_text)
    ocr_confidence = payload.get("ocr_confidence")

    logger.info(f"[{doc_id}] Calling LLM for entity extraction")
    raw_response = await _call_llm(prompt)
    entities = _parse_entities_json(raw_response)

    confidences: list[float] = []
    for entity in entities:
        if "name" not in entity:
            entity["name"] = "Unknown"
        if "entity_type" not in entity:
            entity["entity_type"] = "other"
        if "role" not in entity:
            entity["role"] = "mentioned"
        if "fields" not in entity:
            entity["fields"] = {}
        try:
            llm_confidence = float(entity.get("confidence", 1.0))
        except (TypeError, ValueError):
            llm_confidence = 0.5
        confidence_details = compute_item_confidence(
            llm_confidence=llm_confidence,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            value=entity.get("name"),
            evidence=entity.get("evidence"),
            required_values=[
                entity.get("name"),
                entity.get("entity_type"),
                entity.get("role"),
            ],
        )
        entity["confidence"] = confidence_details["score"]
        entity["confidence_details"] = confidence_details
        confidences.append(confidence_details["score"])

    _normalize_entity_field_keys(entities)

    avg_conf = sum(confidences) / len(confidences) if confidences else None

    init_db()
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if doc:
            doc.status = "ENTITIES_EXTRACTED"
            doc.updated_at = datetime.utcnow()
            session.add(doc)
        session.commit()

    payload["extracted_entities"] = entities
    payload["entity_extraction_confidence"] = round(avg_conf, 4) if avg_conf is not None else None
    payload["history"] = payload.get("history", []) + ["entity_extraction_completed"]
    logger.info(f"[{doc_id}] Extracted {len(entities)} entities (avg_confidence={avg_conf})")
    if doc_id:
        record_pipeline_event(doc_id, "entity_extraction", "completed")
    return payload


