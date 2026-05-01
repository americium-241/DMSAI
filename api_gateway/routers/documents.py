from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlmodel import select, func, or_

from dmsai_models import (
    Document, DocumentField, DocumentEntity, Entity, EntityField,
    Bucket, BucketDocument, User, Correction, PipelineEvent,
    DocumentAuditLog, DocumentVersion,
    get_session, init_db,
)
from auth import get_current_user

LOCK_TIMEOUT_MINUTES = 30

router = APIRouter(prefix="/api", tags=["documents"])

INGESTION_NODE_URL = os.environ.get("INGESTION_NODE_URL", "http://localhost:8010")


def _verify_doc_org(doc: Document, user: User) -> None:
    """Raise 404 if the document doesn't belong to the user's organization."""
    if doc.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Document not found")


def _record_audit(session, document_id: str, user_id: Optional[str], action: str,
                  details: Optional[str] = None, entity_id: Optional[str] = None) -> None:
    session.add(DocumentAuditLog(
        id=str(uuid.uuid4()),
        document_id=document_id,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        details=details,
        created_at=datetime.utcnow(),
    ))


def _next_version_number(session, document_id: str) -> int:
    from sqlmodel import select as _sel
    existing = session.exec(
        _sel(DocumentVersion).where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
    ).first()
    return (existing.version_number + 1) if existing else 1


def _create_version_snapshot(session, doc: Document, user_id: Optional[str], summary: str) -> None:
    import json as _json
    fields = session.exec(select(DocumentField).where(DocumentField.document_id == doc.id)).all()
    links = session.exec(select(DocumentEntity).where(DocumentEntity.document_id == doc.id)).all()
    entities = []
    for link in links:
        entity = session.get(Entity, link.entity_id)
        if entity:
            entities.append({"role": link.role, "entity_id": entity.id, "name": entity.name})
    snapshot = _json.dumps({
        "filename": doc.filename,
        "status": doc.status,
        "classification_label": doc.classification_label,
        "classification_subcategory_label": doc.classification_subcategory_label,
        "pipeline_confidence": doc.pipeline_confidence,
        "fields": {f.field_name: f.field_value for f in fields},
        "entities": entities,
    })
    session.add(DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        version_number=_next_version_number(session, doc.id),
        created_by=user_id,
        created_at=datetime.utcnow(),
        summary=summary,
        snapshot_json=snapshot,
    ))


def _get_doc_or_404(session, document_id: str, user: User) -> Document:
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    _verify_doc_org(doc, user)
    return doc


def _doc_to_response(doc: Document) -> dict:
    import json as _json
    confidence_details = None
    if doc.confidence_details:
        try:
            confidence_details = _json.loads(doc.confidence_details)
        except Exception:
            confidence_details = doc.confidence_details
    return {
        "id": doc.id, "filename": doc.filename,
        "original_extension": doc.original_extension,
        "source": doc.source, "mode": doc.mode,
        "status": doc.status,
        "pdf_url": f"/api/documents/{doc.id}/pdf" if doc.storage_path else None,
        "file_size_bytes": doc.file_size_bytes,
        "page_count": doc.page_count,
        "ocr_confidence": doc.ocr_confidence, "ocr_method": doc.ocr_method,
        "classification_label": doc.classification_label,
        "classification_subcategory_label": doc.classification_subcategory_label,
        "classification_path": _json.loads(doc.classification_path) if doc.classification_path else None,
        "classification_confidence": doc.classification_confidence,
        "classification_method": doc.classification_method,
        "cluster_id": doc.cluster_id,
        "pipeline_confidence": doc.pipeline_confidence,
        "confidence_details": confidence_details,
        "created_at": str(doc.created_at),
        "updated_at": str(doc.updated_at) if doc.updated_at else None,
        "processed_at": str(doc.processed_at) if doc.processed_at else None,
        "archived_at": str(doc.archived_at) if doc.archived_at else None,
        "trashed_at": str(doc.trashed_at) if doc.trashed_at else None,
        "compressed_at": str(doc.compressed_at) if doc.compressed_at else None,
    }


def _json_or_none(raw: Optional[str]):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

@router.get("/documents", summary="List documents", description="Return a paginated list of documents in the current organization. Filter by status, classification, entity, or free-text search.")
async def list_documents(
    status: Optional[str] = None,
    mode: Optional[str] = None,
    classification: Optional[str] = None,
    entity_id: Optional[str] = None,
    search: Optional[str] = None,
    archived: Optional[str] = Query(None, description="'true' = only archived, 'false' = exclude archived"),
    trashed: Optional[str] = Query(None, description="'true' = only trashed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    init_db()
    with get_session() as session:
        query = select(Document).where(
            Document.organization_id == user.organization_id
        )
        # By default exclude archived and trashed from the normal listing
        if trashed == "true":
            query = query.where(Document.trashed_at.isnot(None))
        elif archived == "true":
            query = query.where(Document.archived_at.isnot(None), Document.trashed_at.is_(None))
        else:
            query = query.where(Document.archived_at.is_(None), Document.trashed_at.is_(None))
        if status:
            query = query.where(Document.status == status)
        if mode:
            query = query.where(Document.mode == mode)
        if classification:
            query = query.where(
                or_(
                    Document.classification_label == classification,
                    Document.classification_subcategory_label == classification,
                )
            )
        if search:
            query = query.where(Document.filename.contains(search))
        if entity_id:
            doc_ids = [de.document_id for de in session.exec(
                select(DocumentEntity).where(DocumentEntity.entity_id == entity_id)
            ).all()]
            if doc_ids:
                query = query.where(Document.id.in_(doc_ids))
            else:
                return {"total": 0, "page": page, "page_size": page_size, "documents": []}

        query = query.order_by(Document.created_at.desc())
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        docs = session.exec(query.offset((page - 1) * page_size).limit(page_size)).all()
        doc_payload = [_doc_to_response(d) for d in docs]
    return {"total": total, "page": page, "page_size": page_size, "documents": doc_payload}


@router.get("/documents/{document_id}", summary="Get document", description="Full document detail including OCR text, classification, confidence details, extracted fields, and entities. Check `status`: `PENDING` → processing, `COMPLETED` → all stages done, `FAILED` → pipeline error.")
async def get_document(document_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        result = _doc_to_response(doc)
        result["ocr_text"] = doc.ocr_text
        return result


@router.get("/documents/{document_id}/pdf", summary="Download PDF", description="Stream the normalized PDF for this document. The file is generated by the conversion node.")
async def get_document_pdf(document_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        if not doc.storage_path:
            raise HTTPException(status_code=404, detail="Document PDF not found")
        if not os.path.exists(doc.storage_path):
            raise HTTPException(status_code=404, detail="PDF file missing from storage")
        storage_path = doc.storage_path
        filename = doc.filename
    return FileResponse(storage_path, media_type="application/pdf", filename=f"{filename}.pdf")


@router.get("/documents/{document_id}/fields", summary="Get document fields", description="Return all structured fields extracted by the field extraction node, with per-field confidence scores and canonical names.")
async def get_document_fields(document_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        fields = session.exec(select(DocumentField).where(DocumentField.document_id == document_id)).all()
        return [
            {"id": f.id, "field_name": f.field_name, "field_value": f.field_value,
             "confidence": f.confidence, "confidence_details": _json_or_none(f.confidence_details),
             "extraction_method": f.extraction_method}
            for f in fields
        ]


@router.get("/documents/{document_id}/entities")
async def get_document_entities(document_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        links = session.exec(select(DocumentEntity).where(DocumentEntity.document_id == document_id)).all()
        result = []
        for link in links:
            entity = session.get(Entity, link.entity_id)
            if entity:
                efs = session.exec(select(EntityField).where(EntityField.entity_id == entity.id)).all()
                result.append({
                    "link_id": link.id,
                    "entity_id": entity.id, "name": entity.name,
                    "canonical_name": entity.canonical_name,
                    "entity_type": entity.entity_type, "role": link.role,
                    "confidence": link.confidence,
                    "confidence_details": _json_or_none(link.confidence_details),
                    "fields": {ef.field_name: ef.field_value for ef in efs},
                })
    return result


# ---------------------------------------------------------------------------
# Document editing
# ---------------------------------------------------------------------------

class FieldUpdate(BaseModel):
    field_value: Optional[str] = None
    field_name: Optional[str] = None


class FieldCreate(BaseModel):
    field_name: str
    field_value: Optional[str] = None


class DocumentUpdate(BaseModel):
    classification_label: Optional[str] = None
    classification_subcategory_label: Optional[str] = None


@router.put("/documents/{document_id}")
async def update_document(document_id: str, body: DocumentUpdate, user: User = Depends(get_current_user)):
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        if body.classification_label is not None:
            old_label = doc.classification_label
            new_label = body.classification_label
            if old_label != new_label:
                session.add(Correction(
                    id=str(uuid.uuid4()),
                    document_id=doc.id,
                    entity_id=None,
                    field_type="classification",
                    field_name=None,
                    original_value=old_label,
                    corrected_value=new_label,
                    corrected_by=user.id,
                ))
            doc.classification_label = new_label
        if body.classification_subcategory_label is not None:
            old_label = doc.classification_subcategory_label
            new_label = body.classification_subcategory_label or None
            if old_label != new_label:
                session.add(Correction(
                    id=str(uuid.uuid4()),
                    document_id=doc.id,
                    entity_id=None,
                    field_type="classification_subcategory",
                    field_name=None,
                    original_value=old_label,
                    corrected_value=new_label,
                    corrected_by=user.id,
                ))
            doc.classification_subcategory_label = new_label
            path = [p for p in [doc.classification_label, new_label] if p]
            doc.classification_path = json.dumps(path) if path else None
        doc.updated_at = datetime.utcnow()
        session.add(doc)
        _record_audit(session, document_id, user.id, "classification_edited",
                      f"{body.classification_label or ''} / {body.classification_subcategory_label or ''}")
        session.commit()
    return {"status": "updated"}


@router.put("/documents/{document_id}/fields/{field_id}")
async def update_field(document_id: str, field_id: str, body: FieldUpdate, user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        field = session.get(DocumentField, field_id)
        if not field or field.document_id != document_id:
            raise HTTPException(status_code=404, detail="Field not found")
        old_value = field.field_value
        old_name = field.field_name
        if body.field_value is not None and body.field_value != old_value:
            session.add(Correction(
                id=str(uuid.uuid4()),
                document_id=document_id,
                entity_id=None,
                field_type="document_field",
                field_name=field.field_name,
                original_value=old_value,
                corrected_value=body.field_value,
                corrected_by=user.id,
            ))
            field.field_value = body.field_value
        if body.field_name is not None and body.field_name != old_name:
            session.add(Correction(
                id=str(uuid.uuid4()),
                document_id=document_id,
                entity_id=None,
                field_type="document_field",
                field_name=old_name,
                original_value=old_name,
                corrected_value=body.field_name,
                corrected_by=user.id,
            ))
            field.field_name = body.field_name
        field.extraction_method = "manual"
        session.add(field)
        _record_audit(session, document_id, user.id, "field_edited",
                      f"{old_name}={old_value} → {field.field_name}={field.field_value}")
        session.commit()
    return {"status": "updated"}


@router.post("/documents/{document_id}/fields")
async def create_field(document_id: str, body: FieldCreate, user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        field = DocumentField(
            id=str(uuid.uuid4()), document_id=document_id,
            field_name=body.field_name, field_value=body.field_value,
            confidence=1.0, extraction_method="manual",
        )
        session.add(field)
        field_id = field.id
        field_name = field.field_name
        field_value = field.field_value
        _record_audit(session, document_id, user.id, "field_added",
                      f"{body.field_name}={body.field_value}")
        session.commit()
    return {"id": field_id, "field_name": field_name, "field_value": field_value}


@router.delete("/documents/{document_id}/fields/{field_id}")
async def delete_field(document_id: str, field_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        field = session.get(DocumentField, field_id)
        if not field or field.document_id != document_id:
            raise HTTPException(status_code=404, detail="Field not found")
        _record_audit(session, document_id, user.id, "field_deleted",
                      f"{field.field_name}={field.field_value}")
        session.delete(field)
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Entity field editing
# ---------------------------------------------------------------------------

class EntityFieldUpdate(BaseModel):
    field_value: Optional[str] = None
    field_name: Optional[str] = None


class DocumentEntityResolve(BaseModel):
    target_entity_id: str


def _entity_correction_value(entity: Optional[Entity]) -> Optional[str]:
    if not entity:
        return None
    label = entity.canonical_name or entity.name
    return f"{label} ({entity.id})"


def _verify_entity_org(session, entity_id: str, user: User) -> None:
    """Verify the entity is linked to at least one document in the user's org."""
    link = session.exec(
        select(DocumentEntity).where(DocumentEntity.entity_id == entity_id)
        .join(Document, Document.id == DocumentEntity.document_id)
        .where(Document.organization_id == user.organization_id)
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Entity not found")


@router.put("/documents/{document_id}/entities/{link_id}/resolve")
async def resolve_document_entity(
    document_id: str,
    link_id: str,
    body: DocumentEntityResolve,
    user: User = Depends(get_current_user),
):
    """Reassign one document-entity link to an existing resolved entity."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        link = session.get(DocumentEntity, link_id)
        if not link or link.document_id != document_id:
            raise HTTPException(status_code=404, detail="Document entity link not found")

        _verify_entity_org(session, body.target_entity_id, user)
        target = session.get(Entity, body.target_entity_id)
        if not target:
            raise HTTPException(status_code=404, detail="Target entity not found")

        source = session.get(Entity, link.entity_id)
        if link.entity_id == body.target_entity_id:
            return {"status": "unchanged", "link_id": link.id, "entity_id": link.entity_id}

        session.add(Correction(
            id=str(uuid.uuid4()),
            document_id=document_id,
            entity_id=body.target_entity_id,
            field_type="document_entity_resolution",
            field_name=link.role,
            original_value=_entity_correction_value(source),
            corrected_value=_entity_correction_value(target),
            corrected_by=user.id,
        ))

        existing = session.exec(
            select(DocumentEntity).where(
                DocumentEntity.document_id == document_id,
                DocumentEntity.entity_id == body.target_entity_id,
                DocumentEntity.role == link.role,
            )
        ).first()

        if existing and existing.id != link.id:
            existing.confidence = 1.0
            session.add(existing)
            session.delete(link)
            resolved_link_id = existing.id
        else:
            link.entity_id = body.target_entity_id
            link.confidence = 1.0
            session.add(link)
            resolved_link_id = link.id

        _record_audit(session, document_id, user.id, "entity_resolved",
                      f"Role {link.role}: {_entity_correction_value(source)} → {_entity_correction_value(target)}",
                      entity_id=body.target_entity_id)
        session.commit()
    return {"status": "resolved", "link_id": resolved_link_id, "entity_id": body.target_entity_id}


@router.put("/entities/{entity_id}/fields/{field_id}")
async def update_entity_field(entity_id: str, field_id: str, body: EntityFieldUpdate, user: User = Depends(get_current_user)):
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        ef = session.get(EntityField, field_id)
        if not ef or ef.entity_id != entity_id:
            raise HTTPException(status_code=404, detail="Entity field not found")
        link = session.exec(
            select(DocumentEntity)
            .join(Document, Document.id == DocumentEntity.document_id)
            .where(DocumentEntity.entity_id == entity_id)
            .where(Document.organization_id == user.organization_id)
        ).first()
        doc_id = link.document_id if link else None
        if doc_id is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        old_value = ef.field_value
        old_name = ef.field_name
        if body.field_value is not None and body.field_value != old_value:
            session.add(Correction(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                entity_id=entity_id,
                field_type="entity_field",
                field_name=ef.field_name,
                original_value=old_value,
                corrected_value=body.field_value,
                corrected_by=user.id,
            ))
            ef.field_value = body.field_value
        if body.field_name is not None and body.field_name != old_name:
            session.add(Correction(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                entity_id=entity_id,
                field_type="entity_field",
                field_name=old_name,
                original_value=old_name,
                corrected_value=body.field_name,
                corrected_by=user.id,
            ))
            ef.field_name = body.field_name
        session.add(ef)
        if doc_id:
            _record_audit(session, doc_id, user.id, "entity_field_edited",
                          f"[entity {entity_id[:8]}] {old_name}={old_value} → {ef.field_name}={ef.field_value}",
                          entity_id=entity_id)
        session.commit()
    return {"status": "updated"}


class EntityFieldCreate(BaseModel):
    field_name: str
    field_value: str


@router.post("/entities/{entity_id}/fields")
async def create_entity_field(entity_id: str, body: EntityFieldCreate, user: User = Depends(get_current_user)):
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        entity = session.get(Entity, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        link = session.exec(
            select(DocumentEntity)
            .join(Document, Document.id == DocumentEntity.document_id)
            .where(DocumentEntity.entity_id == entity_id)
            .where(Document.organization_id == user.organization_id)
        ).first()
        ef = EntityField(
            id=str(uuid.uuid4()), entity_id=entity_id,
            field_name=body.field_name, field_value=body.field_value,
            confidence=1.0, source_document_id=None,
        )
        session.add(ef)
        ef_id = ef.id
        if link:
            _record_audit(session, link.document_id, user.id, "entity_field_added",
                          f"[entity {entity_id[:8]}] {body.field_name}={body.field_value}",
                          entity_id=entity_id)
        session.commit()
    return {"id": ef_id, "field_name": body.field_name, "field_value": body.field_value}


@router.delete("/entities/{entity_id}/fields/{field_id}")
async def delete_entity_field(entity_id: str, field_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _verify_entity_org(session, entity_id, user)
        ef = session.get(EntityField, field_id)
        if not ef or ef.entity_id != entity_id:
            raise HTTPException(status_code=404, detail="Entity field not found")
        link = session.exec(
            select(DocumentEntity)
            .join(Document, Document.id == DocumentEntity.document_id)
            .where(DocumentEntity.entity_id == entity_id)
            .where(Document.organization_id == user.organization_id)
        ).first()
        if link:
            _record_audit(session, link.document_id, user.id, "entity_field_deleted",
                          f"[entity {entity_id[:8]}] {ef.field_name}={ef.field_value}",
                          entity_id=entity_id)
        session.delete(ef)
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Auto-lock / toggle state  (works across all buckets the doc belongs to)
# ---------------------------------------------------------------------------

@router.post("/documents/{document_id}/auto-lock")
async def auto_lock_document(document_id: str, user: User = Depends(get_current_user)):
    """Lock the document in every bucket it belongs to (for the current user)."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bds = session.exec(
            select(BucketDocument).where(BucketDocument.document_id == document_id)
        ).all()
        locked = 0
        for bd in bds:
            if bd.workflow_state == "closed":
                continue
            stale = bd.locked_at and (datetime.utcnow() - bd.locked_at > timedelta(minutes=LOCK_TIMEOUT_MINUTES))
            if bd.locked_by and bd.locked_by != user.id and not stale:
                continue
            bd.workflow_state = "locked"
            bd.locked_by = user.id
            bd.locked_at = datetime.utcnow()
            session.add(bd)
            locked += 1
        session.commit()
    return {"status": "locked", "locked_count": locked}


@router.post("/documents/{document_id}/auto-unlock")
async def auto_unlock_document(document_id: str, user: User = Depends(get_current_user)):
    """Unlock the document in every bucket where the current user holds the lock."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bds = session.exec(
            select(BucketDocument).where(BucketDocument.document_id == document_id)
        ).all()
        unlocked = 0
        for bd in bds:
            if bd.workflow_state == "locked" and bd.locked_by == user.id:
                bd.workflow_state = "open"
                bd.locked_by = None
                bd.locked_at = None
                session.add(bd)
                unlocked += 1
        session.commit()
    return {"status": "unlocked", "unlocked_count": unlocked}


@router.post("/documents/{document_id}/toggle-state")
async def toggle_document_state(document_id: str, user: User = Depends(get_current_user)):
    """Toggle between closed and open across all buckets."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bds = session.exec(
            select(BucketDocument).where(BucketDocument.document_id == document_id)
        ).all()
        new_state = None
        for bd in bds:
            if new_state is None:
                new_state = "open" if bd.workflow_state == "closed" else "closed"
            bd.workflow_state = new_state
            bd.locked_by = None
            bd.locked_at = None
            session.add(bd)
        session.commit()
    return {"status": "toggled", "new_state": new_state or "open"}


def _pipeline_event_to_dict(ev: PipelineEvent) -> dict:
    return {
        "id": ev.id,
        "document_id": ev.document_id,
        "stage": ev.stage,
        "event_type": ev.event_type,
        "timestamp": str(ev.timestamp),
        "details": ev.details,
    }


@router.get("/documents/{document_id}/events/stream")
async def stream_document_events(document_id: str, user: User = Depends(get_current_user)):
    """SSE stream of new pipeline events until the document reaches COMPLETED or the client disconnects."""
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)

    async def event_gen():
        seen_ids: set[str] = set()
        try:
            while True:
                done_pipeline = False
                with get_session() as session:
                    doc = session.get(Document, document_id)
                    if not doc:
                        yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                        break
                    done_pipeline = doc.status == "COMPLETED"
                    rows = session.exec(
                        select(PipelineEvent)
                        .where(PipelineEvent.document_id == document_id)
                        .order_by(PipelineEvent.timestamp)
                    ).all()
                for ev in rows:
                    if ev.id not in seen_ids:
                        seen_ids.add(ev.id)
                        yield f"data: {json.dumps(_pipeline_event_to_dict(ev))}\n\n"
                if done_pipeline:
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    break
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/documents/{document_id}/events")
async def list_document_events(document_id: str, user: User = Depends(get_current_user)):
    """All pipeline events for a document (REST fallback / initial load)."""
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        rows = session.exec(
            select(PipelineEvent)
            .where(PipelineEvent.document_id == document_id)
            .order_by(PipelineEvent.timestamp)
        ).all()
    return {"events": [_pipeline_event_to_dict(ev) for ev in rows]}


@router.get("/documents/{document_id}/workflow-state")
async def get_workflow_state(document_id: str, user: User = Depends(get_current_user)):
    """Get the current workflow state of a doc (from the first bucket it belongs to)."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bd = session.exec(
            select(BucketDocument).where(BucketDocument.document_id == document_id)
        ).first()
        if not bd:
            return {"workflow_state": None, "locked_by": None}
        locker_name = None
        if bd.locked_by:
            locker = session.get(User, bd.locked_by)
            locker_name = locker.full_name if locker else None
        return {
            "workflow_state": bd.workflow_state,
            "locked_by": bd.locked_by,
            "locked_by_name": locker_name,
        }


# ---------------------------------------------------------------------------
# Document ↔ Bucket management
# ---------------------------------------------------------------------------

class BucketAssign(BaseModel):
    bucket_id: str


@router.get("/documents/{document_id}/buckets")
async def get_document_buckets(document_id: str, user: User = Depends(get_current_user)):
    """List all buckets this document belongs to, with workflow state."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bds = session.exec(
            select(BucketDocument).where(BucketDocument.document_id == document_id)
        ).all()
        result = []
        for bd in bds:
            bucket = session.get(Bucket, bd.bucket_id)
            if not bucket or bucket.organization_id != user.organization_id:
                continue
            result.append({
                "bucket_document_id": bd.id,
                "bucket_id": bd.bucket_id,
                "bucket_name": bucket.name,
                "workflow_state": bd.workflow_state,
                "locked_by": bd.locked_by,
                "created_at": str(bd.created_at),
            })
    return result


@router.post("/documents/{document_id}/buckets")
async def add_document_to_bucket(
    document_id: str,
    body: BucketAssign,
    user: User = Depends(get_current_user),
):
    """Manually assign this document to a bucket."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bucket = session.get(Bucket, body.bucket_id)
        if not bucket or bucket.organization_id != user.organization_id:
            raise HTTPException(status_code=404, detail="Bucket not found")
        existing = session.exec(
            select(BucketDocument).where(
                BucketDocument.bucket_id == body.bucket_id,
                BucketDocument.document_id == document_id,
            )
        ).first()
        if existing:
            return {
                "bucket_document_id": existing.id,
                "bucket_id": existing.bucket_id,
                "bucket_name": bucket.name,
                "workflow_state": existing.workflow_state,
                "status": "already_assigned",
            }
        bd = BucketDocument(
            id=str(uuid.uuid4()),
            bucket_id=body.bucket_id,
            document_id=document_id,
            workflow_state="open",
            created_at=datetime.utcnow(),
        )
        session.add(bd)
        bd_id = bd.id
        session.commit()
    return {
        "bucket_document_id": bd_id,
        "bucket_id": body.bucket_id,
        "bucket_name": bucket.name,
        "workflow_state": "open",
        "status": "assigned",
    }


@router.delete("/documents/{document_id}/buckets/{bucket_document_id}")
async def remove_document_from_bucket(
    document_id: str,
    bucket_document_id: str,
    user: User = Depends(get_current_user),
):
    """Remove this document from a bucket."""
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        bd = session.get(BucketDocument, bucket_document_id)
        if not bd or bd.document_id != document_id:
            raise HTTPException(status_code=404, detail="Bucket assignment not found")
        bucket = session.get(Bucket, bd.bucket_id)
        if not bucket or bucket.organization_id != user.organization_id:
            raise HTTPException(status_code=404, detail="Bucket not found")
        session.delete(bd)
        session.commit()
    return {"status": "removed"}


# ---------------------------------------------------------------------------
# Document relations (shared-entity neighbours)
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}/related")
async def get_related_documents(
    document_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """
    Return documents that share at least one entity with this document,
    ranked by the number of shared entities (descending).
    """
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)

        # All entity_ids linked to this document
        my_links = session.exec(
            select(DocumentEntity).where(DocumentEntity.document_id == document_id)
        ).all()
        my_entity_ids = {lnk.entity_id for lnk in my_links}

        if not my_entity_ids:
            return {"document_id": document_id, "related": []}

        # Find other document_ids that share at least one of these entities
        other_links = session.exec(
            select(DocumentEntity).where(
                DocumentEntity.entity_id.in_(my_entity_ids),
                DocumentEntity.document_id != document_id,
            )
        ).all()

        # Group by document_id and count shared entities
        from collections import defaultdict
        shared: dict[str, set] = defaultdict(set)
        for lnk in other_links:
            shared[lnk.document_id].add(lnk.entity_id)

        if not shared:
            return {"document_id": document_id, "related": []}

        # Sort by shared entity count descending
        ranked = sorted(shared.items(), key=lambda x: len(x[1]), reverse=True)[:limit]

        # Filter to org documents only and enrich
        result = []
        for other_doc_id, shared_entity_ids in ranked:
            doc = session.get(Document, other_doc_id)
            if not doc or doc.organization_id != user.organization_id:
                continue
            # Entity details for shared entities
            entities = []
            for eid in shared_entity_ids:
                ent = session.get(Entity, eid)
                if ent:
                    entities.append({
                        "entity_id": ent.id,
                        "name": ent.canonical_name or ent.name,
                        "entity_type": ent.entity_type,
                    })
            result.append({
                "document_id": doc.id,
                "filename": doc.filename,
                "classification_label": doc.classification_label,
                "classification_subcategory_label": doc.classification_subcategory_label,
                "status": doc.status,
                "created_at": str(doc.created_at),
                "shared_entity_count": len(shared_entity_ids),
                "shared_entities": entities,
            })

    return {"document_id": document_id, "related": result}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

@router.post("/upload", summary="Upload document", description="Upload a file (PDF, JPG, PNG, TIFF…). The document is queued for the full pipeline: conversion → storage → OCR → entity extraction → classification → entity resolution → field extraction. Returns the document ID immediately; poll `GET /api/documents/{id}` until `status == COMPLETED`.")
async def upload_document(
    file: UploadFile = File(...),
    priority: int = Form(0),
    mode: str = Form("auto"),
    user: User = Depends(get_current_user),
):
    async with httpx.AsyncClient(timeout=60.0) as client:
        file_content = await file.read()
        resp = await client.post(
            f"{INGESTION_NODE_URL}/upload",
            files={"file": (file.filename, file_content, file.content_type)},
            data={"priority": str(priority), "mode": mode},
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        result = resp.json()

    doc_id = result.get("document_id")
    if doc_id:
        with get_session() as session:
            doc = session.get(Document, doc_id)
            if doc:
                doc.organization_id = user.organization_id
                session.add(doc)
                session.commit()

    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search", summary="Full-text search", description="Search across OCR text, classification labels, field values, and entity names.")
async def search_documents(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    init_db()
    term = f"%{q}%"
    results = []
    seen_doc_ids = set()

    with get_session() as session:
        org_docs = select(Document.id).where(
            Document.organization_id == user.organization_id
        )
        org_doc_ids = set(session.exec(org_docs).all())

        for doc in session.exec(
            select(Document).where(
                Document.id.in_(org_doc_ids),
                or_(
                    Document.filename.contains(q),
                    Document.classification_label.contains(q),
                    Document.classification_subcategory_label.contains(q),
                    Document.ocr_text.contains(q),
                )
            ).limit(100)
        ).all():
            if doc.id not in seen_doc_ids:
                seen_doc_ids.add(doc.id)
                if q.lower() in (doc.filename or "").lower():
                    match_field = "filename"
                elif q.lower() in (doc.classification_label or "").lower():
                    match_field = "classification_label"
                elif q.lower() in (doc.classification_subcategory_label or "").lower():
                    match_field = "classification_subcategory_label"
                else:
                    match_field = "ocr_text"
                results.append({
                    "document_id": doc.id, "filename": doc.filename,
                    "match_type": match_field, "match_value": doc.filename,
                    "classification_label": doc.classification_label,
                    "classification_subcategory_label": doc.classification_subcategory_label,
                    "status": doc.status,
                })

        for df in session.exec(
            select(DocumentField).where(
                DocumentField.document_id.in_(org_doc_ids),
                or_(DocumentField.field_name.contains(q), DocumentField.field_value.contains(q)),
            ).limit(100)
        ).all():
            if df.document_id not in seen_doc_ids:
                seen_doc_ids.add(df.document_id)
                doc = session.get(Document, df.document_id)
                results.append({
                    "document_id": df.document_id,
                    "filename": doc.filename if doc else None,
                    "match_type": f"field:{df.field_name}",
                    "match_value": df.field_value,
                    "classification_label": doc.classification_label if doc else None,
                    "classification_subcategory_label": doc.classification_subcategory_label if doc else None,
                    "status": doc.status if doc else None,
                })

        for entity in session.exec(
            select(Entity).where(Entity.name.contains(q)).limit(50)
        ).all():
            links = session.exec(
                select(DocumentEntity).where(
                    DocumentEntity.entity_id == entity.id,
                    DocumentEntity.document_id.in_(org_doc_ids),
                )
            ).all()
            for lnk in links:
                if lnk.document_id not in seen_doc_ids:
                    seen_doc_ids.add(lnk.document_id)
                    doc = session.get(Document, lnk.document_id)
                    results.append({
                        "document_id": lnk.document_id,
                        "filename": doc.filename if doc else None,
                        "match_type": f"entity:{entity.name}",
                        "match_value": entity.name,
                        "classification_label": doc.classification_label if doc else None,
                        "classification_subcategory_label": doc.classification_subcategory_label if doc else None,
                        "status": doc.status if doc else None,
                    })

    total = len(results)
    start = (page - 1) * page_size
    paged = results[start:start + page_size]
    return {"total": total, "page": page, "page_size": page_size, "results": paged}
