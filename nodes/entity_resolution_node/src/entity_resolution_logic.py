from __future__ import annotations

import json
import os
import uuid
import logging
import unicodedata
import re
from datetime import datetime

import httpx
from sqlmodel import select

from dmsai_models import (
    Document, Entity, EntityField, DocumentEntity, SystemConfig, compute_item_confidence,
    get_session, init_db, record_pipeline_event,
)

logger = logging.getLogger("entity_resolution_node")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma3:27b")

IDENTIFIER_KEYS = {"tax_id", "registration_number", "email", "siret", "siren", "vat_number"}

LEGAL_SUFFIXES = re.compile(
    r"\b(s\.?a\.?s\.?|s\.?a\.?r\.?l\.?|s\.?a\.?|e\.?u\.?r\.?l\.?"
    r"|s\.?c\.?i\.?|s\.?n\.?c\.?|g\.?m\.?b\.?h\.?|inc\.?|corp\.?"
    r"|ltd\.?|llc\.?|plc\.?|co\.?|pty\.?)\b",
    re.IGNORECASE,
)

ENTITY_DISAMBIG_PROMPT = """Determine if these two records refer to the same real-world entity.
Consider name variations, abbreviations, legal suffixes, and shared identifiers.

Entity A:
- Name: {name_a}
- Type: {type_a}
- Fields: {fields_a}

Entity B:
- Name: {name_b}
- Type: {type_b}
- Fields: {fields_b}

Respond with ONLY a valid JSON object: {{"same": true/false, "confidence": 0.0-1.0, "canonical_name": "<best canonical name for this entity>"}}"""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[\s\-\.\/_]", "", value).lower().strip()


def _strip_legal_suffix(name: str) -> str:
    return LEGAL_SUFFIXES.sub("", name).strip().rstrip(",").strip()


def _levenshtein_ratio(s1: str, s2: str) -> float:
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1, len2 = len(s1), len(s2)
    matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]

    for i in range(len1 + 1):
        matrix[i][0] = i
    for j in range(len2 + 1):
        matrix[0][j] = j

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )

    max_len = max(len1, len2)
    return 1.0 - (matrix[len1][len2] / max_len) if max_len > 0 else 1.0


def _incoming_fields_lower(fields: dict) -> dict[str, object]:
    return {str(k).lower(): v for k, v in fields.items()}


def _existing_fields_lower(efs: list[EntityField]) -> dict[str, str]:
    return {ef.field_name.lower(): ef.field_value for ef in efs}


def _identifiers_match(
    incoming_fields: dict,
    existing_fields: list[EntityField],
) -> bool:
    """Exact match on normalized identifier values for any known identifier key."""
    inc = _incoming_fields_lower(incoming_fields)
    ex = _existing_fields_lower(existing_fields)
    for key in IDENTIFIER_KEYS:
        iv = inc.get(key)
        sv = ex.get(key)
        if iv and sv:
            if _normalize_identifier(str(iv)) == _normalize_identifier(str(sv)):
                return True
    return False


def _name_similarity(entity_data: dict, existing: Entity) -> float:
    name_norm = _normalize(entity_data.get("name", ""))
    existing_norm = _normalize(existing.name)
    a = _strip_legal_suffix(name_norm)
    b = _strip_legal_suffix(existing_norm)
    return _levenshtein_ratio(a, b)


async def _call_llm(prompt: str, json_format: bool = False) -> str:
    from dmsai_models.llm import call_llm
    return await call_llm(prompt, json_format=json_format)


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


def _config_float(key: str, default: float) -> float:
    try:
        return float(_config_value(key, str(default)))
    except (TypeError, ValueError):
        return default


async def _llm_disambiguate(
    incoming: dict,
    existing: Entity,
    existing_fields: list[EntityField],
) -> dict:
    fields_b = {ef.field_name: ef.field_value for ef in existing_fields}
    prompt = _config_value("entity_resolution_prompt", ENTITY_DISAMBIG_PROMPT).format(
        name_a=incoming.get("name", ""),
        type_a=incoming.get("entity_type", ""),
        fields_a=json.dumps(incoming.get("fields", {}), ensure_ascii=False),
        name_b=existing.name,
        type_b=existing.entity_type,
        fields_b=json.dumps(fields_b, ensure_ascii=False),
    )
    try:
        raw = await _call_llm(prompt, json_format=True)
        result = json.loads(raw.strip())
        return {
            "same": bool(result.get("same", False)),
            "confidence": float(result.get("confidence", 0.0)),
            "canonical_name": result.get("canonical_name", ""),
        }
    except Exception as e:
        logger.warning(f"LLM disambiguation failed: {e}")
        return {"same": False, "confidence": 0.0, "canonical_name": ""}


async def _resolve_entity(
    entity_data: dict,
    candidates: list[Entity],
    entity_fields_map: dict[str, list[EntityField]],
) -> tuple[Entity | None, float, str | None]:
    """
    Staged resolution: hard identifier match -> name similarity -> LLM in ambiguous band only.
    Returns (matched_entity, match_confidence, suggested_canonical_name).
    """
    incoming_fields = entity_data.get("fields") or {}
    if not isinstance(incoming_fields, dict):
        incoming_fields = {}

    for existing in candidates:
        efs = entity_fields_map.get(existing.id, [])
        if _identifiers_match(incoming_fields, efs):
            logger.info(
                f"Entity matched by identifier: '{entity_data.get('name')}' -> '{existing.name}'"
            )
            return existing, 1.0, None

    best: Entity | None = None
    best_sim = 0.0
    for existing in candidates:
        sim = _name_similarity(entity_data, existing)
        if sim > best_sim:
            best_sim = sim
            best = existing

    name_match_high = _config_float("entity_name_match_high", float(os.environ.get("ENTITY_NAME_MATCH_HIGH", "0.85")))
    name_match_low = _config_float("entity_name_match_low", float(os.environ.get("ENTITY_NAME_MATCH_LOW", "0.6")))
    llm_confirm_min = _config_float("entity_llm_confirm_min", float(os.environ.get("ENTITY_LLM_CONFIRM_MIN", "0.7")))

    if best is not None and best_sim >= name_match_high:
        logger.info(
            f"Entity matched by name ({best_sim:.2f}): '{entity_data.get('name')}' -> '{best.name}'"
        )
        return best, round(best_sim, 3), None

    if best is not None and name_match_low <= best_sim < name_match_high:
        logger.info(
            f"Entity ambiguous name ({best_sim:.2f}), LLM disambiguation: "
            f"'{entity_data.get('name')}' vs '{best.name}'"
        )
        llm = await _llm_disambiguate(entity_data, best, entity_fields_map.get(best.id, []))
        if llm["same"] and llm["confidence"] >= llm_confirm_min:
            canon = (llm.get("canonical_name") or "").strip() or None
            logger.info(
                f"LLM confirmed match (conf={llm['confidence']:.2f}): "
                f"'{entity_data.get('name')}' -> '{best.name}'"
            )
            return best, round(llm["confidence"], 3), canon

    return None, 0.0, None


async def process_entity_resolution(payload: dict) -> dict:
    """Match extracted entities against DB, create new ones if needed."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "entity_resolution", "started")
    extracted_entities = payload.get("extracted_entities", [])
    ocr_text = payload.get("ocr_text", "")
    ocr_confidence = payload.get("ocr_confidence")

    if not extracted_entities:
        logger.info(f"[{doc_id}] No entities to resolve")
        payload["resolved_entities"] = []
        payload["entity_resolution_confidence"] = None
        payload["history"] = payload.get("history", []) + ["entity_resolution_skipped"]
        if doc_id:
            record_pipeline_event(doc_id, "entity_resolution", "completed", details="skipped_no_entities")
        return payload

    init_db()
    resolved = []
    link_confidences: list[float] = []

    with get_session() as session:
        entity_types_needed = {e.get("entity_type", "other") for e in extracted_entities}
        candidates = session.exec(
            select(Entity).where(Entity.entity_type.in_(entity_types_needed))
        ).all()
        untyped = session.exec(select(Entity).where(Entity.entity_type == "other")).all()
        all_candidates = list({e.id: e for e in list(candidates) + list(untyped)}.values())

        entity_fields_map: dict[str, list[EntityField]] = {}
        for ent in all_candidates:
            efs = session.exec(
                select(EntityField).where(EntityField.entity_id == ent.id)
            ).all()
            entity_fields_map[ent.id] = efs

        for entity_data in extracted_entities:
            etype = entity_data.get("entity_type", "other")
            ext_conf = 0.5
            try:
                ext_conf = float(entity_data.get("confidence", 0.5))
                ext_conf = max(0.0, min(1.0, ext_conf))
            except (TypeError, ValueError):
                pass

            type_candidates = [
                e for e in all_candidates
                if e.entity_type == etype or e.entity_type == "other" or etype == "other"
            ]

            matched, match_conf, suggested_canonical = await _resolve_entity(
                entity_data, type_candidates, entity_fields_map,
            )

            if matched:
                entity_id = matched.id
                _update_entity_fields(session, matched, entity_data, doc_id, ext_conf)
                if suggested_canonical and not matched.canonical_name:
                    matched.canonical_name = suggested_canonical
                    session.add(matched)
                link_details = compute_item_confidence(
                    llm_confidence=ext_conf,
                    ocr_text=ocr_text,
                    ocr_confidence=ocr_confidence,
                    value=entity_data.get("name"),
                    evidence=entity_data.get("evidence"),
                    required_values=[
                        entity_data.get("name"),
                        entity_data.get("entity_type"),
                        entity_data.get("role"),
                    ],
                    agreement=match_conf,
                    ambiguity=match_conf,
                )
                link_conf = link_details["score"]
            else:
                entity_id = str(uuid.uuid4())
                incoming_name = entity_data.get("name", "Unknown")
                link_details = compute_item_confidence(
                    llm_confidence=ext_conf,
                    ocr_text=ocr_text,
                    ocr_confidence=ocr_confidence,
                    value=incoming_name,
                    evidence=entity_data.get("evidence"),
                    required_values=[
                        incoming_name,
                        entity_data.get("entity_type"),
                        entity_data.get("role"),
                    ],
                    agreement=0.75,
                    ambiguity=0.75,
                )
                new_entity = Entity(
                    id=entity_id,
                    entity_type=etype,
                    name=incoming_name,
                    canonical_name=incoming_name,
                    created_at=datetime.utcnow(),
                )
                session.add(new_entity)
                session.flush()

                new_fields: list[EntityField] = []
                for fname, fval in entity_data.get("fields", {}).items():
                    if fval:
                        ef = EntityField(
                            id=str(uuid.uuid4()),
                            entity_id=entity_id,
                            field_name=fname,
                            field_value=str(fval),
                            confidence=ext_conf,
                            confidence_details=json.dumps(
                                entity_data.get("confidence_details") or {},
                                ensure_ascii=False,
                            ),
                            source_document_id=doc_id,
                        )
                        session.add(ef)
                        new_fields.append(ef)

                all_candidates.append(new_entity)
                entity_fields_map[entity_id] = new_fields
                link_conf = link_details["score"]
                logger.info(f"[{doc_id}] Created new entity: {new_entity.name} ({new_entity.entity_type})")

            link_confidences.append(link_conf)

            doc_entity = DocumentEntity(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                entity_id=entity_id,
                role=entity_data.get("role", "mentioned"),
                confidence=link_conf,
                confidence_details=json.dumps(link_details, ensure_ascii=False),
            )
            session.add(doc_entity)

            resolved.append({
                "entity_id": entity_id,
                "name": entity_data.get("name", "Unknown"),
                "role": entity_data.get("role", "mentioned"),
                "is_new": matched is None,
                "match_confidence": match_conf if matched else link_conf,
                "confidence": link_conf,
                "confidence_details": link_details,
            })

        doc = session.get(Document, doc_id)
        if doc:
            doc.status = "ENTITIES_RESOLVED"
            doc.updated_at = datetime.utcnow()
            session.add(doc)

        session.commit()

    avg_res = sum(link_confidences) / len(link_confidences) if link_confidences else None
    payload["entity_resolution_confidence"] = round(avg_res, 4) if avg_res is not None else None
    payload["resolved_entities"] = resolved
    payload["history"] = payload.get("history", []) + ["entity_resolution_completed"]
    logger.info(
        f"[{doc_id}] Resolved {len(resolved)} entities ({sum(1 for r in resolved if r['is_new'])} new), "
        f"avg_resolution_confidence={avg_res}"
    )
    if doc_id:
        record_pipeline_event(doc_id, "entity_resolution", "completed")
    return payload


def _update_entity_fields(
    session, entity: Entity, entity_data: dict, doc_id: str, extraction_confidence: float,
):
    """Add any new field values from this document to an existing entity."""
    existing_fields = session.exec(
        select(EntityField).where(EntityField.entity_id == entity.id)
    ).all()
    existing_field_map = {ef.field_name.lower(): ef for ef in existing_fields}

    for fname, fval in entity_data.get("fields", {}).items():
        if not fval:
            continue
        if fname.lower() not in existing_field_map:
            ef = EntityField(
                id=str(uuid.uuid4()),
                entity_id=entity.id,
                field_name=fname,
                field_value=str(fval),
                confidence=extraction_confidence,
                confidence_details=json.dumps(
                    entity_data.get("confidence_details") or {},
                    ensure_ascii=False,
                ),
                source_document_id=doc_id,
            )
            session.add(ef)

    entity.updated_at = datetime.utcnow()
    session.add(entity)
