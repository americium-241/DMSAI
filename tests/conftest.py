"""
DMSAI E2E Test Suite – Shared fixtures.

Sets up an isolated test environment with:
  • Temporary SQLite database (cleaned before each session)
  • Temporary storage / models directories
  • Merged config/local_config.yaml so node modules can import cleanly
  • Mocked LLM calls (Ollama) returning realistic deterministic responses
  • importlib-based module loading to avoid src/ namespace collisions
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Path / environment bootstrap (runs at collection time, before imports)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DOCS = PROJECT_ROOT / "example_docs"

# Shared library
_shared_path = str(PROJECT_ROOT / "shared")
if _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

# ---------------------------------------------------------------------------
# 2. Session-scoped temp directory & config
# ---------------------------------------------------------------------------

_TEST_DIR = tempfile.mkdtemp(prefix="dmsai_e2e_")
_TEST_DB = os.path.join(_TEST_DIR, "test_dmsai.db")
_TEST_STORAGE = os.path.join(_TEST_DIR, "storage")
_TEST_MODELS = os.path.join(_TEST_DIR, "models")

os.makedirs(_TEST_STORAGE, exist_ok=True)
os.makedirs(_TEST_MODELS, exist_ok=True)
os.makedirs(os.path.join(_TEST_DIR, "config"), exist_ok=True)

_CONFIG_YAML = f"""\
storage_root: "{_TEST_STORAGE.replace(os.sep, '/')}"
symlink_root: ""
vllm_settings:
  enabled: false
  api_url: "http://localhost:11434/api/chat"
  model: "gemma3:27b"
  confidence_threshold: 0.7
  prompt: "Extract all text from this image."
"""
with open(os.path.join(_TEST_DIR, "config", "local_config.yaml"), "w") as _f:
    _f.write(_CONFIG_YAML)

os.environ["DMSAI_DB_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["DMSAI_STORAGE_ROOT"] = _TEST_STORAGE
os.environ["DMSAI_MODELS_DIR"] = _TEST_MODELS

_ORIGINAL_CWD = os.getcwd()
os.chdir(_TEST_DIR)

# Force the DB engine singleton to be re-created with the test DB
import dmsai_models.connection as _conn_mod
_conn_mod._engine = None


# ---------------------------------------------------------------------------
# 3. Module loader (avoids src/ namespace collisions between nodes)
# ---------------------------------------------------------------------------

def _load_module(module_name: str, file_path: str):
    """Load a Python module from an absolute file path, registering it in sys.modules."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _node_src(node_name: str, filename: str) -> str:
    return str(PROJECT_ROOT / "nodes" / node_name / "src" / filename)


# Load all non-OCR node modules (no relative imports)
ingestion_logic = _load_module("ingestion_logic", _node_src("ingestion_node", "ingestion_logic.py"))
conversion_logic = _load_module("conversion_logic", _node_src("conversion_node", "conversion_logic.py"))
storage_logic = _load_module("storage_logic", _node_src("storage_node", "storage_logic.py"))
embedding_logic = _load_module("embedding_logic", _node_src("embedding_node", "embedding_logic.py"))
classification_logic = _load_module("classification_logic", _node_src("classification_node", "classification_logic.py"))
entity_extraction_logic = _load_module("entity_extraction_logic", _node_src("entity_extraction_node", "entity_extraction_logic.py"))
entity_resolution_logic = _load_module("entity_resolution_logic", _node_src("entity_resolution_node", "entity_resolution_logic.py"))
field_extraction_logic = _load_module("field_extraction_logic", _node_src("field_extraction_node", "field_extraction_logic.py"))

# OCR node uses relative imports (.vllm_engine) – load as a package
_ocr_node_dir = str(PROJECT_ROOT / "nodes" / "ocr_node")
if _ocr_node_dir not in sys.path:
    sys.path.insert(0, _ocr_node_dir)

_ocr_src_dir = str(PROJECT_ROOT / "nodes" / "ocr_node" / "src")
_ocr_src_spec = importlib.util.spec_from_file_location(
    "ocr_src",
    os.path.join(_ocr_src_dir, "__init__.py"),
    submodule_search_locations=[_ocr_src_dir],
)
_ocr_src_pkg = importlib.util.module_from_spec(_ocr_src_spec)
sys.modules["ocr_src"] = _ocr_src_pkg
_ocr_src_spec.loader.exec_module(_ocr_src_pkg)

_load_module("ocr_src.vllm_engine", os.path.join(_ocr_src_dir, "vllm_engine.py"))
_load_module("ocr_src.ocr_logic", os.path.join(_ocr_src_dir, "ocr_logic.py"))

ocr_logic = sys.modules.get("ocr_src.ocr_logic")


# ---------------------------------------------------------------------------
# 4. Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _setup_teardown():
    from dmsai_models import init_db
    init_db()
    yield
    os.chdir(_ORIGINAL_CWD)
    shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def example_docs() -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".pdf"}
    docs = sorted(
        p for p in EXAMPLE_DOCS.iterdir()
        if p.suffix.lower() in extensions
    )
    assert docs, f"No example documents found in {EXAMPLE_DOCS}"
    return docs


@pytest.fixture(scope="session")
def first_doc(example_docs: list[Path]) -> Path:
    return example_docs[0]


@pytest.fixture(scope="session")
def first_doc_bytes(first_doc: Path) -> bytes:
    return first_doc.read_bytes()


# ---------------------------------------------------------------------------
# 5. LLM mock responses (realistic, deterministic)
# ---------------------------------------------------------------------------

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


def make_llm_side_effect(responses: list[str]):
    """Create an async callable that cycles through given responses."""
    idx = {"i": 0}

    async def _side_effect(*args, **kwargs):
        resp = responses[idx["i"] % len(responses)]
        idx["i"] += 1
        return resp

    return _side_effect


@pytest.fixture
def mock_llm_classification():
    with patch.object(
        classification_logic, "_call_llm",
        new_callable=AsyncMock,
        return_value=MOCK_CLASSIFICATION_RESPONSE,
    ) as m:
        yield m


@pytest.fixture
def mock_llm_entity_extraction():
    with patch.object(
        entity_extraction_logic, "_call_llm",
        new_callable=AsyncMock,
        return_value=MOCK_ENTITY_EXTRACTION_RESPONSE,
    ) as m:
        yield m


@pytest.fixture
def mock_llm_entity_resolution():
    from conftest import entity_resolution_logic as erl
    with patch.object(
        erl, "_call_llm",
        new_callable=AsyncMock,
    ) as m:
        yield m


@pytest.fixture
def mock_llm_field_extraction():
    responses = [
        MOCK_FIELD_DETECT_RESPONSE,
        MOCK_CANONICAL_MAP_EXISTING,
        MOCK_CANONICAL_MAP_EXISTING,
        MOCK_CANONICAL_MAP_NEW,
        MOCK_CANONICAL_MAP_NEW,
        MOCK_CANONICAL_MAP_NEW,
        MOCK_FIELD_EXTRACT_RESPONSE,
    ]
    with patch.object(
        field_extraction_logic, "_call_llm",
        new_callable=AsyncMock,
        side_effect=make_llm_side_effect(responses),
    ) as m:
        yield m
