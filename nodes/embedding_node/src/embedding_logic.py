from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime

import numpy as np

from dmsai_models import Document, DocumentEmbedding, get_session, init_db, record_pipeline_event

logger = logging.getLogger("embedding_node")


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


async def _compute_dense(text: str) -> np.ndarray:
    """Get dense embedding from the configured provider (Ollama or LiteLLM)."""
    from dmsai_models.llm import call_embedding
    vec = await call_embedding(text)
    return np.array(vec, dtype=np.float32)


async def process_embedding(payload: dict) -> dict:
    """Compute LLM-provider dense embeddings, store in DB, enrich payload."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "embedding", "started")
    ocr_text = payload.get("ocr_text", "")

    if not ocr_text:
        logger.warning(f"[{doc_id}] No OCR text available, skipping embedding")
        payload["history"] = payload.get("history", []) + ["embedding_skipped"]
        if doc_id:
            record_pipeline_event(doc_id, "embedding", "completed", details="skipped_no_ocr")
        return payload

    dense_vec = await _compute_dense(ocr_text)
    dense_norm = _l2_normalize(dense_vec)

    init_db()
    with get_session() as session:
        embedding = DocumentEmbedding(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            dense_vector=json.dumps(dense_norm.tolist()),
            combined_vector=json.dumps(dense_norm.tolist()),
            created_at=datetime.utcnow(),
        )
        session.add(embedding)

        doc = session.get(Document, doc_id)
        if doc:
            doc.status = "EMBEDDED"
            doc.updated_at = datetime.utcnow()
            session.add(doc)

        session.commit()

    payload["embedding_vector"] = dense_norm.tolist()
    payload["history"] = payload.get("history", []) + ["embedding_completed"]
    logger.info(f"[{doc_id}] Embedding computed via LLM provider: dense={len(dense_vec)}d")
    if doc_id:
        record_pipeline_event(doc_id, "embedding", "completed")
    return payload
