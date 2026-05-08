from __future__ import annotations

import json
import os
import uuid
import logging
from datetime import datetime

import httpx
from sqlmodel import select

API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "http://localhost:8080")
INTERNAL_API_KEY = os.environ.get("DMSAI_INTERNAL_API_KEY", "")

from dmsai_models import (
    Document, DocumentField, CanonicalField, SystemConfig, compute_item_confidence,
    compute_pipeline_confidence,
    get_session, init_db, record_pipeline_event,
)

logger = logging.getLogger("field_extraction_node")

AUTO_DETECT_PROMPT = """Analyze the following document text and list ALL data fields/data points present.
Do NOT include entity-level fields (names, addresses of people/companies) -- those are already extracted.
Focus on document-level fields like: invoice_number, date, due_date, total_amount, subtotal, tax_amount,
payment_terms, reference_number, line_items, etc.

{existing_fields_hint}

Return ONLY a JSON array of field name strings. No explanation, no markdown fences.
Example: ["invoice_number", "date", "total_amount", "tax_rate"]

Document text:
{ocr_text}"""

AUTO_EXTRACT_PROMPT = """Extract the values for the following fields from this document text.

Return ONLY a JSON object with exactly three keys:
- "values": an object mapping each field name to the extracted string value, or null if not found
- "confidences": an object mapping each field name to a number from 0.0 to 1.0 (your confidence in that extraction)
- "evidence": an object mapping each field name to a short exact quote from the document that supports the value, or null

Both objects must use the same field names as listed below.
No explanation, no markdown fences.

Fields to extract: {field_names}

Document text:
{ocr_text}"""

CANONICAL_MAP_PROMPT = """You are a data schema expert. Given a list of canonical field names and a newly detected field name, determine if the new field matches any existing canonical field.

Canonical fields:
{canonical_list}

Newly detected field name: "{field_name}"

Rules:
- Match if the new name is a synonym, translation, abbreviation, or variant of an existing canonical field.
  Examples: "total_ttc" matches "total_amount", "montant_total" matches "total_amount", "numero_facture" matches "invoice_number"
- If no match exists, suggest a good canonical English snake_case name for this field.

Respond with ONLY a valid JSON object:
- If it matches an existing field: {{"match": "<canonical_name>"}}
- If it's a new field: {{"new": "<suggested_canonical_name>", "description": "<one-line description>"}}"""


def _truncate(text: str, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


async def _call_llm(prompt: str, document_id: str | None = None) -> str:
    from dmsai_models.llm import call_llm
    return await call_llm(prompt, stage="field_extraction", document_id=document_id)


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


def _parse_json_array(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return [str(x) for x in result]
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            try:
                return [str(x) for x in json.loads(raw[start:end + 1])]
            except json.JSONDecodeError:
                pass
    return []


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _split_values_and_confidences(parsed: dict) -> tuple[dict, dict[str, float]]:
    """Support new {values, confidences} shape or legacy flat field->value object."""
    if not parsed:
        return {}, {}
    if "values" in parsed and isinstance(parsed["values"], dict):
        vals = parsed["values"]
        confs_raw = parsed.get("confidences") or {}
        out_conf: dict[str, float] = {}
        if isinstance(confs_raw, dict):
            for k, v in confs_raw.items():
                try:
                    out_conf[str(k)] = max(0.0, min(1.0, float(v)))
                except (TypeError, ValueError):
                    out_conf[str(k)] = 0.5
        return vals, out_conf
    return parsed, {}


def _split_evidence(parsed: dict) -> dict[str, object]:
    evidence = parsed.get("evidence") if isinstance(parsed, dict) else None
    return evidence if isinstance(evidence, dict) else {}


def _field_confidence_for(fname: str, confidences: dict[str, float]) -> float:
    if fname in confidences:
        return confidences[fname]
    fl = fname.lower()
    for k, v in confidences.items():
        if k.lower() == fl:
            return v
    return 0.5


def _compute_pipeline_confidence(
    payload: dict, doc: Document | None, field_extraction_avg: float | None,
) -> tuple[dict, float]:
    """Build step details and delegate final aggregation to the shared scorer."""
    ocr = payload.get("ocr_confidence")
    ocr_method = payload.get("ocr_method")
    if doc:
        if ocr is None:
            ocr = doc.ocr_confidence
        if ocr_method is None:
            ocr_method = doc.ocr_method

    cls = payload.get("classification") or {}
    cls_c = cls.get("confidence")
    cls_m = cls.get("method")
    if doc:
        if cls_c is None:
            cls_c = doc.classification_confidence
        if cls_m is None:
            cls_m = doc.classification_method

    ee = payload.get("entity_extraction_confidence")
    er = payload.get("entity_resolution_confidence")

    resolved = payload.get("resolved_entities") or []
    matched_n = sum(1 for r in resolved if not r.get("is_new"))
    new_n = sum(1 for r in resolved if r.get("is_new"))

    details = {
        "ocr": {"score": ocr, "method": ocr_method},
        "classification": {
            "score": cls_c,
            "method": cls_m,
            "details": cls.get("confidence_details"),
        },
        "entity_extraction": {
            "score": ee,
            "count": len(payload.get("extracted_entities") or []),
            "items": [
                {
                    "name": ent.get("name"),
                    "score": ent.get("confidence"),
                    "details": ent.get("confidence_details"),
                }
                for ent in payload.get("extracted_entities") or []
            ],
        },
        "entity_resolution": {
            "score": er,
            "matched": matched_n,
            "new": new_n,
            "items": [
                {
                    "entity_id": ent.get("entity_id"),
                    "name": ent.get("name"),
                    "score": ent.get("confidence"),
                    "match_confidence": ent.get("match_confidence"),
                    "details": ent.get("confidence_details"),
                }
                for ent in resolved
            ],
        },
        "field_extraction": {
            "score": field_extraction_avg,
            "count": None,
        },
    }
    return compute_pipeline_confidence(details)


async def _normalize_field_names(
    field_names: list[str], classification_label: str | None,
) -> dict[str, str]:
    """Map raw LLM field names to canonical names. Returns {raw_name: canonical_name}."""
    init_db()
    with get_session() as session:
        query = select(CanonicalField).where(CanonicalField.scope == "document")
        if classification_label:
            query = query.where(
                (CanonicalField.document_class == classification_label)
                | (CanonicalField.document_class.is_(None))
            )
        else:
            query = query.where(CanonicalField.document_class.is_(None))
        canonical_rows = session.exec(query).all()

    canonical_by_name: dict[str, CanonicalField] = {
        cf.canonical_name.lower(): cf for cf in canonical_rows
    }
    alias_to_canonical: dict[str, str] = {}
    for cf in canonical_rows:
        try:
            alias_list = json.loads(cf.aliases) if cf.aliases else []
        except (json.JSONDecodeError, TypeError):
            alias_list = []
        for alias in alias_list:
            alias_to_canonical[alias.lower()] = cf.canonical_name

    mapping: dict[str, str] = {}
    new_aliases: dict[str, list[str]] = {}

    unmapped: list[str] = []
    for fname in field_names:
        fl = fname.lower().strip()
        if fl in canonical_by_name:
            mapping[fname] = canonical_by_name[fl].canonical_name
        elif fl in alias_to_canonical:
            mapping[fname] = alias_to_canonical[fl]
        else:
            unmapped.append(fname)

    if not unmapped:
        return mapping

    canonical_list_str = "\n".join(
        f"- {cf.canonical_name}: {cf.description}" for cf in canonical_rows
    ) or "(no canonical fields defined yet)"

    for fname in unmapped:
        prompt = _config_value("field_canonical_map_prompt", CANONICAL_MAP_PROMPT).format(
            canonical_list=canonical_list_str,
            field_name=fname,
        )
        try:
            raw = await _call_llm(prompt)
            raw = raw.strip()
            parsed = _parse_json_object(raw)

            if "match" in parsed:
                canonical = parsed["match"].strip().lower()
                if canonical in canonical_by_name:
                    mapping[fname] = canonical_by_name[canonical].canonical_name
                    new_aliases.setdefault(canonical, []).append(fname.lower())
                else:
                    mapping[fname] = fname
            elif "new" in parsed:
                suggested = parsed["new"].strip().lower().replace(" ", "_")
                desc = parsed.get("description", "")
                mapping[fname] = suggested

                with get_session() as session:
                    cf = CanonicalField(
                        id=str(uuid.uuid4()),
                        scope="document",
                        canonical_name=suggested,
                        description=desc,
                        document_class=classification_label,
                        aliases=json.dumps([fname.lower()] if fname.lower() != suggested else []),
                    )
                    session.add(cf)
                    session.commit()

                canonical_by_name[suggested] = cf
                canonical_list_str += f"\n- {suggested}: {desc}"
                logger.info(f"Created new canonical field: {suggested}")
            else:
                mapping[fname] = fname
        except Exception as e:
            logger.warning(f"Canonical mapping failed for '{fname}': {e}")
            mapping[fname] = fname

    if new_aliases:
        with get_session() as session:
            for canon_lower, aliases in new_aliases.items():
                cf = canonical_by_name.get(canon_lower)
                if cf:
                    db_cf = session.get(CanonicalField, cf.id)
                    if db_cf:
                        existing = json.loads(db_cf.aliases)
                        existing.extend(a for a in aliases if a not in existing)
                        db_cf.aliases = json.dumps(existing)
                        session.add(db_cf)
            session.commit()

    return mapping


async def _auto_extract(doc_id: str, ocr_text: str, classification_label: str | None = None) -> list[dict]:
    """Two-pass auto extraction: detect fields, normalize to canonical names, then extract values."""
    truncated = _truncate(ocr_text)

    init_db()
    with get_session() as session:
        canonical_names = [
            cf.canonical_name
            for cf in session.exec(select(CanonicalField).where(CanonicalField.scope == "document")).all()
        ]
        existing = session.exec(select(DocumentField.field_name)).all()
    existing_names = sorted(set(str(n) for n in existing))
    all_hint_names = sorted(set(canonical_names + existing_names))

    hint = ""
    if all_hint_names:
        hint = (
            "Reuse these existing field names where applicable to avoid duplication:\n"
            + json.dumps(all_hint_names[:50])
        )

    detect_prompt = _config_value("field_detection_prompt", AUTO_DETECT_PROMPT).format(
        existing_fields_hint=hint,
        ocr_text=truncated,
    )
    logger.info(f"[{doc_id}] Auto pass 1: detecting field names")
    raw_fields = await _call_llm(detect_prompt)
    field_names = _parse_json_array(raw_fields)

    if not field_names:
        logger.warning(f"[{doc_id}] No fields detected in pass 1")
        return []

    logger.info(f"[{doc_id}] Pass 1.5: normalizing {len(field_names)} field names to canonical schema")
    name_mapping = await _normalize_field_names(field_names, classification_label)

    logger.info(f"[{doc_id}] Auto pass 2: extracting values for {len(field_names)} fields")
    extract_prompt = _config_value("field_extraction_prompt", AUTO_EXTRACT_PROMPT).format(
        field_names=json.dumps(field_names),
        ocr_text=truncated,
    )
    raw_values = await _call_llm(extract_prompt)
    parsed = _parse_json_object(raw_values)
    values, confidences = _split_values_and_confidences(parsed)
    evidence_by_field = _split_evidence(parsed)

    ocr_confidence = None
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if doc:
            ocr_confidence = doc.ocr_confidence

    results = []
    for fname in field_names:
        canonical = name_mapping.get(fname, fname)
        fval = values.get(fname)
        llm_conf = _field_confidence_for(fname, confidences)
        evidence = evidence_by_field.get(fname) or evidence_by_field.get(canonical)
        confidence_details = compute_item_confidence(
            llm_confidence=llm_conf,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            value=fval,
            evidence=evidence,
            required_values=[fname, fval],
        )
        results.append({
            "field_name": canonical,
            "field_value": str(fval) if fval is not None else None,
            "confidence": confidence_details["score"],
            "confidence_details": confidence_details,
            "evidence": evidence,
            "extraction_method": "auto",
        })

    return results


async def process_field_extraction(payload: dict) -> dict:
    """Extract document fields. Terminal node -- no forwarding."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "field_extraction", "started")
    ocr_text = payload.get("ocr_text", "")
    classification_label = payload.get("classification", {}).get("label")

    if not ocr_text:
        logger.warning(f"[{doc_id}] No OCR text, skipping field extraction")
        # Still mark the document COMPLETED — field extraction is the terminal
        # node and the document must not stay stuck in an intermediate status.
        if doc_id:
            init_db()
            with get_session() as session:
                doc = session.get(Document, doc_id)
                if doc:
                    doc.status = "COMPLETED"
                    doc.processed_at = datetime.utcnow()
                    doc.updated_at = datetime.utcnow()
                    session.add(doc)
                session.commit()
        payload["extracted_fields"] = []
        payload["pipeline_confidence"] = 0.0
        payload["history"] = payload.get("history", []) + ["field_extraction_skipped"]
        if doc_id:
            record_pipeline_event(doc_id, "field_extraction", "completed", details="skipped_no_ocr")
        return payload

    fields = await _auto_extract(doc_id, ocr_text, classification_label)

    field_confs = [float(f.get("confidence", 1.0)) for f in fields]
    fe_avg = sum(field_confs) / len(field_confs) if field_confs else None

    init_db()
    with get_session() as session:
        doc = session.get(Document, doc_id)
        details, pipeline = _compute_pipeline_confidence(payload, doc, fe_avg)
        details["field_extraction"]["count"] = len(fields)
        details["field_extraction"]["items"] = [
            {
                "field_name": f.get("field_name"),
                "score": f.get("confidence"),
                "details": f.get("confidence_details"),
            }
            for f in fields
        ]

        for f in fields:
            df = DocumentField(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                field_name=f["field_name"],
                field_value=f["field_value"],
                confidence=float(f.get("confidence", 1.0)),
                confidence_details=json.dumps(f.get("confidence_details") or {}, ensure_ascii=False),
                extraction_method=f["extraction_method"],
            )
            session.add(df)

        if doc:
            doc.status = "COMPLETED"
            doc.processed_at = datetime.utcnow()
            doc.updated_at = datetime.utcnow()
            doc.confidence_details = json.dumps(details, ensure_ascii=False)
            doc.pipeline_confidence = pipeline
            session.add(doc)

        session.commit()

    payload["extracted_fields"] = fields
    payload["field_extraction_confidence"] = round(fe_avg, 4) if fe_avg is not None else None
    payload["pipeline_confidence"] = pipeline
    payload["confidence_details"] = details
    payload["history"] = payload.get("history", []) + ["field_extraction_completed"]
    logger.info(
        f"[{doc_id}] Extracted {len(fields)} fields, "
        f"pipeline_confidence={pipeline}"
    )

    await _trigger_bucket_assignment()

    if doc_id:
        record_pipeline_event(doc_id, "field_extraction", "completed")

    return payload


async def _trigger_bucket_assignment() -> None:
    """Best-effort call to the API gateway to auto-assign completed docs to buckets."""
    if not INTERNAL_API_KEY:
        logger.warning("Bucket auto-assign skipped: DMSAI_INTERNAL_API_KEY is not configured")
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{API_GATEWAY_URL}/api/buckets/auto-assign",
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Key": INTERNAL_API_KEY,
                },
            )
            if resp.status_code < 400:
                logger.info("Bucket auto-assign triggered successfully")
            else:
                logger.warning(f"Bucket auto-assign returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Bucket auto-assign failed (non-blocking): {e}")
