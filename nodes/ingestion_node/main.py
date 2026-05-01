import asyncio
import base64
import json
import os
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import UploadFile, File, HTTPException, Form
from pydantic import BaseModel
from sqlmodel import Session, select

from decentraflow import NodeBlueprint
from decentraflow.models import Task
from src.ingestion_logic import (
    process_document,
    build_ingestion_payload,
    validate_extension,
)
from src.directory_watcher import DirectoryWatcher
from src.email_watcher import EmailWatcher
from dmsai_models import init_db


init_db()

node = NodeBlueprint(
    node_name="ingestion_node",
    process_func=process_document,
    config_dir="config",
    log_dir="logs",
)

app = node.app
logger = node.logger

_node_port = int(os.environ.get("INGESTION_NODE_PORT", 8010))

watcher = DirectoryWatcher(
    config_path="config/local_config.yaml",
    node_port=_node_port,
)

email_watcher = EmailWatcher(node_port=_node_port)

_original_lifespan = node.lifespan


@asynccontextmanager
async def extended_lifespan(application):
    watcher_task = asyncio.create_task(watcher.run())
    email_task = asyncio.create_task(email_watcher.run())
    async with _original_lifespan(application):
        yield
    watcher_task.cancel()
    email_task.cancel()
    for t in (watcher_task, email_task):
        try:
            await t
        except asyncio.CancelledError:
            pass

app.router.lifespan_context = extended_lifespan


# -- Custom upload endpoints ------------------------------------------------

class Base64UploadRequest(BaseModel):
    file_bytes: str
    filename: str
    priority: Optional[int] = 0
    mode: Optional[str] = "auto"


@app.post("/upload/base64")
async def upload_base64(request: Base64UploadRequest):
    """Accept a base64-encoded document and queue it for processing."""
    try:
        validate_extension(request.filename)
        raw_bytes = base64.b64decode(request.file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 encoding")

    payload = build_ingestion_payload(
        raw_bytes, request.filename, source="api", mode=request.mode or "auto",
    )
    payload["priority"] = request.priority or 0

    with Session(node.engine) as session:
        if not session.exec(select(Task).where(Task.id == payload["workflow_id"])).first():
            session.add(Task(
                id=payload["workflow_id"],
                payload=json.dumps(payload),
                priority=payload["priority"],
            ))
            session.commit()

    logger.info(f"Base64 upload queued: {request.filename} -> {payload['workflow_id']} (mode={payload['mode']})")
    return {"status": "Accepted", "document_id": payload["workflow_id"], "mode": payload["mode"]}


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    priority: int = Form(0),
    mode: str = Form("auto"),
):
    """Accept a multipart file upload and queue it for processing."""
    filename = file.filename or "unknown"
    try:
        validate_extension(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    payload = build_ingestion_payload(raw_bytes, filename, source="api", mode=mode)
    payload["priority"] = priority

    with Session(node.engine) as session:
        if not session.exec(select(Task).where(Task.id == payload["workflow_id"])).first():
            session.add(Task(
                id=payload["workflow_id"],
                payload=json.dumps(payload),
                priority=payload["priority"],
            ))
            session.commit()

    logger.info(f"File upload queued: {filename} -> {payload['workflow_id']} (mode={payload['mode']})")
    return {"status": "Accepted", "document_id": payload["workflow_id"], "mode": payload["mode"]}


# To run: uvicorn main:app --port 8010
