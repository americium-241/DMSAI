from __future__ import annotations

import json
import os
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from dmsai_models import (
    CanonicalDocumentClass, Document, SystemConfig, classification_margin,
    compute_item_confidence, get_session, init_db, record_pipeline_event,
)

logger = logging.getLogger("classification_node")

DEFAULT_CATEGORIES = [
    {"name": "invoice", "definition": "A commercial document detailing products/services and amounts owed"},
    {"name": "receipt", "definition": "A document acknowledging payment received"},
    {"name": "contract", "definition": "A legally binding agreement between parties"},
    {"name": "letter", "definition": "A written message to a person or organization"},
    {"name": "report", "definition": "A formal document presenting information or analysis"},
    {"name": "form", "definition": "A structured document with fields to fill in"},
    {"name": "other", "definition": "Does not fit any of the above categories"},
]

CLASSIFICATION_PROMPT = """You are a hierarchical document classification system.

Classify the document into one canonical top-level category and, when useful, one canonical subcategory below it.

Known canonical category hierarchy:
{categories}

Rules:
- Prefer existing canonical category and subcategory labels whenever they are a reasonable fit.
- Treat synonyms, translations, abbreviations, plural forms, and spelling variants as the same label.
- Do not invent near-duplicate categories. For example, "supplier_invoice", "vendor bill", and "facture" should map to "invoice" if that canonical category exists.
- Use "other" only when no specific known or new category is appropriate.
- If no known top-level category fits and a clearly reusable new category is needed, set "is_new" to true.
- If a useful subcategory exists or should be created, provide it as concise English snake_case. Otherwise use null.

Document text:
---
{ocr_text}
---

Respond with ONLY a valid JSON object:
{{
  "category": "<canonical_or_new_category_name>",
  "subcategory": "<canonical_or_new_subcategory_name_or_null>",
  "confidence": <0.0_to_1.0>,
  "evidence": "<short exact quote from the document that supports the classification, or null>",
  "alternatives": [
    {{"category": "<alternative_category>", "confidence": <0.0_to_1.0>}}
  ],
  "is_new": true/false,
  "definition": "<one-line category definition>",
  "subcategory_is_new": true/false,
  "subcategory_definition": "<one-line subcategory definition>",
  "reason": "<short reason>"
}}"""

CANONICAL_CATEGORY_MAP_PROMPT = """You are maintaining a canonical document category taxonomy.

Given the existing canonical categories and a proposed category, determine if the proposed category is actually the same as an existing category.

Existing canonical categories:
{categories}

Proposed category:
- Name: {category}
- Definition: {definition}

Rules:
- Match if the proposed category is a synonym, translation, abbreviation, spelling variant, plural/singular variant, or narrower duplicate of an existing category.
- Prefer an existing broad category over creating a near-duplicate.
- Only create a new canonical category when it is genuinely different from all existing categories.

Respond with ONLY a valid JSON object:
- If it matches an existing category: {{"match": "<canonical_name>", "alias": "<proposed_alias>"}}
- If it is new: {{"new": "<canonical_snake_case_name>", "description": "<one-line description>"}}"""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

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


def _normalize_label(label: str) -> str:
    label = label.strip().lower()
    label = re.sub(r"[^a-z0-9]+", "_", label)
    label = re.sub(r"_+", "_", label).strip("_")
    return label or "other"


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = [line for line in raw.splitlines() if not line.strip().startswith("```")]
        raw = "\n".join(lines)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(raw[start:end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


def _load_config_categories() -> list[dict]:
    config_path = Path("config/local_config.yaml")
    if not config_path.is_file():
        return DEFAULT_CATEGORIES
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Failed to read classification config: %s", e)
        return DEFAULT_CATEGORIES
    categories = data.get("categories")
    if not isinstance(categories, list):
        return DEFAULT_CATEGORIES
    out = []
    for item in categories:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        out.append({
            "name": _normalize_label(str(item["name"])),
            "definition": str(item.get("definition") or ""),
        })
    return out or DEFAULT_CATEGORIES


def _safe_aliases(raw_aliases: str | None) -> list[str]:
    try:
        aliases = json.loads(raw_aliases or "[]")
        if isinstance(aliases, list):
            return [_normalize_label(str(alias)) for alias in aliases if str(alias).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _category_lines(categories: list[CanonicalDocumentClass]) -> str:
    if not categories:
        return "(no canonical categories defined yet)"
    children: dict[str | None, list[CanonicalDocumentClass]] = {}
    for category in categories:
        children.setdefault(category.parent_id, []).append(category)

    def line_for(category: CanonicalDocumentClass, depth: int) -> list[str]:
        aliases = _safe_aliases(category.aliases)
        alias_text = f" aliases={aliases}" if aliases else ""
        prefix = "  " * depth
        lines = [f"{prefix}- {category.canonical_name}: {category.description}{alias_text}"]
        for child in sorted(children.get(category.id, []), key=lambda c: c.canonical_name):
            lines.extend(line_for(child, depth + 1))
        return lines

    lines = []
    roots = children.get(None) or categories
    for category in sorted(roots, key=lambda c: c.canonical_name):
        lines.extend(line_for(category, 0))
    return "\n".join(lines)


def _seed_config_categories_if_missing() -> None:
    """Mirror local_config categories into the canonical taxonomy without overwriting DB edits."""
    init_db()
    config_categories = _load_config_categories()
    with get_session() as session:
        existing = {
            c.canonical_name
            for c in session.exec(select(CanonicalDocumentClass)).all()
        }
        changed = False
        for category in config_categories:
            name = _normalize_label(category["name"])
            if name in existing:
                continue
            session.add(
                CanonicalDocumentClass(
                    id=str(uuid.uuid4()),
                    parent_id=None,
                    canonical_name=name,
                    description=category["definition"],
                    aliases="[]",
                    created_at=datetime.utcnow(),
                )
            )
            existing.add(name)
            changed = True
        if changed:
            session.commit()


def _load_canonical_categories() -> list[CanonicalDocumentClass]:
    _seed_config_categories_if_missing()
    with get_session() as session:
        return session.exec(select(CanonicalDocumentClass)).all()


def _classification_settings() -> tuple[bool, float]:
    create_new = os.environ.get("CLASSIFICATION_CREATE_NEW_CATEGORIES", "true").lower() == "true"
    min_confidence = float(os.environ.get("CLASSIFICATION_NEW_CATEGORY_MIN_CONFIDENCE", "0.75"))
    try:
        init_db()
        with get_session() as session:
            rows = session.exec(
                select(SystemConfig).where(
                    SystemConfig.key.in_([
                        "classification_create_new_categories",
                        "classification_new_category_min_confidence",
                    ])
                )
            ).all()
        cfg = {row.key: row.value for row in rows}
        create_new = cfg.get("classification_create_new_categories", str(create_new)).lower() == "true"
        min_confidence = float(cfg.get("classification_new_category_min_confidence", min_confidence))
    except Exception as e:
        logger.warning("Failed to load classification settings, using defaults: %s", e)
    return create_new, min_confidence


def _lookup_existing_category(
    proposed: str,
    categories: list[CanonicalDocumentClass],
    parent_id: str | None = None,
) -> CanonicalDocumentClass | None:
    normalized = _normalize_label(proposed)
    for category in categories:
        if category.parent_id != parent_id:
            continue
        if normalized == _normalize_label(category.canonical_name):
            return category
        if normalized in _safe_aliases(category.aliases):
            return category
    return None


def _add_alias(category_id: str, alias: str) -> None:
    alias = _normalize_label(alias)
    with get_session() as session:
        category = session.get(CanonicalDocumentClass, category_id)
        if not category:
            return
        aliases = _safe_aliases(category.aliases)
        if alias and alias != category.canonical_name and alias not in aliases:
            aliases.append(alias)
            category.aliases = json.dumps(sorted(aliases))
            category.updated_at = datetime.utcnow()
            session.add(category)
            session.commit()


def _create_category(
    name: str,
    description: str,
    alias: str | None = None,
    parent_id: str | None = None,
) -> CanonicalDocumentClass:
    normalized = _normalize_label(name)
    aliases = []
    if alias:
        alias_norm = _normalize_label(alias)
        if alias_norm != normalized:
            aliases.append(alias_norm)

    with get_session() as session:
        existing = session.exec(
            select(CanonicalDocumentClass).where(
                CanonicalDocumentClass.canonical_name == normalized,
            )
        ).first()
        if existing:
            return existing
        category = CanonicalDocumentClass(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            canonical_name=normalized,
            description=description or f"Documents categorized as {normalized}",
            aliases=json.dumps(aliases),
            created_at=datetime.utcnow(),
        )
        session.add(category)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.exec(
                select(CanonicalDocumentClass).where(
                    CanonicalDocumentClass.canonical_name == normalized,
                )
            ).first()
            if existing:
                return existing
            raise
        session.refresh(category)
        return category


async def _llm_classify(ocr_text: str, categories: list[CanonicalDocumentClass]) -> dict:
    """Classify with an LLM against the canonical document taxonomy."""
    prompt_template = _config_value("classification_prompt", CLASSIFICATION_PROMPT)
    prompt = prompt_template.format(
        categories=_category_lines(categories),
        ocr_text=ocr_text[:8000],
    )
    raw = await _call_llm(prompt, json_format=True)
    parsed = _parse_json_object(raw)
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    alternatives = parsed.get("alternatives")
    if not isinstance(alternatives, list):
        alternatives = []
    return {
        "category": _normalize_label(str(parsed.get("category") or "other")),
        "subcategory": (
            _normalize_label(str(parsed["subcategory"]))
            if parsed.get("subcategory") not in (None, "", "null")
            else None
        ),
        "confidence": confidence,
        "evidence": parsed.get("evidence"),
        "alternatives": alternatives,
        "is_new": bool(parsed.get("is_new", False)),
        "definition": str(parsed.get("definition") or ""),
        "subcategory_is_new": bool(parsed.get("subcategory_is_new", False)),
        "subcategory_definition": str(parsed.get("subcategory_definition") or ""),
        "reason": str(parsed.get("reason") or ""),
    }


async def _map_to_canonical(
    proposed: str,
    definition: str,
    categories: list[CanonicalDocumentClass],
    *,
    allow_create: bool,
    parent_id: str | None = None,
) -> tuple[str, str]:
    """Return (canonical_label, method_suffix) while preventing near-duplicate classes."""
    scoped_categories = [c for c in categories if c.parent_id == parent_id]
    existing = _lookup_existing_category(proposed, categories, parent_id)
    if existing:
        return existing.canonical_name, "existing"

    if not scoped_categories:
        if not allow_create:
            return "other", "fallback"
        category = _create_category(proposed, definition, parent_id=parent_id)
        return category.canonical_name, "new"

    prompt_template = _config_value("classification_canonical_map_prompt", CANONICAL_CATEGORY_MAP_PROMPT)
    prompt = prompt_template.format(
        categories=_category_lines(scoped_categories),
        category=_normalize_label(proposed),
        definition=definition or "",
    )
    raw = await _call_llm(prompt, json_format=True)
    parsed = _parse_json_object(raw)

    if parsed.get("match"):
        match_name = _normalize_label(str(parsed["match"]))
        match = _lookup_existing_category(match_name, categories, parent_id)
        if match:
            _add_alias(match.id, str(parsed.get("alias") or proposed))
            return match.canonical_name, "alias"

    if parsed.get("new"):
        if not allow_create:
            return "other", "fallback"
        category = _create_category(
            str(parsed["new"]),
            str(parsed.get("description") or definition or ""),
            alias=proposed,
            parent_id=parent_id,
        )
        return category.canonical_name, "new"

    return "other", "fallback"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

async def process_classification(payload: dict) -> dict:
    """Classify document with an LLM and canonical category labels."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "classification", "started")
    ocr_text = payload.get("ocr_text", "")
    ocr_confidence = payload.get("ocr_confidence")

    result = {
        "label": "other",
        "confidence": 0.0,
        "method": "llm_canonical",
        "cluster_id": None,
        "subcategory_label": None,
        "path": ["other"],
        "reason": "",
        "confidence_details": {},
    }

    if ocr_text:
        categories = _load_canonical_categories()
        llm_result = await _llm_classify(ocr_text, categories)
        existing = _lookup_existing_category(llm_result["category"], categories, parent_id=None)
        create_new_categories, new_category_min_confidence = _classification_settings()
        if existing:
            label = existing.canonical_name
            category_id = existing.id
            method = "llm_canonical"
        elif (
            llm_result["is_new"]
            and create_new_categories
            and llm_result["confidence"] >= new_category_min_confidence
        ):
            label, suffix = await _map_to_canonical(
                llm_result["category"],
                llm_result["definition"],
                categories,
                allow_create=True,
                parent_id=None,
            )
            categories = _load_canonical_categories()
            category = _lookup_existing_category(label, categories, parent_id=None)
            category_id = category.id if category else None
            method = f"llm_canonical_{suffix}"
        else:
            label, suffix = await _map_to_canonical(
                llm_result["category"],
                llm_result["definition"],
                categories,
                allow_create=False,
                parent_id=None,
            )
            category = _lookup_existing_category(label, categories, parent_id=None)
            category_id = category.id if category else None
            method = f"llm_canonical_{suffix}"

        subcategory_label = None
        path = [label]
        proposed_subcategory = llm_result.get("subcategory")
        if proposed_subcategory and category_id and proposed_subcategory != label:
            allow_subcategory_create = (
                llm_result["subcategory_is_new"]
                and create_new_categories
                and llm_result["confidence"] >= new_category_min_confidence
            )
            subcategory_label, sub_suffix = await _map_to_canonical(
                proposed_subcategory,
                llm_result["subcategory_definition"],
                categories,
                allow_create=allow_subcategory_create,
                parent_id=category_id,
            )
            if subcategory_label != "other":
                path.append(subcategory_label)
                method = f"{method}+subcategory_{sub_suffix}"
            else:
                subcategory_label = None

        predictions = [{"category": llm_result["category"], "confidence": llm_result["confidence"]}]
        predictions.extend(
            p for p in llm_result.get("alternatives", [])
            if isinstance(p, dict)
        )
        margin = classification_margin(predictions)
        confidence_details = compute_item_confidence(
            llm_confidence=llm_result["confidence"],
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            value=label,
            evidence=llm_result.get("evidence") or llm_result.get("reason"),
            required_values=[label],
            agreement=margin,
            ambiguity=margin,
        )

        result = {
            "label": label,
            "subcategory_label": subcategory_label,
            "path": path,
            "confidence": confidence_details["score"],
            "method": method,
            "cluster_id": None,
            "reason": llm_result["reason"],
            "evidence": llm_result.get("evidence"),
            "alternatives": llm_result.get("alternatives", []),
            "confidence_details": confidence_details,
        }
    else:
        logger.warning(f"[{doc_id}] No OCR text, defaulting classification to 'other'")

    init_db()
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if doc:
            doc.classification_label = result["label"]
            doc.classification_subcategory_label = result["subcategory_label"]
            doc.classification_path = json.dumps(result["path"])
            doc.classification_confidence = result["confidence"]
            doc.classification_method = result["method"]
            doc.cluster_id = None
            doc.status = "CLASSIFIED"
            doc.updated_at = datetime.utcnow()
            session.add(doc)
        session.commit()

    payload["classification"] = result
    payload["history"] = payload.get("history", []) + ["classification_completed"]
    logger.info(f"[{doc_id}] Classification: {result['label']} (method={result['method']}, conf={result['confidence']})")
    if doc_id:
        record_pipeline_event(doc_id, "classification", "completed")
    return payload
