import os
import base64
from datetime import datetime

import yaml
from sqlmodel import select

from dmsai_models import Document, get_session, init_db, record_pipeline_event

with open("config/local_config.yaml", "r") as _f:
    _config = yaml.safe_load(_f)

STORAGE_ROOT = os.environ.get("DMSAI_STORAGE_ROOT", _config["storage_root"])
SYMLINK_ROOT = _config.get("symlink_root", "")


def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def save_to_filesystem(doc_id: str, pdf_bytes: bytes) -> str:
    """Save PDF bytes to a date-partitioned directory, return the absolute path."""
    now = datetime.utcnow()
    rel_path = os.path.join(
        str(now.year),
        f"{now.month:02d}",
        f"{doc_id}.pdf",
    )
    full_path = os.path.join(STORAGE_ROOT, rel_path)
    _ensure_dir(full_path)

    with open(full_path, "wb") as f:
        f.write(pdf_bytes)

    return os.path.normpath(full_path)


def create_symlink(doc_id: str, storage_path: str) -> str:
    """Create a date-based symbolic link pointing to the stored PDF."""
    if not SYMLINK_ROOT:
        return ""

    now = datetime.utcnow()
    link_dir = os.path.join(SYMLINK_ROOT, str(now.year), f"{now.month:02d}")
    os.makedirs(link_dir, exist_ok=True)
    link_path = os.path.join(link_dir, f"{doc_id}.pdf")

    try:
        os.symlink(storage_path, link_path)
    except OSError:
        return ""

    return os.path.normpath(link_path)


async def process_document(payload: dict) -> dict:
    """Store the unified PDF, update the central DB, strip file_bytes."""
    init_db()
    doc_id = payload["workflow_id"]
    record_pipeline_event(doc_id, "storage", "started")
    pdf_bytes = base64.b64decode(payload["file_bytes"])

    storage_path = save_to_filesystem(doc_id, pdf_bytes)
    symlink_path = create_symlink(doc_id, storage_path)

    with get_session() as session:
        doc = session.exec(select(Document).where(Document.id == doc_id)).first()
        if doc:
            doc.storage_path = storage_path
            doc.file_size_bytes = len(pdf_bytes)
            doc.status = "STORED"
            doc.updated_at = datetime.utcnow()
            session.commit()

    del payload["file_bytes"]
    payload["storage_path"] = storage_path
    if symlink_path:
        payload["symlink_path"] = symlink_path
    payload["history"] = payload.get("history", []) + ["storage_completed"]
    record_pipeline_event(doc_id, "storage", "completed")
    return payload
