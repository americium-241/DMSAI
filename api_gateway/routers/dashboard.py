from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import select, func

from dmsai_models import (
    Document, DocumentEntity, Entity, Bucket, BucketDocument,
    User, PipelineEvent, DocumentAuditLog,
    get_session, init_db,
)
from auth import get_current_user

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
async def get_dashboard(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    user: User = Depends(get_current_user),
):
    init_db()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    dt_from: Optional[datetime] = None
    dt_to: Optional[datetime] = None
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            pass

    with get_session() as session:
        org_filter = Document.organization_id == user.organization_id
        base_filters = [org_filter]
        if dt_from:
            base_filters.append(Document.created_at >= dt_from)
        if dt_to:
            base_filters.append(Document.created_at <= dt_to)

        # — Core counts -------------------------------------------------------
        total_docs = session.exec(
            select(func.count()).select_from(Document).where(*base_filters)
        ).one()
        processing_docs = session.exec(
            select(func.count()).select_from(Document).where(
                *base_filters, Document.status != "COMPLETED"
            )
        ).one()
        today_docs = session.exec(
            select(func.count()).select_from(Document).where(
                org_filter, Document.created_at >= today_start
            )
        ).one()
        week_docs = session.exec(
            select(func.count()).select_from(Document).where(
                org_filter, Document.created_at >= week_start
            )
        ).one()

        # — Bucket workflow counts --------------------------------------------
        all_bucket_ids = session.exec(
            select(Bucket.id).where(Bucket.organization_id == user.organization_id)
        ).all()
        closed_docs = pending_docs = my_locked_docs = 0
        if all_bucket_ids:
            closed_docs = session.exec(
                select(func.count()).select_from(BucketDocument).where(
                    BucketDocument.bucket_id.in_(all_bucket_ids),
                    BucketDocument.workflow_state == "closed",
                )
            ).one()
            pending_docs = session.exec(
                select(func.count()).select_from(BucketDocument).where(
                    BucketDocument.bucket_id.in_(all_bucket_ids),
                    BucketDocument.workflow_state == "pending",
                )
            ).one()
            my_locked_docs = session.exec(
                select(func.count()).select_from(BucketDocument).where(
                    BucketDocument.bucket_id.in_(all_bucket_ids),
                    BucketDocument.workflow_state == "locked",
                    BucketDocument.locked_by == user.id,
                )
            ).one()

        # — Daily ingestion trend (last 30 days) ------------------------------
        thirty_days_ago = today_start - timedelta(days=29)
        daily_rows = session.exec(
            select(
                func.strftime("%Y-%m-%d", Document.created_at),
                func.count(),
            )
            .where(
                org_filter,
                Document.created_at >= thirty_days_ago,
            )
            .group_by(func.strftime("%Y-%m-%d", Document.created_at))
            .order_by(func.strftime("%Y-%m-%d", Document.created_at))
        ).all()
        daily_map = {row[0]: row[1] for row in daily_rows}
        daily_counts = [
            {
                "date": (thirty_days_ago + timedelta(days=i)).strftime("%Y-%m-%d"),
                "count": daily_map.get(
                    (thirty_days_ago + timedelta(days=i)).strftime("%Y-%m-%d"), 0
                ),
            }
            for i in range(30)
        ]

        # — Status breakdown --------------------------------------------------
        completed = session.exec(
            select(func.count()).select_from(Document).where(
                *base_filters, Document.status == "COMPLETED"
            )
        ).one()
        failed = session.exec(
            select(func.count()).select_from(Document).where(
                *base_filters, Document.status == "FAILED"
            )
        ).one()
        status_breakdown = {
            "completed": completed,
            "processing": max(0, processing_docs - failed),
            "failed": failed,
        }

        # — Confidence buckets ------------------------------------------------
        conf_docs = session.exec(
            select(Document.pipeline_confidence).where(
                *base_filters, Document.pipeline_confidence.isnot(None)
            )
        ).all()
        conf_buckets = {"low": 0, "medium": 0, "good": 0, "high": 0}
        for c in conf_docs:
            v = float(c)
            if v < 0.5:
                conf_buckets["low"] += 1
            elif v < 0.7:
                conf_buckets["medium"] += 1
            elif v < 0.85:
                conf_buckets["good"] += 1
            else:
                conf_buckets["high"] += 1

        # — Top 5 classifications ---------------------------------------------
        class_rows = session.exec(
            select(Document.classification_label, func.count())
            .where(*base_filters, Document.classification_label.isnot(None))
            .group_by(Document.classification_label)
            .order_by(func.count().desc())
            .limit(5)
        ).all()
        top_classifications = [{"label": r[0], "count": r[1]} for r in class_rows]

        # — Top 5 entities by document count ----------------------------------
        entity_count_rows = session.exec(
            select(DocumentEntity.entity_id, func.count(DocumentEntity.document_id))
            .join(Document, Document.id == DocumentEntity.document_id)
            .where(Document.organization_id == user.organization_id)
            .group_by(DocumentEntity.entity_id)
            .order_by(func.count(DocumentEntity.document_id).desc())
            .limit(5)
        ).all()
        top_entities = []
        for eid, cnt in entity_count_rows:
            e = session.get(Entity, eid)
            if e:
                top_entities.append(
                    {"id": eid, "name": e.name, "entity_type": e.entity_type, "doc_count": cnt}
                )

        # — Bucket summaries --------------------------------------------------
        buckets = session.exec(
            select(Bucket).where(Bucket.organization_id == user.organization_id)
        ).all()
        bucket_summaries = []
        for b in buckets:
            states: dict[str, int] = {}
            for st in ("open", "pending", "locked", "closed"):
                states[st] = session.exec(
                    select(func.count()).select_from(BucketDocument).where(
                        BucketDocument.bucket_id == b.id,
                        BucketDocument.workflow_state == st,
                    )
                ).one()
            bucket_summaries.append(
                {"id": b.id, "name": b.name, "states": states, "total": sum(states.values())}
            )

        # — Recent audit entries (org-wide) -----------------------------------
        audit_rows = session.exec(
            select(DocumentAuditLog, Document.filename)
            .join(Document, Document.id == DocumentAuditLog.document_id)
            .where(Document.organization_id == user.organization_id)
            .order_by(DocumentAuditLog.created_at.desc())
            .limit(10)
        ).all()
        recent_audit = []
        for row in audit_rows:
            entry, filename = row[0], row[1]
            # Resolve user name
            actor = None
            if entry.user_id:
                u = session.get(User, entry.user_id)
                actor = u.full_name if u else entry.user_id
            recent_audit.append({
                "id": entry.id,
                "document_id": entry.document_id,
                "filename": filename,
                "action": entry.action,
                "details": entry.details,
                "actor": actor,
                "created_at": str(entry.created_at),
            })

        # — Recent documents --------------------------------------------------
        recent_docs = session.exec(
            select(Document)
            .where(Document.organization_id == user.organization_id)
            .order_by(Document.created_at.desc())
            .limit(8)
        ).all()
        recent_documents = [
            {
                "id": d.id, "filename": d.filename, "status": d.status,
                "classification_label": d.classification_label,
                "classification_subcategory_label": d.classification_subcategory_label,
                "pipeline_confidence": d.pipeline_confidence,
                "created_at": str(d.created_at),
            }
            for d in recent_docs
        ]

    return {
        "total_documents": total_docs,
        "processing_documents": processing_docs,
        "today_documents": today_docs,
        "week_documents": week_docs,
        "closed_documents": closed_docs,
        "pending_documents": pending_docs,
        "my_locked_documents": my_locked_docs,
        # New fields
        "daily_counts": daily_counts,
        "status_breakdown": status_breakdown,
        "confidence_buckets": conf_buckets,
        "top_classifications": top_classifications,
        "top_entities": top_entities,
        "bucket_summaries": bucket_summaries,
        "recent_audit": recent_audit,
        "recent_documents": recent_documents,
        # Kept for backwards-compat
        "classification_distribution": {r["label"]: r["count"] for r in top_classifications},
        "classification_subcategory_distribution": {},
    }


@router.get("/activity")
async def global_activity(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    action: Optional[str] = Query(None, description="Filter by action type"),
    document_id: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """Paginated global audit log for all documents in the current organisation."""
    init_db()
    with get_session() as session:
        base = (
            select(DocumentAuditLog)
            .join(Document, Document.id == DocumentAuditLog.document_id)
            .where(Document.organization_id == user.organization_id)
        )
        if action:
            base = base.where(DocumentAuditLog.action == action)
        if document_id:
            base = base.where(DocumentAuditLog.document_id == document_id)

        total = session.exec(
            select(func.count()).select_from(base.subquery())
        ).one()

        rows = session.exec(
            base.order_by(DocumentAuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        items = []
        for entry in rows:
            doc = session.get(Document, entry.document_id)
            actor = None
            if entry.user_id:
                u = session.get(User, entry.user_id)
                actor = u.full_name if u else entry.user_id
            items.append({
                "id": entry.id,
                "document_id": entry.document_id,
                "filename": doc.filename if doc else None,
                "action": entry.action,
                "details": entry.details,
                "actor": actor,
                "created_at": str(entry.created_at),
            })

        # Return distinct action types for filter UI
        action_types = session.exec(
            select(DocumentAuditLog.action).distinct()
            .join(Document, Document.id == DocumentAuditLog.document_id)
            .where(Document.organization_id == user.organization_id)
        ).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
        "action_types": sorted([a for a in action_types if a]),
    }


@router.get("/activity/recent")
async def recent_activity(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """Recent pipeline events for documents in the user's organization (kept for compatibility)."""
    init_db()
    with get_session() as session:
        rows = session.exec(
            select(PipelineEvent, Document.filename)
            .join(Document, Document.id == PipelineEvent.document_id)
            .where(Document.organization_id == user.organization_id)
            .order_by(PipelineEvent.timestamp.desc())
            .limit(limit)
        ).all()
    items = []
    for row in rows:
        ev, fn = row[0], row[1]
        items.append({
            "id": ev.id,
            "document_id": ev.document_id,
            "filename": fn,
            "stage": ev.stage,
            "event_type": ev.event_type,
            "timestamp": str(ev.timestamp),
            "details": ev.details,
        })
    return {"items": items}
