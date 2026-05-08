"""Shared LLM and embedding mock response constants used across node and integration tests."""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Embedding mocks
# ---------------------------------------------------------------------------

# 8-dimensional unit-normalised mock vector — small enough to be fast in tests
# but large enough to exercise the cosine similarity path.
MOCK_EMBEDDING_VECTOR: list[float] = [0.1, 0.2, 0.3, 0.4, -0.1, -0.2, -0.3, -0.4]

# A second distinct vector (orthogonal to the first on the first 4 dims)
MOCK_EMBEDDING_VECTOR_B: list[float] = [-0.4, 0.3, -0.2, 0.1, 0.4, -0.3, 0.2, -0.1]

MOCK_CLASSIFICATION_RESPONSE = json.dumps({
    "category": "invoice",
    "subcategory": None,
    "confidence": 0.92,
    "is_new": False,
    "definition": "Commercial invoice",
    "subcategory_is_new": False,
    "subcategory_definition": "",
})

MOCK_ENTITY_EXTRACTION_RESPONSE = json.dumps([
    {
        "name": "ACME Corporation",
        "entity_type": "company",
        "role": "issuer",
        "confidence": 0.91,
        "fields": {
            "address": "12 Rue de la Paix, 75002 Paris",
            "tax_id": "FR12345678901",
            "email": "contact@acme-corp.fr",
        },
    },
    {
        "name": "John Doe",
        "entity_type": "person",
        "role": "recipient",
        "confidence": 0.87,
        "fields": {
            "email": "john.doe@example.com",
        },
    },
])

MOCK_ENTITY_EXTRACTION_RESPONSE_2 = json.dumps([
    {
        "name": "ACME Corp.",
        "entity_type": "company",
        "role": "issuer",
        "confidence": 0.89,
        "fields": {
            "address": "12 Rue de la Paix, Paris",
            "tax_id": "FR12345678901",
        },
    },
    {
        "name": "Jane Smith",
        "entity_type": "person",
        "role": "recipient",
        "confidence": 0.85,
        "fields": {
            "email": "jane.smith@example.com",
        },
    },
])

MOCK_FIELD_DETECT_RESPONSE = json.dumps([
    "invoice_number",
    "date",
    "total_amount",
    "tax_amount",
    "due_date",
])

MOCK_FIELD_EXTRACT_RESPONSE = json.dumps({
    "values": {
        "invoice_number": "INV-2026-001",
        "date": "2026-04-15",
        "total_amount": "1 200,00 \u20ac",
        "tax_amount": "200,00 \u20ac",
        "due_date": "2026-05-15",
    },
    "confidences": {
        "invoice_number": 0.95,
        "date": 0.93,
        "total_amount": 0.90,
        "tax_amount": 0.88,
        "due_date": 0.85,
    },
})

MOCK_CANONICAL_MAP_EXISTING = json.dumps({"match": "total_amount"})
MOCK_CANONICAL_MAP_NEW = json.dumps({
    "new": "due_date",
    "description": "Payment due date for the document",
})

# Entity resolution LLM responses
MOCK_ENTITY_RESOLUTION_SAME = json.dumps({
    "same": True,
    "confidence": 0.92,
    "reasoning": "Same company name with a trivial legal suffix difference.",
    "canonical_name": "ACME Corporation",
})
MOCK_ENTITY_RESOLUTION_DIFFERENT = json.dumps({
    "same": False,
    "confidence": 0.91,
    "reasoning": "Different entities despite superficial name similarity.",
    "canonical_name": "",
})


def make_llm_side_effect(responses: list):
    """Create an async callable that cycles through given responses."""
    idx = {"i": 0}

    async def _side_effect(*args, **kwargs):
        resp = responses[idx["i"] % len(responses)]
        idx["i"] += 1
        return resp

    return _side_effect
