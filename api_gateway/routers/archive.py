"""Archive, trash, versioning, and audit log for documents."""
from __future__ import annotations

import gzip
import json
import os
import shutil
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select

from dmsai_models import (
    Document, DocumentField, DocumentEntity, Entity,
    DocumentAuditLog, DocumentVersion, DocumentComment, EntityComment,
    DocumentClassLabel, PipelineEvent, DocumentEmbedding,
    Correction, BucketDocument, User, SystemConfig, Organization,
    get_session, init_db,
    resolve_storage_path, to_relative_storage_path,
)
from auth import get_current_user

router = APIRouter(prefix="/api", tags=["archive"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_doc_or_404(session, document_id: str, user: User) -> Document:
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _record_audit(session, document_id: str, user_id: Optional[str], action: str, details: Optional[str] = None) -> None:
    session.add(DocumentAuditLog(
        id=str(uuid.uuid4()),
        document_id=document_id,
        user_id=user_id,
        action=action,
        details=details,
        created_at=datetime.utcnow(),
    ))


def _get_config(session, key: str, default: str = "") -> str:
    cfg = session.exec(select(SystemConfig).where(SystemConfig.key == key)).first()
    return cfg.value if cfg else default


def _snapshot_document(session, doc: Document) -> str:
    """Build a JSON snapshot of a document's current state."""
    fields = session.exec(select(DocumentField).where(DocumentField.document_id == doc.id)).all()
    links = session.exec(select(DocumentEntity).where(DocumentEntity.document_id == doc.id)).all()
    entities = []
    for link in links:
        entity = session.get(Entity, link.entity_id)
        if entity:
            entities.append({"role": link.role, "entity_id": entity.id, "name": entity.name})
    return json.dumps({
        "filename": doc.filename,
        "status": doc.status,
        "classification_label": doc.classification_label,
        "classification_subcategory_label": doc.classification_subcategory_label,
        "classification_path": doc.classification_path,
        "pipeline_confidence": doc.pipeline_confidence,
        "fields": {f.field_name: f.field_value for f in fields},
        "entities": entities,
    })


def _next_version_number(session, document_id: str) -> int:
    existing = session.exec(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
    ).first()
    return (existing.version_number + 1) if existing else 1


def _create_version(session, doc: Document, user_id: Optional[str], summary: str) -> str:
    version_id = str(uuid.uuid4())
    session.add(DocumentVersion(
        id=version_id,
        document_id=doc.id,
        version_number=_next_version_number(session, doc.id),
        created_by=user_id,
        created_at=datetime.utcnow(),
        summary=summary,
        snapshot_json=_snapshot_document(session, doc),
    ))
    return version_id


# ---------------------------------------------------------------------------
# Archive / Unarchive
# ---------------------------------------------------------------------------

@router.post("/documents/{document_id}/archive")
async def archive_document(document_id: str, user: User = Depends(get_current_user)):
    init_db()
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        if doc.trashed_at:
            raise HTTPException(status_code=400, detail="Document is in trash – restore it before archiving")
        if doc.archived_at:
            return {"status": "already_archived", "archived_at": str(doc.archived_at)}
        _create_version(session, doc, user.id, "Archived")
        doc.archived_at = datetime.utcnow()
        session.add(doc)
        _record_audit(session, document_id, user.id, "archived")
        session.commit()
        archived_at_str = str(doc.archived_at)
    return {"status": "archived", "archived_at": archived_at_str}


@router.post("/documents/{document_id}/unarchive")
async def unarchive_document(document_id: str, user: User = Depends(get_current_user)):
    init_db()
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        if not doc.archived_at:
            return {"status": "not_archived"}
        doc.archived_at = None
        session.add(doc)
        _record_audit(session, document_id, user.id, "unarchived")
        session.commit()
    return {"status": "unarchived"}


# ---------------------------------------------------------------------------
# Trash / Restore
# ---------------------------------------------------------------------------

@router.post("/documents/{document_id}/trash")
async def trash_document(document_id: str, user: User = Depends(get_current_user)):
    init_db()
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        if doc.trashed_at:
            return {"status": "already_trashed", "trashed_at": str(doc.trashed_at)}
        _create_version(session, doc, user.id, "Moved to trash")
        doc.trashed_at = datetime.utcnow()
        doc.archived_at = None
        session.add(doc)
        _record_audit(session, document_id, user.id, "trashed")
        session.commit()
        trashed_at_str = str(doc.trashed_at)
    return {"status": "trashed", "trashed_at": trashed_at_str}


@router.post("/documents/{document_id}/restore")
async def restore_document(document_id: str, user: User = Depends(get_current_user)):
    init_db()
    with get_session() as session:
        doc = _get_doc_or_404(session, document_id, user)
        if not doc.trashed_at:
            return {"status": "not_trashed"}
        doc.trashed_at = None
        session.add(doc)
        _record_audit(session, document_id, user.id, "restored_from_trash")
        session.commit()
    return {"status": "restored"}


# ---------------------------------------------------------------------------
# Permanent delete (admin only)
# ---------------------------------------------------------------------------

@router.delete("/documents/{document_id}/permanent")
async def permanent_delete_document(document_id: str, user: User = Depends(get_current_user)):
    init_db()
    if user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Only admins may permanently delete documents")
    with get_session() as session:
        doc = session.get(Document, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.organization_id != user.organization_id:
            raise HTTPException(status_code=404, detail="Document not found")
        if not doc.trashed_at:
            raise HTTPException(status_code=400, detail="Document must be in trash before permanent deletion")

        # Delete physical file (resolve relative DB path to absolute)
        storage_path = resolve_storage_path(doc.storage_path)
        if storage_path:
            for suffix in ("", ".gz"):
                path = storage_path + suffix
                if os.path.isfile(path):
                    os.remove(path)

        # Cascade-delete every table that has a FK on document.id.  With
        # PRAGMA foreign_keys=ON (SQLite) and Postgres' default behaviour,
        # any orphan would block the final DELETE; missing one of these is
        # silent on legacy SQLite but a hard failure now.
        for field in session.exec(select(DocumentField).where(DocumentField.document_id == document_id)).all():
            session.delete(field)
        for link in session.exec(select(DocumentEntity).where(DocumentEntity.document_id == document_id)).all():
            session.delete(link)
        for bd in session.exec(select(BucketDocument).where(BucketDocument.document_id == document_id)).all():
            session.delete(bd)
        for c in session.exec(select(Correction).where(Correction.document_id == document_id)).all():
            session.delete(c)
        for cm in session.exec(select(DocumentComment).where(DocumentComment.document_id == document_id)).all():
            session.delete(cm)
        for al in session.exec(select(DocumentAuditLog).where(DocumentAuditLog.document_id == document_id)).all():
            session.delete(al)
        for dv in session.exec(select(DocumentVersion).where(DocumentVersion.document_id == document_id)).all():
            session.delete(dv)
        for dcl in session.exec(select(DocumentClassLabel).where(DocumentClassLabel.document_id == document_id)).all():
            session.delete(dcl)
        for pe in session.exec(select(PipelineEvent).where(PipelineEvent.document_id == document_id)).all():
            session.delete(pe)
        for de in session.exec(select(DocumentEmbedding).where(DocumentEmbedding.document_id == document_id)).all():
            session.delete(de)

        session.flush()  # surface any remaining FK violations before final delete
        session.delete(doc)
        session.commit()
    return {"status": "permanently_deleted"}


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}/versions")
async def list_document_versions(document_id: str, user: User = Depends(get_current_user)):
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        versions = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        ).all()
        user_ids = {v.created_by for v in versions if v.created_by}
        users = {u.id: u for u in session.exec(select(User).where(User.id.in_(user_ids))).all()}
        return [
            {
                "id": v.id,
                "version_number": v.version_number,
                "created_by": v.created_by,
                "author_name": users[v.created_by].full_name if v.created_by and v.created_by in users else None,
                "created_at": str(v.created_at),
                "summary": v.summary,
            }
            for v in versions
        ]


@router.get("/documents/{document_id}/versions/{version_id}")
async def get_document_version(document_id: str, version_id: str, user: User = Depends(get_current_user)):
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        version = session.get(DocumentVersion, version_id)
        if not version or version.document_id != document_id:
            raise HTTPException(status_code=404, detail="Version not found")
        author = session.get(User, version.created_by) if version.created_by else None
        return {
            "id": version.id,
            "version_number": version.version_number,
            "created_by": version.created_by,
            "author_name": author.full_name if author else None,
            "created_at": str(version.created_at),
            "summary": version.summary,
            "snapshot": json.loads(version.snapshot_json) if version.snapshot_json else None,
        }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}/audit-log")
async def get_document_audit_log(
    document_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    init_db()
    with get_session() as session:
        _get_doc_or_404(session, document_id, user)
        entries = session.exec(
            select(DocumentAuditLog)
            .where(DocumentAuditLog.document_id == document_id)
            .order_by(DocumentAuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        user_ids = {e.user_id for e in entries if e.user_id}
        users = {u.id: u for u in session.exec(select(User).where(User.id.in_(user_ids))).all()}
        return [
            {
                "id": e.id,
                "action": e.action,
                "user_id": e.user_id,
                "author_name": users[e.user_id].full_name if e.user_id and e.user_id in users else None,
                "entity_id": e.entity_id,
                "details": e.details,
                "created_at": str(e.created_at),
            }
            for e in entries
        ]


# ---------------------------------------------------------------------------
# Admin: list archived / trashed + storage compaction
# ---------------------------------------------------------------------------

@router.get("/admin/archive")
async def list_archived_documents(
    status: str = Query("archived", enum=["archived", "trashed"]),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, le=100),
    user: User = Depends(get_current_user),
):
    init_db()
    if user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")
    with get_session() as session:
        base_q = (
            select(Document)
            .where(Document.organization_id == user.organization_id)
            .where(Document.trashed_at.isnot(None) if status == "trashed" else Document.archived_at.isnot(None))
        )
        if status == "trashed":
            base_q = base_q.where(Document.trashed_at.isnot(None))
        else:
            base_q = base_q.where(Document.archived_at.isnot(None), Document.trashed_at.is_(None))
        total = len(session.exec(base_q).all())
        docs = session.exec(base_q.order_by(Document.archived_at.desc() if status == "archived" else Document.trashed_at.desc())
                            .offset((page - 1) * page_size).limit(page_size)).all()
        return {
            "total": total,
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "status": d.status,
                    "classification_label": d.classification_label,
                    "archived_at": str(d.archived_at) if d.archived_at else None,
                    "trashed_at": str(d.trashed_at) if d.trashed_at else None,
                    "compressed_at": str(d.compressed_at) if d.compressed_at else None,
                    "created_at": str(d.created_at),
                }
                for d in docs
            ],
        }


@router.post("/admin/storage/compact")
async def compact_storage(user: User = Depends(get_current_user)):
    """Compress archived PDFs whose retention period has elapsed."""
    init_db()
    if user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")
    compressed = []
    already_done = []
    skipped = []
    with get_session() as session:
        org = session.get(Organization, user.organization_id)
        global_retention = int(_get_config(session, "archive_retention_days", "90"))
        retention_days = org.archive_retention_days if (org and org.archive_retention_days is not None) else global_retention
        enabled = _get_config(session, "archive_compression_enabled", "true").lower() == "true"
        if not enabled or retention_days <= 0:
            return {"status": "disabled", "compressed": [], "already_done": [], "skipped": [],
                    "retention_days": retention_days, "cutoff": None}

        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        archived_docs = session.exec(
            select(Document)
            .where(Document.organization_id == user.organization_id)
            .where(Document.archived_at.isnot(None))
            .where(Document.archived_at <= cutoff)
            .where(Document.compressed_at.is_(None))
            .where(Document.trashed_at.is_(None))
        ).all()

        for doc in archived_docs:
            path = resolve_storage_path(doc.storage_path)
            if not path or not os.path.isfile(path):
                skipped.append(doc.id)
                continue
            if path.endswith(".gz"):
                already_done.append(doc.id)
                continue
            gz_abs_path = path + ".gz"
            try:
                with open(path, "rb") as f_in, gzip.open(gz_abs_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                os.remove(path)
                # Store the compressed path as relative too
                doc.storage_path = to_relative_storage_path(gz_abs_path)
                doc.compressed_at = datetime.utcnow()
                session.add(doc)
                _record_audit(session, doc.id, user.id, "compressed",
                              f"Compressed after {retention_days}d retention ({os.path.getsize(gz_path)} bytes)")
                compressed.append(doc.id)
            except Exception as exc:
                skipped.append(doc.id)
                continue

        session.commit()

    return {
        "status": "ok",
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "compressed": compressed,
        "already_done": already_done,
        "skipped": skipped,
    }


@router.post("/admin/storage/purge-trash")
async def purge_old_trash(user: User = Depends(get_current_user)):
    """List documents in trash older than retention_days for admin review."""
    init_db()
    if user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")
    with get_session() as session:
        org = session.get(Organization, user.organization_id)
        global_trash_days = int(_get_config(session, "trash_retention_days", "30"))
        trash_days = org.trash_retention_days if (org and org.trash_retention_days is not None) else global_trash_days
        if trash_days <= 0:
            return {"status": "disabled", "trash_retention_days": trash_days, "cutoff": None, "candidates": []}
        cutoff = datetime.utcnow() - timedelta(days=trash_days)
        old_trash = session.exec(
            select(Document)
            .where(Document.organization_id == user.organization_id)
            .where(Document.trashed_at.isnot(None))
            .where(Document.trashed_at <= cutoff)
        ).all()
        return {
            "status": "ok",
            "trash_retention_days": trash_days,
            "cutoff": cutoff.isoformat(),
            "candidates": [
                {"id": d.id, "filename": d.filename, "trashed_at": str(d.trashed_at)}
                for d in old_trash
            ],
        }


# ---------------------------------------------------------------------------
# Retention settings (per-org overrides)
# ---------------------------------------------------------------------------

class RetentionUpdate(BaseModel):
    archive_retention_days: Optional[int] = None
    trash_retention_days: Optional[int] = None


@router.get("/admin/archive/retention")
async def get_retention_settings(user: User = Depends(get_current_user)):
    """Return effective retention settings for the current organisation.

    Returns both the global defaults (from SystemConfig) and any org-level
    overrides.  The ``effective_*`` fields show what the system will actually
    use.
    """
    if user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")
    init_db()
    with get_session() as session:
        org = session.get(Organization, user.organization_id)
        global_archive = int(_get_config(session, "archive_retention_days", "90"))
        global_trash = int(_get_config(session, "trash_retention_days", "30"))
        org_archive = org.archive_retention_days if org else None
        org_trash = org.trash_retention_days if org else None
        return {
            "global_archive_retention_days": global_archive,
            "global_trash_retention_days": global_trash,
            "org_archive_retention_days": org_archive,
            "org_trash_retention_days": org_trash,
            "effective_archive_retention_days": org_archive if org_archive is not None else global_archive,
            "effective_trash_retention_days": org_trash if org_trash is not None else global_trash,
        }


@router.patch("/admin/archive/retention")
async def update_retention_settings(body: RetentionUpdate, user: User = Depends(get_current_user)):
    """Update the per-org retention overrides for the current organisation.

    Pass ``null`` / omit a field to revert to the global default.
    Values must be positive integers or 0 (0 = disabled).
    """
    if user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin only")
    if body.archive_retention_days is not None and body.archive_retention_days < 0:
        raise HTTPException(status_code=400, detail="archive_retention_days must be >= 0")
    if body.trash_retention_days is not None and body.trash_retention_days < 0:
        raise HTTPException(status_code=400, detail="trash_retention_days must be >= 0")
    init_db()
    with get_session() as session:
        org = session.get(Organization, user.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        org.archive_retention_days = body.archive_retention_days
        org.trash_retention_days = body.trash_retention_days
        session.add(org)
        session.commit()
        session.refresh(org)
        global_archive = int(_get_config(session, "archive_retention_days", "90"))
        global_trash = int(_get_config(session, "trash_retention_days", "30"))
        return {
            "status": "updated",
            "org_archive_retention_days": org.archive_retention_days,
            "org_trash_retention_days": org.trash_retention_days,
            "effective_archive_retention_days": org.archive_retention_days if org.archive_retention_days is not None else global_archive,
            "effective_trash_retention_days": org.trash_retention_days if org.trash_retention_days is not None else global_trash,
        }
