"""Unit tests for shared/dmsai_models/confidence.py."""

from __future__ import annotations

import pytest

from dmsai_models.confidence import (
    clamp01,
    confidence_level,
    weighted_average,
    evidence_grounding_score,
    completeness_score,
    compute_item_confidence,
    classification_margin,
    compute_pipeline_confidence,
)


# ---------------------------------------------------------------------------
# clamp01
# ---------------------------------------------------------------------------

class TestClamp01:
    def test_value_in_range(self):
        assert clamp01(0.5) == pytest.approx(0.5)

    def test_zero_stays_zero(self):
        assert clamp01(0.0) == pytest.approx(0.0)

    def test_one_stays_one(self):
        assert clamp01(1.0) == pytest.approx(1.0)

    def test_negative_clamped_to_zero(self):
        assert clamp01(-0.5) == pytest.approx(0.0)

    def test_greater_than_one_clamped(self):
        assert clamp01(1.5) == pytest.approx(1.0)

    def test_none_returns_default(self):
        assert clamp01(None) == pytest.approx(0.0)

    def test_none_with_custom_default(self):
        assert clamp01(None, default=0.5) == pytest.approx(0.5)

    def test_string_float_converted(self):
        assert clamp01("0.75") == pytest.approx(0.75)

    def test_invalid_string_returns_default(self):
        assert clamp01("not-a-number") == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# confidence_level
# ---------------------------------------------------------------------------

class TestConfidenceLevel:
    def test_high(self):
        # Default threshold is 0.85
        assert confidence_level(0.90) == "high"
        assert confidence_level(0.85) == "high"

    def test_medium(self):
        # Default medium threshold is 0.6
        assert confidence_level(0.70) == "medium"
        assert confidence_level(0.60) == "medium"

    def test_low(self):
        assert confidence_level(0.30) == "low"
        assert confidence_level(0.0) == "low"

    def test_none_treated_as_zero(self):
        assert confidence_level(None) == "low"


# ---------------------------------------------------------------------------
# weighted_average
# ---------------------------------------------------------------------------

class TestWeightedAverage:
    def test_equal_weights_equal_values(self):
        signals = {"a": 0.8, "b": 0.8}
        weights = {"a": 1.0, "b": 1.0}
        result = weighted_average(signals, weights)
        assert result == pytest.approx(0.8)

    def test_none_signal_excluded(self):
        signals = {"a": 1.0, "b": None}
        weights = {"a": 1.0, "b": 1.0}
        result = weighted_average(signals, weights)
        assert result == pytest.approx(1.0)

    def test_empty_signals_returns_zero(self):
        result = weighted_average({}, {"a": 1.0})
        assert result == pytest.approx(0.0)

    def test_all_none_signals_returns_zero(self):
        signals = {"a": None, "b": None}
        weights = {"a": 1.0, "b": 2.0}
        result = weighted_average(signals, weights)
        assert result == pytest.approx(0.0)

    def test_weighted_correctly(self):
        signals = {"a": 1.0, "b": 0.0}
        weights = {"a": 3.0, "b": 1.0}
        result = weighted_average(signals, weights)
        assert result == pytest.approx(0.75)

    def test_result_rounded_to_4_decimals(self):
        signals = {"a": 1.0 / 3}
        weights = {"a": 1.0}
        result = weighted_average(signals, weights)
        assert len(str(result).split(".")[1]) <= 4


# ---------------------------------------------------------------------------
# evidence_grounding_score
# ---------------------------------------------------------------------------

class TestEvidenceGroundingScore:
    def test_exact_match_returns_one(self):
        score = evidence_grounding_score("Invoice from ACME Corp", "ACME Corp")
        assert score == pytest.approx(1.0)

    def test_no_match_returns_zero(self):
        score = evidence_grounding_score("Invoice from ACME Corp", "XYZ Limited")
        assert score == pytest.approx(0.0, abs=0.3)

    def test_empty_text_with_candidate(self):
        score = evidence_grounding_score("", "ACME Corp")
        # Returns the config value for empty_text_with_evidence (default 0.35)
        assert 0.0 <= score <= 0.5

    def test_no_candidates_returns_zero(self):
        score = evidence_grounding_score("Some text", None)
        assert score == pytest.approx(0.0)

    def test_compact_match(self):
        # Compact normalization removes punctuation/spaces
        score = evidence_grounding_score(
            "Tax ID: FR12345678901", "FR 12345678901"
        )
        assert score >= 0.9  # Should match after compact normalization

    def test_partial_match_returns_intermediate(self):
        long_text = "This is a very long document text. " * 20 + "INV-2026-001"
        score = evidence_grounding_score(long_text, "INV-2026-001")
        assert score >= 0.9


# ---------------------------------------------------------------------------
# completeness_score
# ---------------------------------------------------------------------------

class TestCompletenessScore:
    def test_all_present(self):
        assert completeness_score(["a", "b", "c"]) == pytest.approx(1.0)

    def test_empty_list(self):
        assert completeness_score([]) == pytest.approx(1.0)

    def test_half_missing(self):
        score = completeness_score(["value", None])
        assert score == pytest.approx(0.5)

    def test_none_missing(self):
        assert completeness_score([None, "", []]) == pytest.approx(0.0)

    def test_null_string_counts_as_missing(self):
        score = completeness_score(["null"])
        assert score == pytest.approx(0.0)

    def test_mixed_present_absent(self):
        score = completeness_score(["name", "type", None, ""])
        assert score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# compute_item_confidence
# ---------------------------------------------------------------------------

class TestComputeItemConfidence:
    def test_returns_dict_with_required_keys(self):
        result = compute_item_confidence(
            llm_confidence=0.9,
            ocr_text="Invoice from ACME Corp total 1200 EUR",
            value="ACME Corp",
        )
        assert "score" in result
        assert "level" in result
        assert "signals" in result
        assert "reasons" in result

    def test_score_in_range(self):
        result = compute_item_confidence(
            llm_confidence=0.8,
            ocr_text="some text",
            value="some",
        )
        assert 0.0 <= result["score"] <= 1.0

    def test_evidence_found_in_ocr_reason(self):
        result = compute_item_confidence(
            llm_confidence=0.9,
            ocr_text="ACME Corporation issued this invoice",
            value="ACME Corporation",
            evidence="ACME Corporation",
        )
        assert "value_or_evidence_found_in_ocr" in result["reasons"]

    def test_no_ocr_evidence_reason(self):
        result = compute_item_confidence(
            llm_confidence=0.9,
            ocr_text="",
            value="ACME Corporation",
        )
        assert "no_direct_ocr_evidence_found" in result["reasons"]

    def test_deterministic_output(self):
        kwargs = dict(
            llm_confidence=0.85,
            ocr_text="Invoice total 500 EUR",
            ocr_confidence=0.9,
            value="500 EUR",
            required_values=["500 EUR"],
        )
        r1 = compute_item_confidence(**kwargs)
        r2 = compute_item_confidence(**kwargs)
        assert r1["score"] == r2["score"]

    def test_level_matches_score(self):
        result = compute_item_confidence(
            llm_confidence=0.95,
            ocr_text="ACME",
            value="ACME",
        )
        if result["score"] >= 0.85:
            assert result["level"] == "high"
        elif result["score"] >= 0.6:
            assert result["level"] == "medium"
        else:
            assert result["level"] == "low"


# ---------------------------------------------------------------------------
# classification_margin
# ---------------------------------------------------------------------------

class TestClassificationMargin:
    def test_single_prediction(self):
        preds = [{"confidence": 0.8}]
        assert classification_margin(preds) == pytest.approx(0.8)

    def test_two_predictions_margin(self):
        preds = [{"confidence": 0.9}, {"confidence": 0.6}]
        result = classification_margin(preds)
        assert result == pytest.approx(0.3)

    def test_empty_predictions(self):
        assert classification_margin([]) is None

    def test_margin_non_negative(self):
        preds = [{"confidence": 0.5}, {"confidence": 0.5}]
        result = classification_margin(preds)
        assert result >= 0.0


# ---------------------------------------------------------------------------
# compute_pipeline_confidence
# ---------------------------------------------------------------------------

class TestComputePipelineConfidence:
    def test_returns_tuple(self):
        step_details = {
            "ocr": {"score": 0.9},
            "classification": {"score": 0.85},
            "entity_extraction": {"score": 0.8},
            "entity_resolution": {"score": 0.75},
            "field_extraction": {"score": 0.88},
        }
        enriched, score = compute_pipeline_confidence(step_details)
        assert isinstance(enriched, dict)
        assert isinstance(score, float)

    def test_pipeline_key_in_enriched(self):
        step_details = {"ocr": {"score": 0.9}, "field_extraction": {"score": 0.8}}
        enriched, _ = compute_pipeline_confidence(step_details)
        assert "pipeline" in enriched

    def test_score_in_range(self):
        step_details = {"ocr": {"score": 0.9}, "classification": {"score": 0.85}}
        _, score = compute_pipeline_confidence(step_details)
        assert 0.0 <= score <= 1.0

    def test_all_none_scores_produce_zero(self):
        step_details = {
            "ocr": {"score": None},
            "classification": {"score": None},
        }
        _, score = compute_pipeline_confidence(step_details)
        assert score == pytest.approx(0.0)
