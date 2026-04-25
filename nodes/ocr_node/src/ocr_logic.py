import logging
from datetime import datetime

from sqlmodel import select

from dmsai_models import Document, get_session, init_db, record_pipeline_event
from .vllm_engine import run_vision_llm

logger = logging.getLogger("ocr_node")


async def process_document(payload: dict) -> dict:
    """OCR via Vision LLM -- sends each PDF page as an image to the configured LLM."""
    init_db()
    doc_id = payload["workflow_id"]
    record_pipeline_event(doc_id, "ocr", "started")
    storage_path = payload["storage_path"]

    with open(storage_path, "rb") as f:
        pdf_bytes = f.read()

    text = await run_vision_llm(pdf_bytes)
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

    payload["ocr_text"] = text
    payload["ocr_confidence"] = confidence
    payload["ocr_method"] = ocr_method
    payload["history"] = payload.get("history", []) + ["ocr_completed"]
    record_pipeline_event(doc_id, "ocr", "completed")
    return payload
