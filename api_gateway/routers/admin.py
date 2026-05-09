from __future__ import annotations

import uuid
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from dmsai_models import (
    Bucket, BucketPermission,
    Correction,
    Document, DocumentEntity,
    Entity, EntityField,
    CanonicalDocumentClass, CanonicalField,
    LLMUsage,
    Organization, OrgIngestionConfig, SystemConfig, User, UserOrganization,
    get_session, init_db, date_str, year_week_str,
)
from auth import (
    require_admin, require_org_admin, require_manager,
    get_current_user, hash_password, validate_password,
    normalize_role as _norm_role, VALID_ROLES,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _json_or_none(raw: Optional[str]):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

def _org_entity_ids(session, org_id: str) -> set[str]:
    """Return entity IDs scoped to the given org.

    Prefers the direct organization_id column on Entity (new schema); falls back
    to the document-join approach for legacy entities that have no org tag yet.
    """
    # Entities directly tagged to this org
    direct = set(session.exec(
        select(Entity.id).where(Entity.organization_id == org_id)
    ).all())
    # Legacy entities (no org tag) that appear in a document of this org
    legacy = set(session.exec(
        select(DocumentEntity.entity_id).distinct()
        .join(Document, Document.id == DocumentEntity.document_id)
        .where(
            Document.organization_id == org_id,
            Entity.organization_id.is_(None),
        )
        .join(Entity, Entity.id == DocumentEntity.entity_id)
    ).all())
    return direct | legacy


@router.get("/entities/types")
async def list_entity_types(user: User = Depends(get_current_user)):
    """Return distinct entity types for entities linked to the user's org."""
    init_db()
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)
        if not eid_set:
            return []
        rows = session.exec(
            select(Entity.entity_type).where(Entity.id.in_(eid_set)).distinct()
        ).all()
        return [t for t in rows if t]


@router.get("/entities")
async def list_entities(
    entity_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
):
    """List entities visible to the current user's organization.

    Accessible to all authenticated users (read-only).
    """
    init_db()
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)

        query = select(Entity).where(Entity.id.in_(eid_set)) if eid_set else select(Entity).where(False)
        if entity_type:
            query = query.where(Entity.entity_type == entity_type)
        if search:
            query = query.where(
                (Entity.name.contains(search)) | (Entity.canonical_name.contains(search))
            )

        from sqlmodel import func as sqlfunc
        count_sub = query.subquery()
        total = session.exec(select(sqlfunc.count()).select_from(count_sub)).one()

        offset = (page - 1) * page_size
        entities = session.exec(
            query.order_by(Entity.name).offset(offset).limit(page_size)
        ).all()

        # Pre-fetch doc counts in one query
        entity_ids = [e.id for e in entities]
        doc_count_rows = session.exec(
            select(DocumentEntity.entity_id, sqlfunc.count(DocumentEntity.document_id))
            .join(Document, Document.id == DocumentEntity.document_id)
            .where(
                DocumentEntity.entity_id.in_(entity_ids),
                Document.organization_id == user.organization_id,
            )
            .group_by(DocumentEntity.entity_id)
        ).all()
        doc_count_map = {row[0]: row[1] for row in doc_count_rows}

        result = []
        for e in entities:
            fields = session.exec(select(EntityField).where(EntityField.entity_id == e.id)).all()
            # Surface only identifier-class fields as the key fields
            key_fields = {
                f.field_name: f.field_value
                for f in fields
                if f.field_name.lower() in {
                    "tax_id", "siret", "siren", "vat_number",
                    "registration_number", "email", "phone",
                }
            }
            result.append({
                "id": e.id,
                "name": e.name,
                "canonical_name": e.canonical_name,
                "entity_type": e.entity_type,
                "created_at": str(e.created_at),
                "fields": {f.field_name: f.field_value for f in fields},
                "key_fields": key_fields,
                "doc_count": doc_count_map.get(e.id, 0),
            })
        return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.get("/quality-metrics")
async def quality_metrics(user: User = Depends(require_manager)):
    """Aggregated correction stats and confidence analytics for the organization."""
    init_db()
    org_id = user.organization_id
    with get_session() as session:
        total_docs = session.exec(
            select(func.count()).select_from(Document).where(Document.organization_id == org_id)
        ).one()

        corr_base = (
            select(Correction)
            .join(Document, Document.id == Correction.document_id)
            .where(Document.organization_id == org_id)
        )
        total_corrections = session.exec(select(func.count()).select_from(corr_base.subquery())).one()

        by_type_rows = session.exec(
            select(Correction.field_type, func.count())
            .join(Document, Document.id == Correction.document_id)
            .where(Document.organization_id == org_id)
            .group_by(Correction.field_type)
        ).all()
        corrections_by_type = {r[0]: r[1] for r in by_type_rows}

        correction_rate = (total_corrections / total_docs) if total_docs else 0.0

        avg_conf = session.exec(
            select(func.avg(Document.pipeline_confidence))
            .where(Document.organization_id == org_id)
            .where(Document.pipeline_confidence.isnot(None))
        ).one()
        avg_pipeline_confidence = float(avg_conf) if avg_conf is not None else None

        week_expr = year_week_str(func.coalesce(Document.processed_at, Document.created_at))
        week_rows = session.exec(
            select(week_expr, func.avg(Document.pipeline_confidence))
            .where(Document.organization_id == org_id)
            .where(Document.pipeline_confidence.isnot(None))
            .group_by(week_expr)
            .order_by(week_expr)
        ).all()
        weekly_confidence = [
            {"week": w[0], "avg_pipeline_confidence": float(w[1]) if w[1] is not None else None}
            for w in week_rows
        ]

        docs_for_hist = session.exec(
            select(Document)
            .where(Document.organization_id == org_id)
            .where(Document.pipeline_confidence.isnot(None))
        ).all()
        buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for doc in docs_for_hist:
            pc = doc.pipeline_confidence
            if pc is None:
                continue
            x = float(pc)
            if x < 0.2:
                buckets["0.0-0.2"] += 1
            elif x < 0.4:
                buckets["0.2-0.4"] += 1
            elif x < 0.6:
                buckets["0.4-0.6"] += 1
            elif x < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1

        field_rows = session.exec(
            select(Correction.field_name, func.count())
            .join(Document, Document.id == Correction.document_id)
            .where(Document.organization_id == org_id)
            .where(Correction.field_type.in_(["document_field", "entity_field"]))
            .where(Correction.field_name.isnot(None))
            .group_by(Correction.field_name)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        most_corrected_fields = [{"field_name": r[0], "count": r[1]} for r in field_rows]

        cls_rows = session.exec(
            select(
                Correction.original_value,
                Correction.corrected_value,
                func.count(),
            )
            .join(Document, Document.id == Correction.document_id)
            .where(Document.organization_id == org_id)
            .where(Correction.field_type == "classification")
            .group_by(Correction.original_value, Correction.corrected_value)
            .order_by(func.count().desc())
            .limit(50)
        ).all()
        classification_changes = [
            {"from": r[0], "to": r[1], "count": r[2]} for r in cls_rows
        ]

        recent_rows = session.exec(
            select(Correction, User.full_name)
            .join(Document, Document.id == Correction.document_id)
            .join(User, User.id == Correction.corrected_by)
            .where(Document.organization_id == org_id)
            .order_by(Correction.created_at.desc())
            .limit(20)
        ).all()
        recent_corrections = []
        for row in recent_rows:
            c, uname = row[0], row[1]
            recent_corrections.append({
                "id": c.id,
                "document_id": c.document_id,
                "entity_id": c.entity_id,
                "field_type": c.field_type,
                "field_name": c.field_name,
                "original_value": c.original_value,
                "corrected_value": c.corrected_value,
                "corrected_by_name": uname,
                "created_at": str(c.created_at),
            })

    return {
        "total_documents": total_docs,
        "total_corrections": total_corrections,
        "corrections_by_type": corrections_by_type,
        "correction_rate": round(correction_rate, 6),
        "avg_pipeline_confidence": round(avg_pipeline_confidence, 4) if avg_pipeline_confidence is not None else None,
        "weekly_confidence": weekly_confidence,
        "confidence_distribution": buckets,
        "most_corrected_fields": most_corrected_fields,
        "classification_changes": classification_changes,
        "recent_corrections": recent_corrections,
    }


# ---------------------------------------------------------------------------
# Global ingestion stats (admin — all orgs)
# ---------------------------------------------------------------------------

@router.get("/global-ingestion")
async def global_ingestion(
    days: int = 30,
    admin: User = Depends(require_admin),
):
    """Global document ingestion stats across all organizations."""
    from datetime import timedelta
    init_db()
    with get_session() as session:
        # Daily counts for the past `days`
        cutoff = datetime.utcnow() - timedelta(days=days)
        day_expr = date_str(Document.created_at)
        daily_rows = session.exec(
            select(day_expr, func.count())
            .where(Document.created_at >= cutoff)
            .group_by(day_expr)
            .order_by(day_expr)
        ).all()
        daily_counts = [{"date": r[0], "count": r[1]} for r in daily_rows]

        # Total documents all time
        total_all = session.exec(select(func.count()).select_from(Document)).one()

        # Status breakdown
        status_rows = session.exec(
            select(Document.status, func.count())
            .group_by(Document.status)
        ).all()
        status_breakdown = {r[0]: r[1] for r in status_rows}

        # Per-org breakdown
        org_rows = session.exec(
            select(Document.organization_id, func.count())
            .group_by(Document.organization_id)
            .order_by(func.count().desc())
        ).all()
        # Resolve org names
        org_names: dict[str, str] = {}
        for oid, _ in org_rows:
            if oid and oid not in org_names:
                org = session.get(Organization, oid)
                org_names[oid] = org.name if org else oid
        per_org = [
            {"org_id": r[0], "org_name": org_names.get(r[0] or "", r[0] or "—"), "count": r[1]}
            for r in org_rows
        ]

        # Top classifications global
        cls_rows = session.exec(
            select(Document.classification_label, func.count())
            .where(Document.classification_label.isnot(None))
            .group_by(Document.classification_label)
            .order_by(func.count().desc())
            .limit(10)
        ).all()
        top_classifications = [{"label": r[0], "count": r[1]} for r in cls_rows]

    return {
        "total_documents": total_all,
        "daily_counts": daily_counts,
        "status_breakdown": status_breakdown,
        "per_org": per_org,
        "top_classifications": top_classifications,
        "days": days,
    }


# ---------------------------------------------------------------------------
# LLM usage stats (admin — global)
# ---------------------------------------------------------------------------

@router.get("/llm-usage")
async def llm_usage_stats(
    days: int = 30,
    admin: User = Depends(require_admin),
):
    """Global LLM token consumption analytics."""
    from datetime import timedelta
    init_db()
    with get_session() as session:
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Total tokens (all time)
        total_row = session.exec(
            select(
                func.sum(LLMUsage.prompt_tokens),
                func.sum(LLMUsage.completion_tokens),
                func.sum(LLMUsage.total_tokens),
                func.count(),
            )
        ).one()
        total_prompt     = int(total_row[0] or 0)
        total_completion = int(total_row[1] or 0)
        total_tokens     = int(total_row[2] or 0)
        total_calls      = int(total_row[3] or 0)

        # Tokens in period
        period_row = session.exec(
            select(
                func.sum(LLMUsage.prompt_tokens),
                func.sum(LLMUsage.completion_tokens),
                func.sum(LLMUsage.total_tokens),
                func.count(),
            )
            .where(LLMUsage.created_at >= cutoff)
        ).one()
        period_prompt     = int(period_row[0] or 0)
        period_completion = int(period_row[1] or 0)
        period_tokens     = int(period_row[2] or 0)
        period_calls      = int(period_row[3] or 0)

        # By provider
        prov_rows = session.exec(
            select(LLMUsage.provider, func.sum(LLMUsage.total_tokens), func.count())
            .group_by(LLMUsage.provider)
        ).all()
        by_provider = [{"provider": r[0], "total_tokens": int(r[1] or 0), "calls": int(r[2] or 0)} for r in prov_rows]

        # By model
        model_rows = session.exec(
            select(LLMUsage.model, func.sum(LLMUsage.total_tokens), func.count())
            .group_by(LLMUsage.model)
            .order_by(func.sum(LLMUsage.total_tokens).desc())
        ).all()
        by_model = [{"model": r[0], "total_tokens": int(r[1] or 0), "calls": int(r[2] or 0)} for r in model_rows]

        # By stage
        stage_rows = session.exec(
            select(LLMUsage.stage, func.sum(LLMUsage.total_tokens), func.count())
            .group_by(LLMUsage.stage)
            .order_by(func.sum(LLMUsage.total_tokens).desc())
        ).all()
        by_stage = [{"stage": r[0], "total_tokens": int(r[1] or 0), "calls": int(r[2] or 0)} for r in stage_rows]

        # By call type (text vs vision)
        type_rows = session.exec(
            select(LLMUsage.call_type, func.sum(LLMUsage.total_tokens), func.count())
            .group_by(LLMUsage.call_type)
        ).all()
        by_call_type = [{"call_type": r[0], "total_tokens": int(r[1] or 0), "calls": int(r[2] or 0)} for r in type_rows]

        # Daily token trend for the period
        day_expr = date_str(LLMUsage.created_at)
        daily_rows = session.exec(
            select(
                day_expr,
                func.sum(LLMUsage.prompt_tokens),
                func.sum(LLMUsage.completion_tokens),
                func.count(),
            )
            .where(LLMUsage.created_at >= cutoff)
            .group_by(day_expr)
            .order_by(day_expr)
        ).all()
        daily_tokens = [
            {
                "date": r[0],
                "prompt_tokens": int(r[1] or 0),
                "completion_tokens": int(r[2] or 0),
                "calls": int(r[3] or 0),
            }
            for r in daily_rows
        ]

    return {
        "total": {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "calls": total_calls,
        },
        "period": {
            "days": days,
            "prompt_tokens": period_prompt,
            "completion_tokens": period_completion,
            "total_tokens": period_tokens,
            "calls": period_calls,
        },
        "by_provider": by_provider,
        "by_model": by_model,
        "by_stage": by_stage,
        "by_call_type": by_call_type,
        "daily_tokens": daily_tokens,
    }


class EntityMergeBody(BaseModel):
    source_id: str
    target_id: str


@router.post("/entities/merge")
async def merge_entities(body: EntityMergeBody, user: User = Depends(require_manager)):
    """Merge source entity into target (reassign links and fields, delete source)."""
    init_db()
    if body.source_id == body.target_id:
        raise HTTPException(status_code=400, detail="source and target must differ")
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)
        if body.source_id not in eid_set or body.target_id not in eid_set:
            raise HTTPException(status_code=404, detail="Entity not found")
        src = session.get(Entity, body.source_id)
        tgt = session.get(Entity, body.target_id)
        if not src or not tgt:
            raise HTTPException(status_code=404, detail="Entity not found")

        for de in session.exec(
            select(DocumentEntity).where(DocumentEntity.entity_id == body.source_id)
        ).all():
            existing = session.exec(
                select(DocumentEntity).where(
                    DocumentEntity.document_id == de.document_id,
                    DocumentEntity.entity_id == body.target_id,
                    DocumentEntity.role == de.role,
                )
            ).first()
            if existing:
                session.delete(de)
            else:
                de.entity_id = body.target_id
                session.add(de)

        for ef in session.exec(select(EntityField).where(EntityField.entity_id == body.source_id)).all():
            dup = session.exec(
                select(EntityField).where(
                    EntityField.entity_id == body.target_id,
                    EntityField.field_name == ef.field_name,
                )
            ).first()
            if dup:
                session.delete(ef)
            else:
                ef.entity_id = body.target_id
                session.add(ef)

        session.delete(src)
        session.commit()
    return {"status": "merged", "target_id": body.target_id}


@router.get("/entities/{entity_id}/relationships")
async def entity_relationships(entity_id: str, user: User = Depends(get_current_user)):
    """Entities that co-occur in documents with this entity."""
    init_db()
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)
        if entity_id not in eid_set:
            raise HTTPException(status_code=404, detail="Entity not found")

        my_docs = {
            de.document_id
            for de in session.exec(
                select(DocumentEntity).where(DocumentEntity.entity_id == entity_id)
            ).all()
        }
        other_counts: dict[str, set[str]] = defaultdict(set)
        shared_docs: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for doc_id in my_docs:
            others = session.exec(
                select(DocumentEntity).where(
                    DocumentEntity.document_id == doc_id,
                    DocumentEntity.entity_id != entity_id,
                )
            ).all()
            for o in others:
                other_counts[o.entity_id].add(doc_id)
                doc = session.get(Document, doc_id)
                shared_docs[o.entity_id].append(
                    (doc_id, doc.filename if doc else doc_id)
                )

        out = []
        for oid, doc_ids in other_counts.items():
            ent = session.get(Entity, oid)
            if not ent or oid not in eid_set:
                continue
            out.append({
                "entity_id": ent.id,
                "name": ent.name,
                "entity_type": ent.entity_type,
                "shared_document_count": len(doc_ids),
                "shared_documents": [{"id": i[0], "filename": i[1]} for i in shared_docs.get(oid, [])[:20]],
            })
        out.sort(key=lambda x: -x["shared_document_count"])
    return {"items": out}


@router.get("/entities/{entity_id}/dossier")
async def entity_dossier(entity_id: str, user: User = Depends(get_current_user)):
    """Cross-document aggregation for one entity."""
    init_db()
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)
        if entity_id not in eid_set:
            raise HTTPException(status_code=404, detail="Entity not found")
        entity = session.get(Entity, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        links = session.exec(
            select(DocumentEntity)
            .join(Document, Document.id == DocumentEntity.document_id)
            .where(DocumentEntity.entity_id == entity_id)
            .where(Document.organization_id == user.organization_id)
            .order_by(Document.created_at)
        ).all()

        timeline = []
        documents_out = []
        for de in links:
            doc = session.get(Document, de.document_id)
            if not doc:
                continue
            timeline.append({
                "document_id": doc.id,
                "filename": doc.filename,
                "role": de.role,
                "at": str(doc.created_at),
            })
            documents_out.append({
                "document_id": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "classification_label": doc.classification_label,
                "pipeline_confidence": doc.pipeline_confidence,
                "role": de.role,
                "link_confidence": de.confidence,
                "created_at": str(doc.created_at),
            })

        fields = session.exec(select(EntityField).where(EntityField.entity_id == entity_id)).all()
        fields_out = [
            {
                "id": f.id,
                "field_name": f.field_name,
                "field_value": f.field_value,
                "confidence": f.confidence,
                "confidence_details": _json_or_none(f.confidence_details),
            }
            for f in fields
        ]

    return {
        "entity": {
            "id": entity.id,
            "name": entity.name,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "created_at": str(entity.created_at),
        },
        "fields": fields_out,
        "documents": documents_out,
        "timeline": timeline,
    }


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)
        entity = session.get(Entity, entity_id)
        if not entity or entity.id not in eid_set:
            raise HTTPException(status_code=404, detail="Entity not found")
        fields = session.exec(select(EntityField).where(EntityField.entity_id == entity.id)).all()
        return {
            "id": entity.id, "name": entity.name,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "created_at": str(entity.created_at),
            "fields": [
                {
                    "id": f.id,
                    "field_name": f.field_name,
                    "field_value": f.field_value,
                    "confidence": f.confidence,
                    "confidence_details": _json_or_none(f.confidence_details),
                }
                for f in fields
            ],
        }


# ---------------------------------------------------------------------------
# Canonical Fields
# ---------------------------------------------------------------------------

class CanonicalFieldCreate(BaseModel):
    canonical_name: str
    description: str = ""
    document_class: Optional[str] = None
    aliases: list[str] = []
    scope: str = "document"


class CanonicalFieldUpdate(BaseModel):
    canonical_name: Optional[str] = None
    description: Optional[str] = None
    document_class: Optional[str] = None
    aliases: Optional[list[str]] = None
    scope: Optional[str] = None


@router.get("/canonical-fields")
async def list_canonical_fields(
    scope: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    import json as _json
    with get_session() as session:
        q = select(CanonicalField)
        if scope:
            q = q.where(CanonicalField.scope == scope)
        cfs = session.exec(q).all()
        return [
            {
                "id": cf.id,
                "scope": getattr(cf, "scope", "document"),
                "canonical_name": cf.canonical_name,
                "description": cf.description,
                "document_class": cf.document_class,
                "aliases": _json.loads(cf.aliases),
                "created_at": str(cf.created_at),
            }
            for cf in cfs
        ]


@router.post("/canonical-fields")
async def create_canonical_field(body: CanonicalFieldCreate, user: User = Depends(require_manager)):
    import json as _json
    with get_session() as session:
        existing = session.exec(
            select(CanonicalField).where(
                CanonicalField.scope == body.scope,
                CanonicalField.canonical_name == body.canonical_name,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Canonical field name already exists for this scope")
        cf = CanonicalField(
            id=str(uuid.uuid4()),
            scope=body.scope,
            canonical_name=body.canonical_name,
            description=body.description,
            document_class=body.document_class,
            aliases=_json.dumps(body.aliases),
            created_at=datetime.utcnow(),
        )
        session.add(cf)
        cf_id = cf.id
        cf_name = cf.canonical_name
        session.commit()
    return {"id": cf_id, "canonical_name": cf_name}


@router.put("/canonical-fields/{cf_id}")
async def update_canonical_field(cf_id: str, body: CanonicalFieldUpdate, user: User = Depends(require_manager)):
    import json as _json
    with get_session() as session:
        cf = session.get(CanonicalField, cf_id)
        if not cf:
            raise HTTPException(status_code=404, detail="Canonical field not found")
        if body.canonical_name is not None:
            cf.canonical_name = body.canonical_name
        if body.description is not None:
            cf.description = body.description
        if body.document_class is not None:
            cf.document_class = body.document_class
        if body.aliases is not None:
            cf.aliases = _json.dumps(body.aliases)
        if body.scope is not None:
            cf.scope = body.scope
        session.add(cf)
        session.commit()
    return {"status": "updated"}


@router.delete("/canonical-fields/{cf_id}")
async def delete_canonical_field(cf_id: str, user: User = Depends(require_admin)):
    with get_session() as session:
        cf = session.get(CanonicalField, cf_id)
        if not cf:
            raise HTTPException(status_code=404, detail="Canonical field not found")
        session.delete(cf)
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Canonical document classes
# ---------------------------------------------------------------------------

class CanonicalDocumentClassCreate(BaseModel):
    canonical_name: str
    description: str = ""
    aliases: list[str] = []
    parent_id: Optional[str] = None


class CanonicalDocumentClassUpdate(BaseModel):
    canonical_name: Optional[str] = None
    description: Optional[str] = None
    aliases: Optional[list[str]] = None
    parent_id: Optional[str] = None


@router.get("/canonical-document-classes")
async def list_canonical_document_classes(user: User = Depends(get_current_user)):
    import json as _json
    with get_session() as session:
        classes = session.exec(select(CanonicalDocumentClass)).all()
        return [
            {
                "id": c.id,
                "parent_id": c.parent_id,
                "canonical_name": c.canonical_name,
                "description": c.description,
                "aliases": _json.loads(c.aliases or "[]"),
                "created_at": str(c.created_at),
                "updated_at": str(c.updated_at) if c.updated_at else None,
            }
            for c in classes
        ]


@router.post("/canonical-document-classes")
async def create_canonical_document_class(
    body: CanonicalDocumentClassCreate,
    user: User = Depends(require_manager),
):
    import json as _json
    with get_session() as session:
        existing = session.exec(
            select(CanonicalDocumentClass).where(
                CanonicalDocumentClass.canonical_name == body.canonical_name,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Canonical document class already exists")
        row = CanonicalDocumentClass(
            id=str(uuid.uuid4()),
            parent_id=body.parent_id,
            canonical_name=body.canonical_name,
            description=body.description,
            aliases=_json.dumps(body.aliases),
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        return {"id": row.id, "canonical_name": row.canonical_name}


@router.put("/canonical-document-classes/{class_id}")
async def update_canonical_document_class(
    class_id: str,
    body: CanonicalDocumentClassUpdate,
    user: User = Depends(require_manager),
):
    import json as _json
    with get_session() as session:
        row = session.get(CanonicalDocumentClass, class_id)
        if not row:
            raise HTTPException(status_code=404, detail="Canonical document class not found")
        if body.canonical_name is not None:
            row.canonical_name = body.canonical_name
        if body.description is not None:
            row.description = body.description
        if body.aliases is not None:
            row.aliases = _json.dumps(body.aliases)
        if body.parent_id is not None:
            row.parent_id = body.parent_id
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# System Configuration
# ---------------------------------------------------------------------------

class SystemConfigUpdate(BaseModel):
    value: str


class ServiceRestartRequest(BaseModel):
    services: list[str]


_SENSITIVE_KEY_PATTERNS = ("password", "secret", "api_key")


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in _SENSITIVE_KEY_PATTERNS)


def _config_row_to_dict(row: SystemConfig, *, redact: bool) -> dict:
    value = "********" if redact and _is_sensitive(row.key) and row.value else row.value
    return {
        "key": row.key, "value": value, "category": row.category,
        "description": row.description, "updated_at": str(row.updated_at),
    }


@router.get("/system-config")
async def list_system_config(
    category: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    init_db()
    redact = user.role != "admin"
    with get_session() as session:
        q = select(SystemConfig)
        if category:
            q = q.where(SystemConfig.category == category)
        rows = session.exec(q).all()
        return [_config_row_to_dict(r, redact=redact) for r in rows]


@router.get("/system-config/{key}")
async def get_system_config(key: str, user: User = Depends(get_current_user)):
    redact = user.role != "admin"
    with get_session() as session:
        row = session.get(SystemConfig, key)
        if not row:
            raise HTTPException(status_code=404, detail="Config key not found")
        return _config_row_to_dict(row, redact=redact)


@router.put("/system-config/{key}")
async def update_system_config(key: str, body: SystemConfigUpdate, user: User = Depends(require_admin)):
    with get_session() as session:
        row = session.get(SystemConfig, key)
        if not row:
            raise HTTPException(status_code=404, detail="Config key not found")
        row.value = body.value
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    return {"status": "updated", "key": key, "value": body.value}


@router.post("/services/restart")
async def restart_services(body: ServiceRestartRequest, user: User = Depends(require_admin)):
    allowed = {
        "ocr", "classification", "entity_extraction", "entity_resolution",
        "field_extraction", "litellm", "frontend",
    }
    services = sorted({svc for svc in body.services if svc in allowed})
    if not services:
        raise HTTPException(status_code=400, detail="No restartable services requested")

    root = Path(__file__).resolve().parents[2]
    cmd = [sys.executable, str(root / "dmsai.py"), "restart", "--only", ",".join(services)]
    subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "restart_started", "services": services}


# ---------------------------------------------------------------------------
# Admin — User management
# ---------------------------------------------------------------------------

class AdminUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "user"
    organization_id: Optional[str] = None  # defaults to admin's own org


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.post(
    "/users",
    summary="Create user",
    description=(
        "Admin creates a new user account. "
        "By default the user is placed in the admin's own organization. "
        "Specify `organization_id` to create a user in a different organization "
        "(useful when setting up a freshly created org via `POST /api/admin/organizations`)."
    ),
)
async def admin_create_user(body: AdminUserCreate, admin: User = Depends(require_admin)):
    pw_error = validate_password(body.password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)

    body.role = _norm_role(body.role)
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {', '.join(VALID_ROLES)}",
        )

    target_org_id = body.organization_id or admin.organization_id

    with get_session() as session:
        # Verify target org exists
        org = session.get(Organization, target_org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Check email uniqueness
        existing = session.exec(select(User).where(User.email == body.email)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        new_user_id = str(uuid.uuid4())
        new_user = User(
            id=new_user_id,
            email=body.email,
            password_hash=hash_password(body.password),
            full_name=body.full_name,
            role=body.role,
            organization_id=target_org_id,
            is_active=True,
            auth_provider="local",
            email_verified=True,  # admin-created accounts are pre-verified
            created_at=datetime.utcnow(),
        )
        session.add(new_user)
        # Always create the UserOrganization membership record
        session.add(UserOrganization(
            id=str(uuid.uuid4()),
            user_id=new_user_id,
            organization_id=target_org_id,
            role=body.role,
            is_default=True,
        ))
        session.commit()
        return {
            "status": "created",
            "id": new_user.id,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": new_user.role,
            "organization_id": new_user.organization_id,
        }


@router.delete(
    "/users/{user_id}",
    summary="Deactivate user",
    description=(
        "Deactivate a user account. The user cannot log in while deactivated. "
        "Their data is preserved. Admins may only deactivate users in their own organization. "
        "An admin cannot deactivate their own account."
    ),
)
async def admin_deactivate_user(user_id: str, admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        # Only admins who share an org membership with the target user may deactivate them
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == admin.organization_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.is_active:
            return {"status": "already_inactive", "id": user_id}
        user.is_active = False
        session.add(user)
        session.commit()
    return {"status": "deactivated", "id": user_id}


@router.put(
    "/users/{user_id}",
    summary="Update user (admin)",
    description="Update a user's role, name, or active status. Admins may only update users in their own organization.",
)
async def admin_update_user(user_id: str, body: AdminUserUpdate, admin: User = Depends(require_admin)):
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        # Only admins who share an org membership with the target user may update them
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == admin.organization_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="User not found")
        if body.full_name is not None:
            user.full_name = body.full_name
        if body.role is not None:
            body.role = _norm_role(body.role)
            if body.role not in VALID_ROLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"role must be one of {', '.join(VALID_ROLES)}",
                )
            if user_id == admin.id and body.role != "admin":
                raise HTTPException(
                    status_code=400,
                    detail="You cannot demote your own admin account. Ask another admin to do this.",
                )
            # Update the org-specific role and sync to User.role if this is the user's home org
            membership.role = body.role
            session.add(membership)
            if user.organization_id == admin.organization_id:
                user.role = body.role
        if body.is_active is not None:
            if user_id == admin.id and not body.is_active:
                raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
            user.is_active = body.is_active
        session.add(user)
        session.commit()
    return {"status": "updated"}


class AdminResetPassword(BaseModel):
    new_password: str


@router.post(
    "/users/{user_id}/reset-password",
    summary="Reset a user's password",
    description=(
        "Force-reset a user's password.  The new password is hashed and stored. "
        "The user keeps any other auth state (verified email, role, memberships). "
        "Admins may only reset passwords for users in their own organization. "
        "The target account is also automatically unlocked (failed-login counter cleared)."
    ),
)
async def admin_reset_password(
    user_id: str, body: AdminResetPassword, admin: User = Depends(require_admin)
):
    pw_error = validate_password(body.new_password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        # Same scoping rule as admin_update_user — must share an org with the admin.
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == admin.organization_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="User not found")
        user.password_hash = hash_password(body.new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        # Force re-auth for any active sessions: invalidate the token versioning
        # if/when we add it.  For now bumping the password is the source of truth.
        session.add(user)
        session.commit()
    return {"status": "password_reset", "user_id": user_id}


# ---------------------------------------------------------------------------
# Phase 5 — Per-user permissions matrix (org × bucket)
# ---------------------------------------------------------------------------

class MatrixBucketEntry(BaseModel):
    bucket_id: str
    bucket_name: str
    permission: Optional[str] = None  # None = no explicit grant


class MatrixOrgEntry(BaseModel):
    organization_id: str
    organization_name: str
    membership_role: Optional[str] = None  # None = not a member
    buckets: list[MatrixBucketEntry] = []


class MatrixSnapshot(BaseModel):
    user_id: str
    email: str
    full_name: str
    home_organization_id: str
    matrix: list[MatrixOrgEntry]


def _orgs_visible_to_admin(session, admin: User) -> list[Organization]:
    """System admin sees every org; org_admin sees only their home org."""
    if admin.role == "admin":
        return list(session.exec(select(Organization).order_by(Organization.name)).all())
    return [session.get(Organization, admin.organization_id)]


@router.get(
    "/users/{user_id}/access-matrix",
    summary="Get a user's full org × bucket access matrix",
    description=(
        "Return every organization the calling admin can manage and, for each, "
        "the user's membership role (or null) plus every bucket and the user's "
        "permission on it (or null).  System admin sees every org; org_admin "
        "sees only their own organization."
    ),
    response_model=MatrixSnapshot,
)
async def get_user_access_matrix(user_id: str, admin: User = Depends(require_org_admin)):
    init_db()
    with get_session() as session:
        target = session.get(User, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        # Org-admins can only manage users that share at least one org with them.
        if admin.role != "admin":
            shared = session.exec(
                select(UserOrganization).where(
                    UserOrganization.user_id == user_id,
                    UserOrganization.organization_id == admin.organization_id,
                )
            ).first()
            if not shared:
                raise HTTPException(status_code=404, detail="User not found")

        orgs = _orgs_visible_to_admin(session, admin)
        memberships = {
            m.organization_id: m
            for m in session.exec(
                select(UserOrganization).where(UserOrganization.user_id == user_id)
            ).all()
        }

        # Pre-fetch all buckets and permissions in the visible orgs
        org_ids = [o.id for o in orgs if o]
        if not org_ids:
            return MatrixSnapshot(
                user_id=target.id,
                email=target.email,
                full_name=target.full_name,
                home_organization_id=target.organization_id,
                matrix=[],
            )
        buckets = session.exec(
            select(Bucket).where(Bucket.organization_id.in_(org_ids)).order_by(Bucket.name)
        ).all()
        bucket_by_org: dict[str, list[Bucket]] = defaultdict(list)
        for b in buckets:
            bucket_by_org[b.organization_id].append(b)

        # Map bucket_id -> permission for this user (only buckets in our visible scope)
        bucket_ids = [b.id for b in buckets]
        perms_by_bucket: dict[str, str] = {}
        if bucket_ids:
            for p in session.exec(
                select(BucketPermission).where(
                    BucketPermission.user_id == user_id,
                    BucketPermission.bucket_id.in_(bucket_ids),
                )
            ).all():
                perms_by_bucket[p.bucket_id] = p.permission

        matrix: list[MatrixOrgEntry] = []
        for org in orgs:
            if not org:
                continue
            entry = MatrixOrgEntry(
                organization_id=org.id,
                organization_name=org.name,
                membership_role=memberships[org.id].role if org.id in memberships else None,
                buckets=[
                    MatrixBucketEntry(
                        bucket_id=b.id,
                        bucket_name=b.name,
                        permission=perms_by_bucket.get(b.id),
                    )
                    for b in bucket_by_org.get(org.id, [])
                ],
            )
            matrix.append(entry)

        return MatrixSnapshot(
            user_id=target.id,
            email=target.email,
            full_name=target.full_name,
            home_organization_id=target.organization_id,
            matrix=matrix,
        )


class MatrixUpdateMembership(BaseModel):
    organization_id: str
    role: Optional[str] = None  # None / "" = remove membership


class MatrixUpdateBucketGrant(BaseModel):
    bucket_id: str
    permission: Optional[str] = None  # None / "" = remove grant


class MatrixUpdate(BaseModel):
    memberships: list[MatrixUpdateMembership] = []
    bucket_grants: list[MatrixUpdateBucketGrant] = []


@router.post(
    "/users/{user_id}/access-matrix",
    summary="Bulk-update a user's org × bucket permissions",
    description=(
        "Apply a batch of membership and bucket-permission changes to one user "
        "in a single transaction.  When granting bucket access in an org the user "
        "is not yet a member of, a `viewer` UserOrganization row is auto-created. "
        "System admin can edit any org; org_admin can only edit their own org."
    ),
)
async def update_user_access_matrix(
    user_id: str, body: MatrixUpdate, admin: User = Depends(require_org_admin)
):
    init_db()
    with get_session() as session:
        target = session.get(User, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        visible_org_ids = {o.id for o in _orgs_visible_to_admin(session, admin) if o}

        # Refuse self-demote/self-deactivate footguns
        for m in body.memberships:
            if m.organization_id not in visible_org_ids:
                raise HTTPException(
                    status_code=403,
                    detail=f"You cannot edit memberships for org {m.organization_id}",
                )
            if user_id == admin.id and m.role != "admin" and m.organization_id == admin.organization_id:
                raise HTTPException(
                    status_code=400,
                    detail="You cannot demote yourself in your own organization.",
                )
            if m.role and _norm_role(m.role) not in VALID_ROLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"role must be one of {', '.join(VALID_ROLES)}",
                )

        # Validate bucket grants — each bucket must belong to a visible org
        for g in body.bucket_grants:
            bucket = session.get(Bucket, g.bucket_id)
            if not bucket:
                raise HTTPException(status_code=404, detail=f"Bucket {g.bucket_id} not found")
            if bucket.organization_id not in visible_org_ids:
                raise HTTPException(
                    status_code=403,
                    detail=f"You cannot edit bucket {g.bucket_id} (other organization)",
                )
            if g.permission and g.permission not in ("view", "edit", "admin"):
                raise HTTPException(status_code=400, detail="permission must be view/edit/admin")

        # ---- Apply membership changes ----
        existing_mems = {
            m.organization_id: m
            for m in session.exec(
                select(UserOrganization).where(UserOrganization.user_id == user_id)
            ).all()
        }
        for m in body.memberships:
            normalized = _norm_role(m.role) if m.role else None
            current = existing_mems.get(m.organization_id)
            if not normalized:
                # Remove membership (also clear all bucket perms in that org)
                if current:
                    bucket_ids = [
                        b.id for b in session.exec(
                            select(Bucket).where(Bucket.organization_id == m.organization_id)
                        ).all()
                    ]
                    if bucket_ids:
                        for bp in session.exec(
                            select(BucketPermission).where(
                                BucketPermission.user_id == user_id,
                                BucketPermission.bucket_id.in_(bucket_ids),
                            )
                        ).all():
                            session.delete(bp)
                    session.delete(current)
            else:
                if current:
                    current.role = normalized
                    session.add(current)
                else:
                    session.add(UserOrganization(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        organization_id=m.organization_id,
                        role=normalized,
                        is_default=False,
                        joined_at=datetime.utcnow(),
                    ))

        # ---- Apply bucket grant changes ----
        existing_perms = {
            p.bucket_id: p
            for p in session.exec(
                select(BucketPermission).where(BucketPermission.user_id == user_id)
            ).all()
        }
        for g in body.bucket_grants:
            current = existing_perms.get(g.bucket_id)
            if not g.permission:
                if current:
                    session.delete(current)
            else:
                if current:
                    current.permission = g.permission
                    session.add(current)
                else:
                    session.add(BucketPermission(
                        id=str(uuid.uuid4()),
                        bucket_id=g.bucket_id,
                        user_id=user_id,
                        permission=g.permission,
                    ))

                # Auto-add a viewer membership if the user has no org row yet.
                bucket = session.get(Bucket, g.bucket_id)
                if bucket:
                    has_membership = session.exec(
                        select(UserOrganization).where(
                            UserOrganization.user_id == user_id,
                            UserOrganization.organization_id == bucket.organization_id,
                        )
                    ).first()
                    if not has_membership:
                        session.add(UserOrganization(
                            id=str(uuid.uuid4()),
                            user_id=user_id,
                            organization_id=bucket.organization_id,
                            role="viewer",
                            is_default=False,
                            joined_at=datetime.utcnow(),
                        ))

        session.commit()

    return {"status": "updated", "user_id": user_id}


# ---------------------------------------------------------------------------
# Admin — Organization management
# ---------------------------------------------------------------------------

class OrganizationCreate(BaseModel):
    name: str


@router.get(
    "/organizations",
    summary="List organizations",
    description="Return all organizations visible to this admin. Only the admin's own org is returned unless there are no other admins for other orgs.",
)
async def admin_list_organizations(admin: User = Depends(require_admin)):
    with get_session() as session:
        orgs = session.exec(select(Organization)).all()
        return [
            {"id": o.id, "name": o.name, "created_at": str(o.created_at)}
            for o in orgs
        ]


@router.post(
    "/organizations",
    summary="Create organization",
    description=(
        "Create a new organization. After creation, use `POST /api/admin/users` with the new "
        "`organization_id` to create the first user (admin) for that organization. "
        "Users can also self-register with the exact organization name if registration is open."
    ),
)
async def admin_create_organization(body: OrganizationCreate, admin: User = Depends(require_admin)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Organization name cannot be empty")

    with get_session() as session:
        existing = session.exec(
            select(Organization).where(Organization.name == name)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="An organization with this name already exists")

        org = Organization(
            id=str(uuid.uuid4()),
            name=name,
            created_at=datetime.utcnow(),
        )
        session.add(org)
        session.commit()
        return {"status": "created", "id": org.id, "name": org.name, "created_at": str(org.created_at)}


# ---------------------------------------------------------------------------
# Admin — Organization membership management
# ---------------------------------------------------------------------------

class MemberAdd(BaseModel):
    user_id: str
    role: str = "user"


class MemberUpdate(BaseModel):
    role: str


@router.get("/organizations/{org_id}/members", summary="List members of an organization")
async def admin_list_org_members(org_id: str, admin: User = Depends(require_admin)):
    with get_session() as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        memberships = session.exec(
            select(UserOrganization).where(UserOrganization.organization_id == org_id)
        ).all()
        result = []
        for m in memberships:
            user = session.get(User, m.user_id)
            if user:
                result.append({
                    "membership_id": m.id,
                    "user_id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": m.role,
                    "is_default": m.is_default,
                    "joined_at": str(m.joined_at),
                    "is_active": user.is_active,
                })
        return result


@router.post("/organizations/{org_id}/members", summary="Add a user to an organization")
async def admin_add_org_member(org_id: str, body: MemberAdd, admin: User = Depends(require_admin)):
    body.role = _norm_role(body.role)
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {', '.join(VALID_ROLES)}",
        )
    with get_session() as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        user = session.get(User, body.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        existing = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == body.user_id,
                UserOrganization.organization_id == org_id,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="User is already a member of this organization")
        # Check if this is the user's first org membership — mark as default
        any_membership = session.exec(
            select(UserOrganization).where(UserOrganization.user_id == body.user_id)
        ).first()
        session.add(UserOrganization(
            id=str(uuid.uuid4()),
            user_id=body.user_id,
            organization_id=org_id,
            role=body.role,
            is_default=(any_membership is None),
            joined_at=datetime.utcnow(),
        ))
        session.commit()
    return {"status": "added", "user_id": body.user_id, "org_id": org_id, "role": body.role}


@router.put(
    "/organizations/{org_id}/members/{user_id}",
    summary="Update a member's role within an organization",
)
async def admin_update_org_member(
    org_id: str, user_id: str, body: MemberUpdate, admin: User = Depends(require_admin)
):
    body.role = _norm_role(body.role)
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {', '.join(VALID_ROLES)}",
        )
    with get_session() as session:
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == org_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found")
        membership.role = body.role
        session.add(membership)
        session.commit()
    return {"status": "updated", "user_id": user_id, "org_id": org_id, "role": body.role}


@router.delete(
    "/organizations/{org_id}/members/{user_id}",
    summary="Remove a user from an organization",
)
async def admin_remove_org_member(org_id: str, user_id: str, admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from an organization")
    with get_session() as session:
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == org_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="Membership not found")
        session.delete(membership)
        session.commit()
    return {"status": "removed", "user_id": user_id, "org_id": org_id}


# ---------------------------------------------------------------------------
# Admin — Per-org ingestion config
# ---------------------------------------------------------------------------

class IngestionConfigCreate(BaseModel):
    name: str
    source_type: str    # "directory" | "email"
    config: dict        # free-form settings for this source type
    is_active: bool = True


class IngestionConfigUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None


@router.get("/organizations/{org_id}/ingestion", summary="List ingestion configs for an org")
async def admin_list_ingestion_configs(org_id: str, admin: User = Depends(require_admin)):
    with get_session() as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        configs = session.exec(
            select(OrgIngestionConfig).where(OrgIngestionConfig.organization_id == org_id)
        ).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "source_type": c.source_type,
                "config": _json_or_none(c.config_json),
                "is_active": c.is_active,
                "created_at": str(c.created_at),
            }
            for c in configs
        ]


@router.post("/organizations/{org_id}/ingestion", summary="Add an ingestion config to an org")
async def admin_create_ingestion_config(
    org_id: str, body: IngestionConfigCreate, admin: User = Depends(require_admin)
):
    if body.source_type not in ("directory", "email"):
        raise HTTPException(status_code=400, detail="source_type must be 'directory' or 'email'")
    with get_session() as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        cfg = OrgIngestionConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name=body.name,
            source_type=body.source_type,
            config_json=json.dumps(body.config),
            is_active=body.is_active,
            created_at=datetime.utcnow(),
        )
        session.add(cfg)
        session.commit()
        return {
            "status": "created",
            "id": cfg.id,
            "name": cfg.name,
            "source_type": cfg.source_type,
            "config": body.config,
            "is_active": cfg.is_active,
        }


@router.put(
    "/organizations/{org_id}/ingestion/{config_id}",
    summary="Update an ingestion config",
)
async def admin_update_ingestion_config(
    org_id: str, config_id: str, body: IngestionConfigUpdate, admin: User = Depends(require_admin)
):
    with get_session() as session:
        cfg = session.get(OrgIngestionConfig, config_id)
        if not cfg or cfg.organization_id != org_id:
            raise HTTPException(status_code=404, detail="Ingestion config not found")
        if body.name is not None:
            cfg.name = body.name
        if body.config is not None:
            cfg.config_json = json.dumps(body.config)
        if body.is_active is not None:
            cfg.is_active = body.is_active
        session.add(cfg)
        session.commit()
    return {"status": "updated", "id": config_id}


@router.delete(
    "/organizations/{org_id}/ingestion/{config_id}",
    summary="Delete an ingestion config",
)
async def admin_delete_ingestion_config(
    org_id: str, config_id: str, admin: User = Depends(require_admin)
):
    with get_session() as session:
        cfg = session.get(OrgIngestionConfig, config_id)
        if not cfg or cfg.organization_id != org_id:
            raise HTTPException(status_code=404, detail="Ingestion config not found")
        session.delete(cfg)
        session.commit()
    return {"status": "deleted", "id": config_id}
