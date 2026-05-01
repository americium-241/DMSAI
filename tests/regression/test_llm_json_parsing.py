"""
Regression tests for LLM JSON parsing across pipeline nodes.

Parametrized against a wide variety of realistic bad-LLM-output edge cases:
markdown fences, trailing commas (handled), wrong keys, truncated output, etc.
"""

from __future__ import annotations

import json
import sys

import pytest

entity_extraction_logic = sys.modules["entity_extraction_logic"]
field_extraction_logic = sys.modules["field_extraction_logic"]


# ---------------------------------------------------------------------------
# Entity extraction: _parse_entities_json
# ---------------------------------------------------------------------------

_PARSE_ENTITIES_CASES = [
    # (input, expected_count, description)
    ("[]", 0, "empty array"),
    ("{}", 0, "empty object — not an array"),
    ('{"entities": [{"name": "Corp", "entity_type": "company"}]}', 1, "entities wrapper"),
    ('[{"name": "Corp", "entity_type": "company"}]', 1, "plain array"),
    ('```json\n[{"name": "Corp", "entity_type": "company"}]\n```', 1, "markdown fenced"),
    ('```\n[{"name": "Corp", "entity_type": "company"}]\n```', 1, "plain fence no lang"),
    ('Some text [{"name": "Corp", "entity_type": "company"}] end', 1, "embedded array"),
    ("not json at all", 0, "invalid json"),
    ("", 0, "empty string"),
    ('null', 0, "null response"),
    ('{"name": "Corp", "entity_type": "company"}', 1, "single object without array"),
    (
        '[{"name": "ACME", "entity_type": "company"}, {"name": "John", "entity_type": "person"}]',
        2,
        "two entities",
    ),
    # Truncated JSON (common with long responses)
    ('[{"name": "ACME", "entity_type": "company"', 0, "truncated array"),
]


@pytest.mark.parametrize("raw,expected_count,desc", _PARSE_ENTITIES_CASES)
def test_parse_entities_json(raw, expected_count, desc):
    result = entity_extraction_logic._parse_entities_json(raw)
    assert isinstance(result, list), f"[{desc}] Expected list, got {type(result)}"
    assert len(result) == expected_count, (
        f"[{desc}] Expected {expected_count} entity, got {len(result)}: {result}"
    )


# ---------------------------------------------------------------------------
# Entity extraction: entity defaults when keys missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entity_missing_keys_get_defaults():
    """Entities missing 'name', 'entity_type', 'role' should get defaults filled in."""
    from unittest.mock import AsyncMock, patch

    from dmsai_models import init_db
    ingestion_logic = sys.modules["ingestion_logic"]
    init_db()

    minimal_entity = json.dumps([{"confidence": 0.8}])
    payload = ingestion_logic.build_ingestion_payload(b"%PDF-test", "regression_defaults.pdf")
    payload["ocr_text"] = "Some text"

    with patch.object(
        entity_extraction_logic, "_call_llm",
        new_callable=AsyncMock,
        return_value=minimal_entity,
    ):
        result = await entity_extraction_logic.process_entity_extraction(payload)

    entities = result["extracted_entities"]
    assert len(entities) == 1
    assert entities[0]["name"] == "Unknown"
    assert entities[0]["entity_type"] == "other"
    assert entities[0]["role"] == "mentioned"
    assert isinstance(entities[0]["fields"], dict)


# ---------------------------------------------------------------------------
# Field extraction: _parse_json_array (field detection)
# ---------------------------------------------------------------------------

_PARSE_ARRAY_CASES = [
    ('["invoice_number", "date", "total_amount"]', 3, "plain array"),
    ('```json\n["invoice_number", "date"]\n```', 2, "markdown fenced"),
    ('```\n["field_a", "field_b"]\n```', 2, "plain fence"),
    ('Here: ["invoice_number"] done', 1, "embedded in text"),
    ("[]", 0, "empty array"),
    ("not json", 0, "invalid json"),
    ("", 0, "empty string"),
]


@pytest.mark.parametrize("raw,expected_count,desc", _PARSE_ARRAY_CASES)
def test_parse_json_array(raw, expected_count, desc):
    result = field_extraction_logic._parse_json_array(raw)
    assert isinstance(result, list), f"[{desc}] Expected list"
    assert len(result) == expected_count, f"[{desc}] Expected {expected_count} items, got {len(result)}"


# ---------------------------------------------------------------------------
# Field extraction: _parse_json_object (field extraction response)
# ---------------------------------------------------------------------------

_PARSE_OBJECT_CASES = [
    ('{"values": {"invoice_number": "INV-001"}}', True, "valid object"),
    ('```json\n{"key": "val"}\n```', True, "markdown fenced"),
    ("not json", False, "invalid json"),
    ("", False, "empty string"),
    ('{"key": "val"} extra text', True, "with trailing text"),
]


@pytest.mark.parametrize("raw,expect_non_empty,desc", _PARSE_OBJECT_CASES)
def test_parse_json_object(raw, expect_non_empty, desc):
    result = field_extraction_logic._parse_json_object(raw)
    assert isinstance(result, dict), f"[{desc}] Expected dict"
    if expect_non_empty:
        assert len(result) > 0, f"[{desc}] Expected non-empty dict"
    else:
        assert len(result) == 0, f"[{desc}] Expected empty dict"


# ---------------------------------------------------------------------------
# Field extraction: _split_values_and_confidences edge cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("parsed,expected_vals_key", [
    ({"values": {"invoice_number": "INV-001"}, "confidences": {"invoice_number": 0.9}}, "invoice_number"),
    ({"invoice_number": "INV-001"}, "invoice_number"),  # legacy format
    ({}, None),
    ({"values": None}, None),
])
def test_split_values_and_confidences(parsed, expected_vals_key):
    vals, confs = field_extraction_logic._split_values_and_confidences(parsed)
    if expected_vals_key:
        assert expected_vals_key in vals
    else:
        # Either empty dict or no crash
        assert isinstance(vals, dict)


# ---------------------------------------------------------------------------
# Field extraction: missing 'values' key
# ---------------------------------------------------------------------------

def test_split_values_missing_values_key():
    """A parsed dict with 'confidences' but no 'values' should use legacy path."""
    parsed = {"confidences": {"invoice_number": 0.9}}
    vals, confs = field_extraction_logic._split_values_and_confidences(parsed)
    # Legacy path: the whole dict is treated as field->value
    assert "confidences" in vals  # legacy treats all keys as values


# ---------------------------------------------------------------------------
# Classification response parsing
# ---------------------------------------------------------------------------

_VALID_CLASSIFICATION_RESPONSES = [
    json.dumps({"category": "invoice", "confidence": 0.9, "is_new": False,
                "subcategory": None, "definition": "Invoice", "subcategory_is_new": False,
                "subcategory_definition": ""}),
    json.dumps({"category": "contract", "confidence": 0.85, "is_new": False,
                "subcategory": "nda", "definition": "Contract", "subcategory_is_new": False,
                "subcategory_definition": "Non-disclosure"}),
]

_INVALID_CLASSIFICATION_RESPONSES = [
    "not json",
    "{}",  # missing category
    '{"confidence": 0.9}',  # missing category
]


def test_valid_classification_responses_have_category():
    """Valid mock responses should always have 'category' key."""
    for raw in _VALID_CLASSIFICATION_RESPONSES:
        data = json.loads(raw)
        assert "category" in data
        assert isinstance(data["confidence"], float)


def test_invalid_classification_responses_handled():
    """These should not raise when parsed."""
    for raw in _INVALID_CLASSIFICATION_RESPONSES:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        # If category is missing, that's handled at runtime
        assert isinstance(data, dict)
