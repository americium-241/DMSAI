import logging
from datetime import datetime

from sqlmodel import select

from dmsai_models import Document, get_session, init_db, record_pipeline_event
from .vllm_engine import run_vision_llm

logger = logging.getLogger("ocr_node")


async def _embed_document(doc_id: str, ocr_text: str) -> None:
    """Compute and persist the document embedding (best-effort, never raises)."""
    try:
        from dmsai_models.embedding import (
            call_embedding,
            document_embedding_text,
            store_document_embedding,
            _refresh_embedding_config,
        )
        cfg = _refresh_embedding_config()
        model = cfg.get("embedding_model", "")
        text_to_embed = document_embedding_text(ocr_text)
        if not text_to_embed:
            return
        vec = await call_embedding(text_to_embed, stage="ocr", document_id=doc_id)
        if vec:
            store_document_embedding(doc_id, vec, model=model)
            logger.debug("[%s] Document embedding stored (dim=%d)", doc_id, len(vec))
    except Exception as exc:
        logger.debug("[%s] Document embedding skipped: %s", doc_id, exc)


async def process_document(payload: dict) -> dict:
    """OCR via Vision LLM -- sends each PDF page as an image to the configured LLM."""
    init_db()
    doc_id = payload["workflow_id"]
    record_pipeline_event(doc_id, "ocr", "started")
    storage_path = payload["storage_path"]

    with open(storage_path, "rb") as f:
        pdf_bytes = f.read()

    text = await run_vision_llm(pdf_bytes, document_id=doc_id)
    ocr_method = "vllm"
    confidence = 1.0 if text.strip() else 0.0

    logger.info(f"Vision LLM OCR result: {len(text)} chars")

    with get_session() as session:
        doc = session.exec(select(Document).where(Document.id == doc_id)).first()
        if doc:
            doc.ocr_text = text
            doc.ocr_confidence = confidence
            doc.ocr_method = ocr_method
            doc.status = "OCR_DONE"
            doc.updated_at = datetime.utcnow()
            session.commit()

    # Best-effort document embedding — runs after the DB session closes so a
    # failure here can never corrupt the document record.
    await _embed_document(doc_id, text)

    payload["ocr_text"] = text
    payload["ocr_confidence"] = confidence
    payload["ocr_method"] = ocr_method
    payload["history"] = payload.get("history", []) + ["ocr_completed"]
    record_pipeline_event(doc_id, "ocr", "completed")
    return payload
