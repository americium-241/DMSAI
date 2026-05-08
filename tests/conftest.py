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

# Test fixtures package
_fixtures_path = str(Path(__file__).resolve().parent)
if _fixtures_path not in sys.path:
    sys.path.insert(0, _fixtures_path)

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
classification_logic = _load_module("classification_logic", _node_src("classification_node", "classification_logic.py"))
entity_extraction_logic = _load_module("entity_extraction_logic", _node_src("entity_extraction_node", "entity_extraction_logic.py"))
entity_resolution_logic = _load_module("entity_resolution_logic", _node_src("entity_resolution_node", "entity_resolution_logic.py"))
field_extraction_logic = _load_module("field_extraction_logic", _node_src("field_extraction_node", "field_extraction_logic.py"))

# Ensure dmsai_models.embedding is importable (it's a shared module)
import dmsai_models.embedding as _embedding_mod  # noqa: F401 — registers the module

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
    # Populate example_docs with synthetic fixtures so all tests can run
    from fixtures.create_test_docs import ensure_example_docs
    ensure_example_docs(EXAMPLE_DOCS)
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

# Re-export from the fixtures module so tests can import from conftest OR
# directly from fixtures.mock_responses (avoids conftest shadowing issues).
from fixtures.mock_responses import (  # noqa: E402
    MOCK_CLASSIFICATION_RESPONSE,
    MOCK_ENTITY_EXTRACTION_RESPONSE,
    MOCK_ENTITY_EXTRACTION_RESPONSE_2,
    MOCK_FIELD_DETECT_RESPONSE,
    MOCK_FIELD_EXTRACT_RESPONSE,
    MOCK_CANONICAL_MAP_EXISTING,
    MOCK_CANONICAL_MAP_NEW,
    MOCK_ENTITY_RESOLUTION_SAME,
    MOCK_ENTITY_RESOLUTION_DIFFERENT,
    MOCK_EMBEDDING_VECTOR,
    make_llm_side_effect,
)


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
    """Mock the resolution LLM to always say entities are different (safe default).

    Use return_value=MOCK_ENTITY_RESOLUTION_SAME in specific tests that need a merge.
    """
    with patch.object(
        entity_resolution_logic, "_call_llm",
        new_callable=AsyncMock,
        return_value=MOCK_ENTITY_RESOLUTION_DIFFERENT,
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


# ---------------------------------------------------------------------------
# 6. Embedding mock — autouse so no existing test needs changes
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_embedding_disabled():
    """Ensure call_embedding always returns None in tests unless overridden.

    Embedding is disabled by default (embedding_enabled = "false") so this
    fixture is a safety net: even if a test runs against a DB that has
    embedding_enabled = "true", no real HTTP call is made.

    Tests that specifically exercise embedding behaviour should override by
    patching dmsai_models.embedding.call_embedding with a non-None return.
    """
    import dmsai_models.embedding as _emb
    with patch.object(_emb, "call_embedding", new_callable=AsyncMock, return_value=None):
        yield
