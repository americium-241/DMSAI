"""Unified embedding caller that dispatches to Ollama or LiteLLM.

Mirrors the structure of dmsai_models/llm.py so both providers are
configured from the same SystemConfig table.

Usage
-----
    from dmsai_models.embedding import call_embedding, cosine_similarity

    vec = await call_embedding("ACME Corporation – company, tax_id FR123")
    # vec is list[float] | None  (None when disabled or on error)

Embedding is **disabled by default** (embedding_enabled = "false").
Enable it in the admin UI or by setting embedding_enabled = "true" in
SystemConfig.  The pipeline gracefully degrades when embedding is off or
when the model server is unreachable — no exception is ever raised.

Provider config keys (all in SystemConfig, category = "embedding"):
  embedding_enabled     "true" | "false"   (default "false")
  embedding_provider    "ollama" | "litellm"  (defaults to llm_provider)
  embedding_model       e.g. "nomic-embed-text" (Ollama) or
                        "text-embedding-3-small" (LiteLLM/OpenAI)

Ollama endpoint:   POST {ollama_base_url}/api/embed
                   body: {"model": "...", "input": "..."}
                   resp: {"embeddings": [[float, ...]]}

LiteLLM endpoint:  POST {litellm_base_url}/embeddings
                   body: {"model": "...", "input": "..."}
                   resp: {"data": [{"embedding": [float, ...]}]}
"""
from __future__ import annotations

import json
import logging
import math
import time
import uuid
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger("dmsai_embedding")

_config_cache: dict[str, str] = {}
_cache_ts: float = 0.0
_CACHE_TTL = 30.0


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _refresh_embedding_config() -> dict[str, str]:
    """Load LLM + embedding settings from SystemConfig (shared TTL cache)."""
    global _config_cache, _cache_ts
    now = time.time()
    if _config_cache and (now - _cache_ts) < _CACHE_TTL:
        return _config_cache
    try:
        from .connection import get_engine
        from .models import SystemConfig
        from sqlmodel import Session, select
        with Session(get_engine()) as session:
            rows = session.exec(
                select(SystemConfig).where(
                    SystemConfig.category.in_(["llm", "embedding"])
                )
            ).all()
            _config_cache = {r.key: r.value for r in rows}
            _cache_ts = now
    except Exception as exc:
        logger.warning("Failed to load embedding config from DB: %s", exc)
        if not _config_cache:
            _config_cache = {
                "embedding_enabled": "false",
                "llm_provider": "ollama",
                "ollama_base_url": "http://localhost:11434",
                "embedding_model": "nomic-embed-text",
                "litellm_base_url": "",
                "litellm_api_key": "",
            }
    return _config_cache


def _embedding_model(cfg: dict[str, str]) -> str:
    return cfg.get("embedding_model") or "nomic-embed-text"


def _embedding_provider(cfg: dict[str, str]) -> str:
    """Prefer explicit embedding_provider; fall back to llm_provider."""
    return cfg.get("embedding_provider") or cfg.get("llm_provider", "ollama")


# ---------------------------------------------------------------------------
# Public embedding API
# ---------------------------------------------------------------------------

async def call_embedding(
    text: str,
    stage: str = "unknown",
    document_id: Optional[str] = None,
    timeout: float = 60.0,
) -> list[float] | None:
    """
    Embed *text* using the configured provider.

    Returns
    -------
    list[float]
        The embedding vector on success.
    None
        When embedding is disabled, the model is not configured, or any
        network / parsing error occurs.  The caller must handle None
        gracefully — the pipeline must never fail because of embeddings.
    """
    cfg = _refresh_embedding_config()
    if cfg.get("embedding_enabled", "false").lower() != "true":
        return None

    provider = _embedding_provider(cfg)
    try:
        if provider == "litellm":
            vec = await _embed_litellm(text, cfg, timeout)
        else:
            vec = await _embed_ollama(text, cfg, timeout)
        if vec:
            logger.debug(
                "Embedded %d chars → dim=%d  stage=%s  provider=%s",
                len(text), len(vec), stage, provider,
            )
        return vec
    except Exception as exc:
        logger.warning("Embedding call failed (non-critical, stage=%s): %s", stage, exc)
        return None


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

async def _embed_ollama(
    text: str, cfg: dict[str, str], timeout: float
) -> list[float] | None:
    base_url = cfg.get("ollama_base_url", "http://localhost:11434").rstrip("/")
    model = _embedding_model(cfg)
    url = f"{base_url}/api/embed"
    body = {"model": model, "input": text}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
    embeddings = data.get("embeddings")
    if embeddings and isinstance(embeddings, list) and embeddings[0]:
        return [float(x) for x in embeddings[0]]
    return None


async def _embed_litellm(
    text: str, cfg: dict[str, str], timeout: float
) -> list[float] | None:
    base_url = cfg.get("litellm_base_url", "").rstrip("/")
    if not base_url:
        raise RuntimeError("litellm_base_url is not configured")
    model = _embedding_model(cfg)
    if not model:
        raise RuntimeError("embedding_model is not configured")
    api_key = cfg.get("litellm_api_key", "")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model, "input": text}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/embeddings", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data")
    if items and isinstance(items, list) and items[0].get("embedding"):
        return [float(x) for x in items[0]["embedding"]]
    return None


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity — pure Python, no numpy dependency."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------

def document_embedding_text(ocr_text: str, max_chars: int = 2000) -> str:
    """Build the text fed to the embedding model for a full document.

    We use the first *max_chars* characters of the OCR text.  This is
    intentionally short: most embedding models cap at 512 tokens (~2 000 chars)
    and the semantic gist of a document is usually in its opening section.
    """
    return ocr_text[:max_chars].strip()


def entity_embedding_text(entity_data: dict) -> str:
    """Build a compact semantic string for an entity.

    Format:
        {type}: {name}
        fields: {k1}={v1}, {k2}={v2}, ...
    """
    etype = entity_data.get("entity_type", "other")
    name = entity_data.get("name", "")
    parts = [f"{etype}: {name}"]
    fields = entity_data.get("fields") or {}
    if fields:
        fstr = ", ".join(
            f"{k}={v}" for k, v in fields.items()
            if v and str(v).strip()
        )
        if fstr:
            parts.append(f"fields: {fstr}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# DB storage helpers  (synchronous — call from async code without await)
# ---------------------------------------------------------------------------

def store_document_embedding(
    document_id: str,
    vector: list[float],
    model: str = "",
) -> None:
    """Persist a document-level embedding.  Silently absorbs all errors."""
    try:
        from .connection import get_engine
        from .models import DocumentEmbedding
        from sqlmodel import Session, select
        with Session(get_engine()) as session:
            existing = session.exec(
                select(DocumentEmbedding)
                .where(DocumentEmbedding.document_id == document_id)
                .where(DocumentEmbedding.model == model)
            ).first()
            if existing:
                existing.vector = json.dumps(vector)
                existing.updated_at = datetime.utcnow()
                session.add(existing)
            else:
                session.add(DocumentEmbedding(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    model=model,
                    vector=json.dumps(vector),
                ))
            session.commit()
    except Exception as exc:
        logger.debug("Failed to store document embedding (non-critical): %s", exc)


def store_entity_embedding(
    entity_id: str,
    vector: list[float],
    model: str = "",
) -> None:
    """Persist an entity-level embedding.  Silently absorbs all errors."""
    try:
        from .connection import get_engine
        from .models import EntityEmbedding
        from sqlmodel import Session, select
        with Session(get_engine()) as session:
            existing = session.exec(
                select(EntityEmbedding)
                .where(EntityEmbedding.entity_id == entity_id)
                .where(EntityEmbedding.model == model)
            ).first()
            if existing:
                existing.vector = json.dumps(vector)
                existing.updated_at = datetime.utcnow()
                session.add(existing)
            else:
                session.add(EntityEmbedding(
                    id=str(uuid.uuid4()),
                    entity_id=entity_id,
                    model=model,
                    vector=json.dumps(vector),
                ))
            session.commit()
    except Exception as exc:
        logger.debug("Failed to store entity embedding (non-critical): %s", exc)


def load_entity_embeddings(
    entity_ids: list[str],
    model: str = "",
) -> dict[str, list[float]]:
    """Return {entity_id: vector} for all entities that have an embedding.

    Silently returns an empty dict on any error.
    """
    if not entity_ids:
        return {}
    try:
        from .connection import get_engine
        from .models import EntityEmbedding
        from sqlmodel import Session, select
        with Session(get_engine()) as session:
            rows = session.exec(
                select(EntityEmbedding)
                .where(EntityEmbedding.entity_id.in_(entity_ids))
                .where(EntityEmbedding.model == model)
            ).all()
            result: dict[str, list[float]] = {}
            for row in rows:
                try:
                    result[row.entity_id] = json.loads(row.vector)
                except Exception:
                    pass
            return result
    except Exception as exc:
        logger.debug("Failed to load entity embeddings (non-critical): %s", exc)
        return {}
