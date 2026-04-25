from __future__ import annotations

import json
import difflib
import re
from typing import Any


def _config_value(key: str, default: str) -> str:
    try:
        from sqlmodel import Session, select
        from .connection import get_engine
        from .models import SystemConfig

        with Session(get_engine()) as session:
            row = session.exec(select(SystemConfig).where(SystemConfig.key == key)).first()
            if row and row.value:
                return row.value
    except Exception:
        pass
    return default


def _config_float(key: str, default: float) -> float:
    try:
        return float(_config_value(key, str(default)))
    except (TypeError, ValueError):
        return default


def _config_weights(key: str, defaults: dict[str, float]) -> dict[str, float]:
    try:
        parsed = json.loads(_config_value(key, json.dumps(defaults)))
        if isinstance(parsed, dict):
            return {name: float(parsed.get(name, weight)) for name, weight in defaults.items()}
    except Exception:
        pass
    return defaults


def clamp01(value: Any, default: float = 0.0) -> float:
    """Return a numeric confidence value constrained to [0, 1]."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def confidence_level(score: float | None) -> str:
    score = clamp01(score, 0.0)
    if score >= _config_float("confidence_level_high", 0.85):
        return "high"
    if score >= _config_float("confidence_level_medium", 0.6):
        return "medium"
    return "low"


def weighted_average(signals: dict[str, float | None], weights: dict[str, float]) -> float:
    total = 0.0
    used = 0.0
    for name, weight in weights.items():
        value = signals.get(name)
        if value is None:
            continue
        total += clamp01(value) * weight
        used += weight
    if used <= 0:
        return 0.0
    return round(total / used, 4)


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def evidence_grounding_score(text: str, *snippets: Any) -> float:
    """Generic OCR grounding score for a value or supporting quote.

    This is intentionally domain-neutral: it only checks whether the proposed
    value/evidence appears in, or is very close to, the OCR text.
    """
    haystack = _normalize_text(text or "")
    candidates = [_normalize_text(str(s)) for s in snippets if s not in (None, "")]
    candidates = [c for c in candidates if c and c.lower() != "null"]
    if not haystack:
        return _config_float("confidence_empty_text_with_evidence", 0.35) if candidates else 0.0
    if not candidates:
        return 0.0

    best = 0.0
    for candidate in candidates:
        if candidate in haystack:
            best = max(best, 1.0)
            continue
        compact_candidate = re.sub(r"[^a-z0-9]+", "", candidate)
        compact_haystack = re.sub(r"[^a-z0-9]+", "", haystack)
        if compact_candidate and compact_candidate in compact_haystack:
            best = max(best, 0.92)
            continue
        if len(candidate) >= 6:
            window = min(max(len(candidate) * 2, 32), 240)
            chunks = [haystack[i:i + window] for i in range(0, max(1, len(haystack) - window + 1), max(1, window // 2))]
            similarity = max((difflib.SequenceMatcher(None, candidate, chunk).ratio() for chunk in chunks), default=0.0)
            if similarity >= 0.82:
                best = max(best, 0.8)
            elif similarity >= 0.65:
                best = max(best, 0.6)
    return round(best, 4)


def completeness_score(required_values: list[Any]) -> float:
    if not required_values:
        return 1.0
    present = sum(1 for value in required_values if value not in (None, "", [], {}) and str(value).lower() != "null")
    return round(present / len(required_values), 4)


def compute_item_confidence(
    *,
    llm_confidence: Any,
    ocr_text: str,
    ocr_confidence: Any = None,
    value: Any = None,
    evidence: Any = None,
    required_values: list[Any] | None = None,
    agreement: float | None = None,
    ambiguity: float | None = None,
) -> dict:
    """Compute an explainable, autonomous confidence score for one output item."""
    llm = clamp01(llm_confidence, 0.5)
    grounding = evidence_grounding_score(ocr_text, value, evidence)
    completeness = completeness_score(required_values or ([value] if value is not None else []))
    default_source_quality = _config_float("confidence_default_source_quality", 0.75)
    source_quality = clamp01(ocr_confidence, default_source_quality) if ocr_confidence is not None else default_source_quality

    signals = {
        "llm": llm,
        "grounding": grounding,
        "completeness": completeness,
        "source_quality": source_quality,
        "agreement": agreement,
        "ambiguity": ambiguity,
    }
    weights = _config_weights("confidence_item_weights", {
        "llm": 0.30,
        "grounding": 0.35,
        "completeness": 0.15,
        "source_quality": 0.10,
        "agreement": 0.07,
        "ambiguity": 0.03,
    })
    score = weighted_average(signals, weights)
    reasons = []
    if grounding >= 0.9:
        reasons.append("value_or_evidence_found_in_ocr")
    elif grounding >= 0.6:
        reasons.append("value_or_evidence_partially_matches_ocr")
    else:
        reasons.append("no_direct_ocr_evidence_found")
    if completeness < 1:
        reasons.append("required_parts_missing")
    if source_quality < 0.6:
        reasons.append("low_source_quality")
    if agreement is not None and agreement < 0.55:
        reasons.append("weak_agreement_signal")
    if ambiguity is not None and ambiguity < 0.55:
        reasons.append("ambiguous_output")

    return {
        "score": score,
        "level": confidence_level(score),
        "signals": {k: v for k, v in signals.items() if v is not None},
        "reasons": reasons,
    }


def classification_margin(predictions: list[dict]) -> float | None:
    scores = sorted(
        [clamp01(p.get("confidence"), 0.0) for p in predictions if isinstance(p, dict)],
        reverse=True,
    )
    if not scores:
        return None
    if len(scores) == 1:
        return scores[0]
    return round(max(0.0, scores[0] - scores[1]), 4)


def compute_pipeline_confidence(step_details: dict[str, dict]) -> tuple[dict, float]:
    """Compute the final document confidence from stage-level autonomous signals."""
    weights = _config_weights("confidence_pipeline_weights", {
        "ocr": 0.20,
        "classification": 0.20,
        "entity_extraction": 0.20,
        "entity_resolution": 0.15,
        "field_extraction": 0.25,
    })
    signals = {
        name: details.get("score") if isinstance(details, dict) else None
        for name, details in step_details.items()
    }
    score = weighted_average(signals, weights)
    enriched = dict(step_details)
    enriched["pipeline"] = {
        "score": score,
        "level": confidence_level(score),
        "method": "autonomous_llm_evidence_v1",
        "signals": {name: signals.get(name) for name in weights},
        "weights": weights,
    }
    return enriched, score
