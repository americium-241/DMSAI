from __future__ import annotations

import os
import uuid
import base64
from datetime import datetime
from typing import Optional

from dmsai_models import Document, get_session, init_db, record_pipeline_event


SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".pdf",
}

def validate_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return ext


def build_ingestion_payload(
    file_bytes: bytes,
    filename: str,
    source: str = "api",
    mode: str = "auto",
    organization_id: Optional[str] = None,
) -> dict:
    """Create a standardised pipeline payload from raw file bytes."""
    ext = validate_extension(filename)
    doc_id = str(uuid.uuid4())
    mode = "auto"

    init_db()
    with get_session() as session:
        doc = Document(
            id=doc_id,
            filename=filename,
            original_extension=ext,
            source=source,
            mode=mode,
            file_size_bytes=len(file_bytes),
            status="INGESTED",
            organization_id=organization_id,
            created_at=datetime.utcnow(),
        )
        session.add(doc)
        session.commit()

    payload = {
        "workflow_id": doc_id,
        "filename": filename,
        "original_extension": ext,
        "file_bytes": base64.b64encode(file_bytes).decode(),
        "source": source,
        "mode": mode,
        "priority": 0,
        "history": [],
    }
    if organization_id:
        payload["organization_id"] = organization_id
    return payload


async def process_document(payload: dict) -> dict:
    """Pipeline process_func called by NodeBlueprint workers."""
    doc_id = payload.get("workflow_id")
    if doc_id:
        record_pipeline_event(doc_id, "ingestion", "started")
    payload["history"] = payload.get("history", []) + ["ingestion_completed"]
    if doc_id:
        record_pipeline_event(doc_id, "ingestion", "completed")
    return payload
