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
    Correction,
    Document, DocumentEntity,
    Entity, EntityField,
    CanonicalDocumentClass, CanonicalField,
    Organization, SystemConfig, User, get_session, init_db,
)
from auth import require_admin, require_manager, get_current_user, hash_password, validate_password

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
    """Return entity IDs linked to at least one document in the given org."""
    rows = session.exec(
        select(DocumentEntity.entity_id).distinct()
        .join(Document, Document.id == DocumentEntity.document_id)
        .where(Document.organization_id == org_id)
    ).all()
    return set(rows)


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
    user: User = Depends(require_manager),
):
    init_db()
    with get_session() as session:
        eid_set = _org_entity_ids(session, user.organization_id)

        query = select(Entity).where(Entity.id.in_(eid_set)) if eid_set else select(Entity).where(False)
        if entity_type:
            query = query.where(Entity.entity_type == entity_type)
        if search:
            query = query.where(Entity.name.contains(search))

        from sqlmodel import func as sqlfunc
        count_sub = query.subquery()
        total = session.exec(select(sqlfunc.count()).select_from(count_sub)).one()

        offset = (page - 1) * page_size
        entities = session.exec(query.offset(offset).limit(page_size)).all()
        result = []
        for e in entities:
            fields = session.exec(select(EntityField).where(EntityField.entity_id == e.id)).all()
            result.append({
                "id": e.id, "name": e.name,
                "canonical_name": e.canonical_name,
                "entity_type": e.entity_type,
                "created_at": str(e.created_at),
                "fields": {f.field_name: f.field_value for f in fields},
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

        week_rows = session.exec(
            select(
                func.strftime("%Y-%W", func.coalesce(Document.processed_at, Document.created_at)),
                func.avg(Document.pipeline_confidence),
            )
            .where(Document.organization_id == org_id)
            .where(Document.pipeline_confidence.isnot(None))
            .group_by(func.strftime("%Y-%W", func.coalesce(Document.processed_at, Document.created_at)))
            .order_by(func.strftime("%Y-%W", func.coalesce(Document.processed_at, Document.created_at)))
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

    if body.role not in ("admin", "manager", "user"):
        raise HTTPException(status_code=400, detail="role must be admin, manager, or user")

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

        new_user = User(
            id=str(uuid.uuid4()),
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
        if not user or user.organization_id != admin.organization_id:
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
        if not user or user.organization_id != admin.organization_id:
            raise HTTPException(status_code=404, detail="User not found")
        if body.full_name is not None:
            user.full_name = body.full_name
        if body.role is not None:
            if body.role not in ("admin", "manager", "user"):
                raise HTTPException(status_code=400, detail="role must be admin, manager, or user")
            if user_id == admin.id and body.role != "admin":
                raise HTTPException(
                    status_code=400,
                    detail="You cannot demote your own admin account. Ask another admin to do this.",
                )
            user.role = body.role
        if body.is_active is not None:
            if user_id == admin.id and not body.is_active:
                raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
            user.is_active = body.is_active
        session.add(user)
        session.commit()
    return {"status": "updated"}


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
