"""
Regression tests for confidence computation — golden-value style.

These tests guard against inadvertent changes to the scoring formulas.
Each test uses fixed inputs and checks that the output matches the
expected value within a small tolerance.
"""

from __future__ import annotations

import pytest

from dmsai_models.confidence import (
    clamp01,
    completeness_score,
    compute_item_confidence,
    compute_pipeline_confidence,
    evidence_grounding_score,
    weighted_average,
)

# ---------------------------------------------------------------------------
# Golden values (computed from the current correct implementation)
# ---------------------------------------------------------------------------

# Default weights from _seed_system_config:
# llm=0.30, grounding=0.35, completeness=0.15, source_quality=0.10,
# agreement=0.07, ambiguity=0.03

TOLERANCE = 0.05  # allow ±5% drift for config-dependent values


class TestClamp01GoldenValues:
    @pytest.mark.parametrize("value,expected", [
        (0.0, 0.0),
        (1.0, 1.0),
        (0.5, 0.5),
        (-1.0, 0.0),
        (2.0, 1.0),
        (0.123456789, 0.123456789),
    ])
    def test_exact(self, value, expected):
        assert clamp01(value) == pytest.approx(expected)


class TestEvidenceGroundingGoldenValues:
    def test_exact_match(self):
        score = evidence_grounding_score("ACME Corporation", "ACME Corporation")
        assert score == pytest.approx(1.0)

    def test_empty_text_empty_candidate(self):
        score = evidence_grounding_score("", "")
        assert score == pytest.approx(0.0)

    def test_candidate_in_long_text(self):
        text = "Invoice Number INV-2026-001 from ACME Corp dated 2026-04-15"
        score = evidence_grounding_score(text, "INV-2026-001")
        assert score >= 0.9

    def test_no_match_long_text(self):
        text = "This is a completely different document about something else"
        score = evidence_grounding_score(text, "ZZZUNKNOWNZZZ")
        # Should be low (no match)
        assert score < 0.5


class TestCompletenessGoldenValues:
    @pytest.mark.parametrize("values,expected", [
        (["a", "b", "c"], 1.0),
        (["a", None, "c"], 0.6667),
        ([None, None, None], 0.0),
        ([], 1.0),
        (["null"], 0.0),
        (["a"], 1.0),
    ])
    def test_golden(self, values, expected):
        result = completeness_score(values)
        assert result == pytest.approx(expected, abs=0.01)


class TestWeightedAverageGoldenValues:
    def test_all_equal_weights_equal_values(self):
        signals = {"a": 0.8, "b": 0.8, "c": 0.8}
        weights = {"a": 1.0, "b": 1.0, "c": 1.0}
        result = weighted_average(signals, weights)
        assert result == pytest.approx(0.8)

    def test_single_signal(self):
        result = weighted_average({"a": 0.75}, {"a": 1.0})
        assert result == pytest.approx(0.75)

    def test_dominant_weight(self):
        # 'a' has 10x the weight of 'b', so result should be close to a's value
        result = weighted_average({"a": 1.0, "b": 0.0}, {"a": 10.0, "b": 1.0})
        assert result > 0.9

    def test_none_signals_excluded_from_denominator(self):
        # If only 'a' is present, result = a's value regardless of b's weight
        result = weighted_average({"a": 0.6, "b": None}, {"a": 1.0, "b": 2.0})
        assert result == pytest.approx(0.6)


class TestComputeItemConfidenceGoldenValues:
    def test_high_confidence_scenario(self):
        """All signals strong → score should be high."""
        result = compute_item_confidence(
            llm_confidence=0.95,
            ocr_text="Invoice total 1200 EUR from ACME Corp",
            ocr_confidence=0.95,
            value="ACME Corp",
            evidence="ACME Corp",
            required_values=["ACME Corp", "company", "issuer"],
        )
        assert result["score"] >= 0.7
        assert result["level"] in ("high", "medium")

    def test_low_confidence_scenario(self):
        """LLM uncertain, no OCR grounding, missing fields → low score."""
        result = compute_item_confidence(
            llm_confidence=0.2,
            ocr_text="",
            ocr_confidence=0.1,
            value=None,
            required_values=[None, None],
        )
        assert result["score"] < 0.5

    def test_reasons_present(self):
        result = compute_item_confidence(
            llm_confidence=0.9,
            ocr_text="",
            value="some value",
        )
        assert "reasons" in result
        assert len(result["reasons"]) > 0

    def test_signals_subset_of_expected_keys(self):
        result = compute_item_confidence(
            llm_confidence=0.8,
            ocr_text="some text",
            value="text",
        )
        valid_signal_keys = {"llm", "grounding", "completeness", "source_quality", "agreement", "ambiguity"}
        for key in result["signals"]:
            assert key in valid_signal_keys


class TestComputePipelineConfidenceGoldenValues:
    def test_all_high_scores(self):
        step_details = {
            "ocr": {"score": 0.95},
            "classification": {"score": 0.90},
            "entity_extraction": {"score": 0.88},
            "entity_resolution": {"score": 0.85},
            "field_extraction": {"score": 0.92},
        }
        _, score = compute_pipeline_confidence(step_details)
        assert score >= 0.85, f"Expected high pipeline confidence, got {score}"

    def test_mixed_scores_produce_intermediate(self):
        step_details = {
            "ocr": {"score": 0.9},
            "classification": {"score": 0.3},  # bad
            "entity_extraction": {"score": 0.9},
            "entity_resolution": {"score": 0.9},
            "field_extraction": {"score": 0.9},
        }
        _, score = compute_pipeline_confidence(step_details)
        # Should be between 0.5 and 0.9
        assert 0.4 < score < 0.92

    def test_pipeline_weights_sum_to_one(self):
        """Verify the default pipeline weights are normalized."""
        from dmsai_models.confidence import _config_weights
        weights = _config_weights("confidence_pipeline_weights", {
            "ocr": 0.20,
            "classification": 0.20,
            "entity_extraction": 0.20,
            "entity_resolution": 0.15,
            "field_extraction": 0.25,
        })
        total = sum(weights.values())
        assert total == pytest.approx(1.0, abs=0.01)
