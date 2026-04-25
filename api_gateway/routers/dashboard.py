from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import select, func

from dmsai_models import (
    Document, Bucket, BucketDocument, User, PipelineEvent, get_session, init_db,
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

    dt_from = None
    dt_to = None
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
        org_filter = (Document.organization_id == user.organization_id)

        base_filters = [org_filter]
        if dt_from:
            base_filters.append(Document.created_at >= dt_from)
        if dt_to:
            base_filters.append(Document.created_at <= dt_to)

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

        # Bucket-level workflow counts scoped to the user's org
        all_bucket_ids = [bid for bid in session.exec(
            select(Bucket.id).where(Bucket.organization_id == user.organization_id)
        ).all()]

        closed_docs = 0
        pending_docs = 0
        my_locked_docs = 0
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

        classification_rows = session.exec(
            select(Document.classification_label, func.count()).where(
                *base_filters, Document.classification_label.isnot(None)
            ).group_by(Document.classification_label)
        ).all()
        classification_dist = {label: cnt for label, cnt in classification_rows}

        subcategory_rows = session.exec(
            select(Document.classification_subcategory_label, func.count()).where(
                *base_filters, Document.classification_subcategory_label.isnot(None)
            ).group_by(Document.classification_subcategory_label)
        ).all()
        classification_subcategory_dist = {label: cnt for label, cnt in subcategory_rows}

        buckets = session.exec(
            select(Bucket).where(Bucket.organization_id == user.organization_id)
        ).all()
        bucket_summaries = []
        for b in buckets:
            states = {}
            for st in ("open", "pending", "locked", "closed"):
                states[st] = session.exec(
                    select(func.count()).select_from(BucketDocument).where(
                        BucketDocument.bucket_id == b.id,
                        BucketDocument.workflow_state == st,
                    )
                ).one()
            bucket_summaries.append({
                "id": b.id, "name": b.name, "states": states,
                "total": sum(states.values()),
            })

        recent_docs = session.exec(
            select(Document).where(
                Document.organization_id == user.organization_id
            ).order_by(Document.created_at.desc()).limit(10)
        ).all()
        recent_documents = [
            {
                "id": d.id, "filename": d.filename, "status": d.status,
                "classification_label": d.classification_label,
                "classification_subcategory_label": d.classification_subcategory_label,
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
        "classification_distribution": classification_dist,
        "classification_subcategory_distribution": classification_subcategory_dist,
        "bucket_summaries": bucket_summaries,
        "recent_documents": recent_documents,
    }


@router.get("/activity/recent")
async def recent_activity(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """Recent pipeline events for documents in the user's organization."""
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
