"""LLM-first entity resolution node.

Resolution pipeline (in order):
  1. Hard identifier match  (tax_id, siret, …)     → conf = 1.0, no LLM needed
  2. Token-overlap pre-filter                        → select top-K cheap candidates
  3. LLM open question per candidate                 → "are these the same entity?"
  4. Best LLM match above threshold wins, else create new entity

The old Levenshtein / band-based gating is removed.  The LLM is now the
primary arbiter for name resolution; it uses open-ended reasoning so it can
consider abbreviations, legal forms, aliases, and conflicting evidence before
answering.
"""
from __future__ import annotations

import json
import os
import re
import uuid
import unicodedata
import logging
from datetime import datetime

from sqlmodel import select

from dmsai_models import (
    Document, Entity, EntityField, DocumentEntity, SystemConfig,
    compute_item_confidence, get_session, init_db, record_pipeline_event,
)

logger = logging.getLogger("entity_resolution_node")

# ---------------------------------------------------------------------------
# Hard-identifier keys used for exact matching (no LLM required)
# ---------------------------------------------------------------------------
IDENTIFIER_KEYS = {"tax_id", "registration_number", "email", "siret", "siren", "vat_number"}

LEGAL_SUFFIXES = re.compile(
    r"\b(s\.?a\.?s\.?|s\.?a\.?r\.?l\.?|s\.?a\.?|e\.?u\.?r\.?l\.?"
    r"|s\.?c\.?i\.?|s\.?n\.?c\.?|g\.?m\.?b\.?h\.?|inc\.?|corp\.?"
    r"|ltd\.?|llc\.?|plc\.?|co\.?|pty\.?)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Default prompt — stored in SystemConfig so admins can override it
# ---------------------------------------------------------------------------
ENTITY_RESOLUTION_PROMPT = """You are an entity resolution expert. Carefully examine the two entity records below and determine whether they refer to the same real-world entity.

Be conservative — only conclude they are the same entity if the evidence is compelling. Different branches, subsidiaries, or similarly-named organisations are NOT the same entity.

Entity A (incoming from the current document):
- Name: {name_a}
- Type: {type_a}
- Known fields: {fields_a}

Entity B (existing record in the knowledge base):
- Name: {name_b}
- Type: {type_b}
- Known fields: {fields_b}

Before answering, consider:
1. Could the name difference be explained by abbreviations, legal suffixes, or transliterations?
2. Do any unique identifiers (tax ID, SIRET, registration number, email) match or explicitly conflict?
3. Is there any strong evidence they are DIFFERENT entities (different country, conflicting IDs, different industry)?
4. How confident are you overall?

Respond with ONLY a valid JSON object — no markdown, no explanation outside the JSON:
{{"same": true/false, "confidence": 0.0-1.0, "reasoning": "<one sentence>", "canonical_name": "<best canonical name if same, else empty string>"}}"""


# ---------------------------------------------------------------------------
# Text normalisation helpers (kept for pre-filtering only, not for gating)
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text.lower().strip())


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[\s\-\.\/_]", "", value).lower().strip()


def _strip_legal_suffix(name: str) -> str:
    return LEGAL_SUFFIXES.sub("", name).strip().rstrip(",").strip()


def _token_set(name: str) -> set[str]:
    """Return the normalised token set of a name (no legal suffixes)."""
    cleaned = _strip_legal_suffix(_normalize(name))
    return {t for t in re.split(r"\W+", cleaned) if len(t) > 1}


def _token_overlap(name_a: str, name_b: str) -> float:
    """Jaccard token overlap between two entity names — fast, no LLM."""
    ta, tb = _token_set(name_a), _token_set(name_b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _config_value(key: str, default: str) -> str:
    try:
        init_db()
        with get_session() as session:
            row = session.get(SystemConfig, key)
            if row and row.value:
                return row.value
    except Exception as exc:
        logger.warning("Failed to load config %s: %s", key, exc)
    return default


def _config_float(key: str, default: float) -> float:
    try:
        return float(_config_value(key, str(default)))
    except (TypeError, ValueError):
        return default


def _config_int(key: str, default: int) -> int:
    try:
        return int(_config_value(key, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Identifier matching (hard match, no LLM)
# ---------------------------------------------------------------------------

def _incoming_fields_lower(fields: dict) -> dict[str, object]:
    return {str(k).lower(): v for k, v in fields.items()}


def _existing_fields_lower(efs: list[EntityField]) -> dict[str, str]:
    return {ef.field_name.lower(): ef.field_value for ef in efs}


def _identifiers_match(incoming_fields: dict, existing_fields: list[EntityField]) -> bool:
    """Return True if any known identifier key matches exactly after normalisation."""
    inc = _incoming_fields_lower(incoming_fields)
    ex = _existing_fields_lower(existing_fields)
    for key in IDENTIFIER_KEYS:
        iv = inc.get(key)
        sv = ex.get(key)
        if iv and sv and _normalize_identifier(str(iv)) == _normalize_identifier(str(sv)):
            return True
    return False


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

async def _call_llm(prompt: str, json_format: bool = False) -> str:
    from dmsai_models.llm import call_llm
    return await call_llm(prompt, json_format=json_format)


async def _llm_compare(
    incoming: dict,
    existing: Entity,
    existing_fields: list[EntityField],
) -> dict:
    """
    Ask the LLM the open resolution question.
    Returns {"same": bool, "confidence": float, "reasoning": str, "canonical_name": str}.
    """
    fields_b = {ef.field_name: ef.field_value for ef in existing_fields}
    prompt = _config_value("entity_resolution_prompt", ENTITY_RESOLUTION_PROMPT).format(
        name_a=incoming.get("name", ""),
        type_a=incoming.get("entity_type", ""),
        fields_a=json.dumps(incoming.get("fields", {}), ensure_ascii=False),
        name_b=existing.name,
        type_b=existing.entity_type,
        fields_b=json.dumps(fields_b, ensure_ascii=False),
    )
    try:
        raw = await _call_llm(prompt, json_format=True)
        text = raw.strip()
        # Strip markdown fences if the model adds them
        if text.startswith("```"):
            lines = [l for l in text.splitlines() if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        result = json.loads(text)
        return {
            "same": bool(result.get("same", False)),
            "confidence": float(result.get("confidence", 0.0)),
            "reasoning": str(result.get("reasoning", "")),
            "canonical_name": str(result.get("canonical_name", "")).strip(),
        }
    except Exception as exc:
        logger.warning("LLM entity comparison failed: %s", exc)
        return {"same": False, "confidence": 0.0, "reasoning": "llm_error", "canonical_name": ""}


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

async def _resolve_entity(
    entity_data: dict,
    candidates: list[Entity],
    entity_fields_map: dict[str, list[EntityField]],
) -> tuple[Entity | None, float, str | None]:
    """
    LLM-first resolution.

    Steps:
      1. Hard identifier match  → return immediately at conf 1.0
      2. Token-overlap pre-filter → keep top-K candidates for LLM
      3. LLM open question for each candidate (in order of pre-filter score)
      4. Return the first candidate where LLM confidence ≥ merge_threshold
         (ties broken by pre-filter score so the closest name wins)

    Returns (matched_entity | None, confidence, suggested_canonical_name | None).
    """
    incoming_fields = entity_data.get("fields") or {}
    if not isinstance(incoming_fields, dict):
        incoming_fields = {}

    # — Step 1: hard identifier match ----------------------------------------
    for existing in candidates:
        efs = entity_fields_map.get(existing.id, [])
        if _identifiers_match(incoming_fields, efs):
            logger.info(
                "Entity matched by identifier: '%s' → '%s'",
                entity_data.get("name"), existing.name,
            )
            return existing, 1.0, None

    if not candidates:
        return None, 0.0, None

    # — Step 2: token-overlap pre-filter ----------------------------------------
    top_k = _config_int("entity_resolution_top_k", int(os.environ.get("ENTITY_RESOLUTION_TOP_K", "5")))
    incoming_name = entity_data.get("name", "")

    scored: list[tuple[float, Entity]] = []
    for existing in candidates:
        score = _token_overlap(incoming_name, existing.name)
        scored.append((score, existing))

    # Sort descending by token overlap, take top K
    scored.sort(key=lambda x: x[0], reverse=True)
    top_candidates = scored[:top_k]

    # Skip LLM entirely if no candidate has any token overlap
    min_overlap = _config_float("entity_resolution_min_overlap", float(os.environ.get("ENTITY_RESOLUTION_MIN_OVERLAP", "0.1")))
    if top_candidates and top_candidates[0][0] < min_overlap:
        logger.debug(
            "No candidates above min_overlap (%.2f) for '%s' — skipping LLM",
            min_overlap, incoming_name,
        )
        return None, 0.0, None

    # — Step 3: LLM open question per candidate ---------------------------------
    merge_threshold = _config_float("entity_llm_merge_threshold", float(os.environ.get("ENTITY_LLM_MERGE_THRESHOLD", "0.75")))

    best_match: Entity | None = None
    best_conf = 0.0
    best_canonical: str | None = None

    for overlap_score, existing in top_candidates:
        if overlap_score < min_overlap:
            break  # List is sorted; once below min we're done

        llm = await _llm_compare(entity_data, existing, entity_fields_map.get(existing.id, []))
        logger.info(
            "LLM resolution '%s' vs '%s': same=%s conf=%.2f | %s",
            incoming_name, existing.name,
            llm["same"], llm["confidence"], llm.get("reasoning", ""),
        )

        if llm["same"] and llm["confidence"] >= merge_threshold:
            if llm["confidence"] > best_conf:
                best_match = existing
                best_conf = llm["confidence"]
                best_canonical = llm["canonical_name"] or None

    if best_match is not None:
        logger.info(
            "Entity resolved by LLM (conf=%.2f): '%s' → '%s'",
            best_conf, incoming_name, best_match.name,
        )
        return best_match, round(best_conf, 3), best_canonical

    return None, 0.0, None


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

async def process_entity_resolution(payload: dict) -> dict:
    """Match extracted entities against the DB, create new ones if needed."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "entity_resolution", "started")

    extracted_entities = payload.get("extracted_entities", [])
    ocr_text = payload.get("ocr_text", "")
    ocr_confidence = payload.get("ocr_confidence")

    if not extracted_entities:
        logger.info("[%s] No entities to resolve", doc_id)
        payload["resolved_entities"] = []
        payload["entity_resolution_confidence"] = None
        payload["history"] = payload.get("history", []) + ["entity_resolution_skipped"]
        if doc_id:
            record_pipeline_event(doc_id, "entity_resolution", "completed", details="skipped_no_entities")
        return payload

    init_db()
    resolved: list[dict] = []
    link_confidences: list[float] = []

    with get_session() as session:
        # Load candidates filtered by the entity types we actually need
        entity_types_needed = {e.get("entity_type", "other") for e in extracted_entities}
        candidates = session.exec(
            select(Entity).where(Entity.entity_type.in_(entity_types_needed))
        ).all()
        untyped = session.exec(select(Entity).where(Entity.entity_type == "other")).all()
        all_candidates = list({e.id: e for e in list(candidates) + list(untyped)}.values())

        # Pre-load all entity fields to avoid N+1 queries
        entity_fields_map: dict[str, list[EntityField]] = {}
        for ent in all_candidates:
            entity_fields_map[ent.id] = session.exec(
                select(EntityField).where(EntityField.entity_id == ent.id)
            ).all()

        for entity_data in extracted_entities:
            etype = entity_data.get("entity_type", "other")
            ext_conf = max(0.0, min(1.0, float(entity_data.get("confidence", 0.5) or 0.5)))

            # Only pass type-compatible candidates
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
                logger.info("[%s] Created new entity: %s (%s)", doc_id, new_entity.name, new_entity.entity_type)

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
        "[%s] Resolved %d entities (%d new), avg_resolution_confidence=%s",
        doc_id, len(resolved), sum(1 for r in resolved if r["is_new"]), avg_res,
    )
    if doc_id:
        record_pipeline_event(doc_id, "entity_resolution", "completed")
    return payload


# ---------------------------------------------------------------------------
# Field-update helper (unchanged)
# ---------------------------------------------------------------------------

def _update_entity_fields(
    session, entity: Entity, entity_data: dict, doc_id: str, extraction_confidence: float,
) -> None:
    """Merge new field values from this document into an existing entity record."""
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
