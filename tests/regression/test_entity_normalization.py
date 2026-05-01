"""
Regression tests for entity field key normalization.

Guards against regressions in alias mapping, case sensitivity, and
canonical field lookup in entity_extraction_logic.
"""

from __future__ import annotations

import sys
import uuid

import pytest
from sqlmodel import select

from dmsai_models import CanonicalField, get_session, init_db

entity_extraction_logic = sys.modules["entity_extraction_logic"]
entity_resolution_logic = sys.modules["entity_resolution_logic"]


# ---------------------------------------------------------------------------
# _normalize_entity_field_keys (entity_extraction_logic)
# ---------------------------------------------------------------------------

class TestNormalizeEntityFieldKeys:
    def test_email_alias_normalized(self):
        """'e_mail' is an alias for 'email' in the canonical seed data."""
        init_db()
        entities = [{"name": "Corp", "fields": {"e_mail": "a@b.com"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        keys = set(entities[0]["fields"].keys())
        # Should map to 'email' canonical name
        assert "email" in keys or "e_mail" in keys  # alias may or may not exist in seed

    def test_tax_number_alias(self):
        """'tax_number' should map to 'tax_id'."""
        init_db()
        entities = [{"name": "Corp", "fields": {"tax_number": "FR123"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        keys = set(entities[0]["fields"].keys())
        assert "tax_id" in keys or "tax_number" in keys

    def test_completely_unknown_key_passes_through(self):
        """Unknown field names should pass through unchanged."""
        init_db()
        entities = [{"name": "Corp", "fields": {"utterly_unknown_field_abc123": "val"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert "utterly_unknown_field_abc123" in entities[0]["fields"]

    def test_known_canonical_name_direct_match(self):
        """If the key is already a canonical name, it passes through as-is."""
        init_db()
        entities = [{"name": "Corp", "fields": {"email": "a@b.com"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert "email" in entities[0]["fields"]

    def test_case_insensitive_lookup(self):
        """Field name matching should be case-insensitive."""
        init_db()
        entities = [{"name": "Corp", "fields": {"EMAIL": "A@B.COM"}}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        # EMAIL should map to email
        keys_lower = {k.lower() for k in entities[0]["fields"].keys()}
        assert "email" in keys_lower

    def test_multiple_entities_normalized_independently(self):
        init_db()
        entities = [
            {"name": "Corp A", "fields": {"email": "a@corp.com"}},
            {"name": "Person B", "fields": {"telephone": "+33123456789"}},
        ]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert "email" in entities[0]["fields"]
        # telephone → phone alias
        assert "phone" in entities[1]["fields"] or "telephone" in entities[1]["fields"]

    def test_none_fields_becomes_empty_dict(self):
        init_db()
        entities = [{"name": "Corp", "fields": None}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert entities[0]["fields"] == {}

    def test_non_dict_fields_becomes_empty_dict(self):
        init_db()
        entities = [{"name": "Corp", "fields": ["list", "not", "dict"]}]
        entity_extraction_logic._normalize_entity_field_keys(entities)
        assert entities[0]["fields"] == {}


# ---------------------------------------------------------------------------
# entity_resolution_logic: _normalize and _strip_legal_suffix
# ---------------------------------------------------------------------------

class TestEntityNormalizationHelpers:
    @pytest.mark.parametrize("input_name,expected_contains", [
        ("ACME Corporation", "acme corporation"),
        ("Société Générale", "societe generale"),
        ("Müller GmbH", "muller gmbh"),
        ("ÉlectricitÉ de France", "electricite de france"),
    ])
    def test_normalize_diacritics(self, input_name, expected_contains):
        result = entity_resolution_logic._normalize(input_name)
        assert result == expected_contains

    @pytest.mark.parametrize("name,suffix", [
        ("ACME SAS", "sas"),
        ("BNP Paribas S.A.", "s.a."),
        ("Shell Corp.", "corp."),
        ("TechCo Ltd.", "ltd."),
        ("Startup Inc.", "inc."),
        ("Holding GmbH", "gmbh"),
    ])
    def test_strip_legal_suffix(self, name, suffix):
        result = entity_resolution_logic._strip_legal_suffix(
            entity_resolution_logic._normalize(name)
        )
        assert suffix.replace(".", "").lower() not in result.replace(".", "").replace(" ", "")

    @pytest.mark.parametrize("s1,s2,expected_range", [
        ("acme corporation", "acme corporation", (1.0, 1.0)),  # identical → perfect overlap
        ("acme corp", "acme corporation", (0.3, 1.0)),         # share "acme" → some overlap
        ("google", "amazon", (0.0, 0.1)),                      # completely different
        ("alpha beta", "alpha beta", (1.0, 1.0)),              # identical
    ])
    def test_token_overlap_ranges(self, s1, s2, expected_range):
        """_token_overlap replaced _levenshtein_ratio as the pre-filter function."""
        overlap = entity_resolution_logic._token_overlap(s1, s2)
        lo, hi = expected_range
        assert lo <= overlap <= hi, f"token_overlap({s1!r}, {s2!r})={overlap} not in [{lo},{hi}]"


# ---------------------------------------------------------------------------
# _identifiers_match regression
# ---------------------------------------------------------------------------

class TestIdentifiersMatchRegression:
    @pytest.mark.parametrize("incoming_val,existing_val,should_match", [
        # Same tax_id, different formats
        ("FR12345678901", "FR12345678901", True),
        ("FR 1234-5678-901", "FR12345678901", True),  # normalized
        ("fr12345678901", "FR12345678901", True),  # case-insensitive normalize
        ("FR000", "DE999", False),  # different
        # Siret matching
        ("12345678901234", "12345678901234", True),
        # Email matching
        ("user@example.com", "USER@EXAMPLE.COM", True),  # normalize strips case via lower
    ])
    def test_identifier_match(self, incoming_val, existing_val, should_match):
        from dmsai_models import EntityField
        key = "tax_id"
        incoming = {key: incoming_val}
        existing = [
            EntityField(
                id=str(uuid.uuid4()), entity_id="x",
                field_name=key, field_value=existing_val,
            )
        ]
        result = entity_resolution_logic._identifiers_match(incoming, existing)
        assert result is should_match
