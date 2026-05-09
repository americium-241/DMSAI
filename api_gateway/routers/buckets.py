from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlmodel import select, func

from dmsai_models import (
    Bucket, BucketRule, BucketDocument, BucketPermission,
    Document, DocumentField, DocumentEntity, Entity, EntityField,
    Organization, SystemConfig, User, UserOrganization, get_session, init_db,
)
from auth import get_current_user, require_manager, require_org_admin  # noqa: F401

INTERNAL_API_KEY = os.environ.get("DMSAI_INTERNAL_API_KEY", "")
VISION_RULE_PROMPT = """You are evaluating whether a document should be assigned to a bucket.

Bucket rule:
{rule}

Known document metadata:
- filename: {filename}
- classification_label: {classification_label}
- classification_subcategory_label: {classification_subcategory_label}
- classification_path: {classification_path}

Inspect the document image and decide whether the bucket rule is true.
Return ONLY a valid JSON object:
{{"match": true/false, "reason": "<short reason>"}}"""

router = APIRouter(prefix="/api/buckets", tags=["buckets"])

LOCK_TIMEOUT_MINUTES = 30


class BucketCreate(BaseModel):
    name: str
    description: Optional[str] = None


class BucketUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RuleCreate(BaseModel):
    field: str
    operator: str = "equals"
    value: str


class PermissionCreate(BaseModel):
    user_id: str
    permission: str = "view"


class StateChange(BaseModel):
    workflow_state: str


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _user_can_access_bucket(session, bucket_id: str, user: User, min_perm: str = "view") -> Bucket:
    bucket = session.get(Bucket, bucket_id)
    if not bucket or bucket.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Bucket not found")
    # System admin and org-scoped admin bypass per-bucket ACLs.  ``manager``
    # is accepted for back-compat with stale JWTs issued before the rename.
    if user.role in ("admin", "org_admin", "manager"):
        return bucket
    perm = session.exec(
        select(BucketPermission).where(
            BucketPermission.bucket_id == bucket_id,
            BucketPermission.user_id == user.id,
        )
    ).first()
    levels = {"view": 0, "edit": 1, "admin": 2}
    if not perm or levels.get(perm.permission, 0) < levels.get(min_perm, 0):
        raise HTTPException(status_code=403, detail="Insufficient bucket permissions")
    return bucket


def _is_lock_stale(locked_at: datetime | None) -> bool:
    if not locked_at:
        return True
    return datetime.utcnow() - locked_at > timedelta(minutes=LOCK_TIMEOUT_MINUTES)


def _bucket_document_ids_for_org(session, bucket_id: str, org_id: str) -> list[str]:
    rows = session.exec(select(BucketDocument).where(BucketDocument.bucket_id == bucket_id)).all()
    doc_ids: list[str] = []
    for bd in rows:
        doc = session.get(Document, bd.document_id)
        if doc and doc.organization_id == org_id:
            doc_ids.append(bd.document_id)
    return doc_ids


# ---------------------------------------------------------------------------
# Bucket CRUD
# ---------------------------------------------------------------------------

@router.get("")
async def list_buckets(
    across_orgs: bool = False,
    user: User = Depends(get_current_user),
):
    """List buckets visible to the current user.

    Default scope is the user's *active* organization.  When
    ``?across_orgs=true`` is passed, the response also includes buckets in:
      - every organization the user is a member of (via ``UserOrganization``)
      - every bucket the user has an explicit ``BucketPermission`` on
        (covers cross-org grants from the Phase 5 matrix)

    The response shape gains an ``organization_id`` / ``organization_name``
    column so the UI can show which org each bucket lives in.
    """
    init_db()
    with get_session() as session:
        if across_orgs:
            org_ids = {
                row.organization_id
                for row in session.exec(
                    select(UserOrganization).where(UserOrganization.user_id == user.id)
                ).all()
            }
            org_ids.add(user.organization_id)  # active org always included

            # Add orgs reached via explicit cross-org bucket grants
            granted_bucket_ids = [
                p.bucket_id for p in session.exec(
                    select(BucketPermission).where(BucketPermission.user_id == user.id)
                ).all()
            ]
            if granted_bucket_ids:
                for b in session.exec(
                    select(Bucket).where(Bucket.id.in_(granted_bucket_ids))
                ).all():
                    org_ids.add(b.organization_id)

            buckets = session.exec(
                select(Bucket).where(Bucket.organization_id.in_(list(org_ids) or ["__none__"]))
            ).all()

            org_names = {
                o.id: o.name
                for o in session.exec(
                    select(Organization).where(
                        Organization.id.in_(list(org_ids) or ["__none__"])
                    )
                ).all()
            }
        else:
            buckets = session.exec(
                select(Bucket).where(Bucket.organization_id == user.organization_id)
            ).all()
            org = session.get(Organization, user.organization_id)
            org_names = {user.organization_id: org.name if org else ""}

        result = []
        for b in buckets:
            # Workflow-state counts respect the bucket's own org scope.
            visible_doc_ids = set(
                _bucket_document_ids_for_org(session, b.id, b.organization_id)
            )
            states = {}
            for st in ("open", "pending", "locked", "closed"):
                cnt = 0
                for bd in session.exec(
                    select(BucketDocument).where(
                        BucketDocument.bucket_id == b.id,
                        BucketDocument.workflow_state == st,
                    )
                ).all():
                    if bd.document_id in visible_doc_ids:
                        cnt += 1
                states[st] = cnt
            result.append({
                "id": b.id, "name": b.name, "description": b.description,
                "created_at": str(b.created_at), "states": states,
                "total": sum(states.values()),
                "organization_id": b.organization_id,
                "organization_name": org_names.get(b.organization_id, ""),
            })
    return result


@router.post("")
async def create_bucket(body: BucketCreate, user: User = Depends(require_manager)):
    init_db()
    with get_session() as session:
        bucket = Bucket(
            id=str(uuid.uuid4()), name=body.name, description=body.description,
            organization_id=user.organization_id, created_by=user.id,
            created_at=datetime.utcnow(),
        )
        session.add(bucket)
        bucket_id = bucket.id
        bucket_name = bucket.name
        session.commit()
    return {"id": bucket_id, "name": bucket_name}


@router.get("/{bucket_id}")
async def get_bucket(bucket_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        bucket = _user_can_access_bucket(session, bucket_id, user)
        states = {}
        visible_doc_ids = set(_bucket_document_ids_for_org(session, bucket_id, user.organization_id))
        for st in ("open", "pending", "locked", "closed"):
            states[st] = sum(
                1 for bd in session.exec(
                    select(BucketDocument).where(BucketDocument.bucket_id == bucket_id, BucketDocument.workflow_state == st)
                ).all()
                if bd.document_id in visible_doc_ids
            )
        rules = session.exec(select(BucketRule).where(BucketRule.bucket_id == bucket_id)).all()
        return {
            "id": bucket.id, "name": bucket.name, "description": bucket.description,
            "created_at": str(bucket.created_at), "states": states, "total": sum(states.values()),
            "rules": [{"id": r.id, "field": r.field, "operator": r.operator, "value": r.value} for r in rules],
        }


@router.put("/{bucket_id}")
async def update_bucket(bucket_id: str, body: BucketUpdate, user: User = Depends(require_manager)):
    with get_session() as session:
        bucket = _user_can_access_bucket(session, bucket_id, user, "admin")
        if body.name is not None:
            bucket.name = body.name
        if body.description is not None:
            bucket.description = body.description
        session.add(bucket)
        session.commit()
    return {"status": "updated"}


@router.delete("/{bucket_id}")
async def delete_bucket(bucket_id: str, user: User = Depends(require_manager)):
    with get_session() as session:
        bucket = _user_can_access_bucket(session, bucket_id, user, "admin")
        for bd in session.exec(select(BucketDocument).where(BucketDocument.bucket_id == bucket_id)).all():
            session.delete(bd)
        for br in session.exec(select(BucketRule).where(BucketRule.bucket_id == bucket_id)).all():
            session.delete(br)
        for bp in session.exec(select(BucketPermission).where(BucketPermission.bucket_id == bucket_id)).all():
            session.delete(bp)
        session.delete(bucket)
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Bucket documents
# ---------------------------------------------------------------------------

@router.get("/{bucket_id}/documents")
async def list_bucket_documents(
    bucket_id: str,
    workflow_state: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        bucket = _user_can_access_bucket(session, bucket_id, user)
        query = select(BucketDocument).where(BucketDocument.bucket_id == bucket_id)
        if workflow_state:
            query = query.where(BucketDocument.workflow_state == workflow_state)
        all_bds = session.exec(query).all()
        bds = [
            bd for bd in all_bds
            if (doc := session.get(Document, bd.document_id)) and doc.organization_id == bucket.organization_id
        ]
        total = len(bds)
        bds = bds[(page - 1) * page_size:page * page_size]

        result = []
        for bd in bds:
            doc = session.get(Document, bd.document_id)
            lock_stale = _is_lock_stale(bd.locked_at) if bd.locked_by else False
            if lock_stale and bd.locked_by:
                bd.workflow_state = "open"
                bd.locked_by = None
                bd.locked_at = None
                session.add(bd)

            locker_name = None
            if bd.locked_by:
                locker = session.get(User, bd.locked_by)
                locker_name = locker.full_name if locker else None

            company_name = None
            client_name = None
            if doc:
                links = session.exec(
                    select(DocumentEntity).where(DocumentEntity.document_id == doc.id)
                ).all()
                for lnk in links:
                    ent = session.get(Entity, lnk.entity_id)
                    if not ent:
                        continue
                    role = (lnk.role or "").lower()
                    etype = (ent.entity_type or "").lower()
                    if role in ("issuer", "seller", "vendor", "supplier") or (etype == "company" and not company_name):
                        company_name = ent.name
                    if role in ("recipient", "client", "buyer", "customer") or (etype == "person" and role not in ("issuer", "seller", "vendor", "supplier", "contact") and not client_name):
                        client_name = ent.name

            result.append({
                "id": bd.id, "document_id": bd.document_id,
                "workflow_state": bd.workflow_state,
                "locked_by": bd.locked_by, "locked_by_name": locker_name,
                "locked_at": str(bd.locked_at) if bd.locked_at else None,
                "filename": doc.filename if doc else None,
                "classification_label": doc.classification_label if doc else None,
                "classification_subcategory_label": doc.classification_subcategory_label if doc else None,
                "classification_path": doc.classification_path if doc else None,
                "status": doc.status if doc else None,
                "created_at": str(doc.created_at) if doc else None,
                "company_name": company_name,
                "client_name": client_name,
            })
        session.commit()
    return {"total": total, "page": page, "page_size": page_size, "documents": result}


# ---------------------------------------------------------------------------
# Document state and locking
# ---------------------------------------------------------------------------

@router.put("/{bucket_id}/documents/{doc_id}/state")
async def change_document_state(
    bucket_id: str, doc_id: str, body: StateChange,
    user: User = Depends(get_current_user),
):
    if body.workflow_state not in ("open", "pending", "locked", "closed"):
        raise HTTPException(status_code=400, detail="Invalid state")
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "edit")
        bd = session.exec(
            select(BucketDocument).where(
                BucketDocument.bucket_id == bucket_id,
                BucketDocument.document_id == doc_id,
            )
        ).first()
        if not bd:
            raise HTTPException(status_code=404, detail="Document not in bucket")
        bd.workflow_state = body.workflow_state
        if body.workflow_state != "locked":
            bd.locked_by = None
            bd.locked_at = None
        workflow_state_out = bd.workflow_state
        session.add(bd)
        session.commit()
    return {"status": "updated", "workflow_state": workflow_state_out}


@router.post("/{bucket_id}/documents/{doc_id}/lock")
async def lock_document(bucket_id: str, doc_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "edit")
        bd = session.exec(
            select(BucketDocument).where(
                BucketDocument.bucket_id == bucket_id,
                BucketDocument.document_id == doc_id,
            )
        ).first()
        if not bd:
            raise HTTPException(status_code=404, detail="Document not in bucket")
        if bd.locked_by and bd.locked_by != user.id and not _is_lock_stale(bd.locked_at):
            locker = session.get(User, bd.locked_by)
            name = locker.full_name if locker else "another user"
            raise HTTPException(status_code=409, detail=f"Document locked by {name}")
        bd.workflow_state = "locked"
        bd.locked_by = user.id
        bd.locked_at = datetime.utcnow()
        session.add(bd)
        session.commit()
    return {"status": "locked", "locked_by": user.id}


@router.post("/{bucket_id}/documents/{doc_id}/unlock")
async def unlock_document(bucket_id: str, doc_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "edit")
        bd = session.exec(
            select(BucketDocument).where(
                BucketDocument.bucket_id == bucket_id,
                BucketDocument.document_id == doc_id,
            )
        ).first()
        if not bd:
            raise HTTPException(status_code=404, detail="Document not in bucket")
        if bd.locked_by and bd.locked_by != user.id and user.role != "admin":
            raise HTTPException(status_code=403, detail="Only lock owner or admin can unlock")
        bd.workflow_state = "open"
        bd.locked_by = None
        bd.locked_at = None
        session.add(bd)
        session.commit()
    return {"status": "unlocked"}


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@router.get("/{bucket_id}/rules")
async def list_rules(bucket_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user)
        rules = session.exec(select(BucketRule).where(BucketRule.bucket_id == bucket_id)).all()
        return [{"id": r.id, "field": r.field, "operator": r.operator, "value": r.value} for r in rules]


@router.post("/{bucket_id}/rules")
async def create_rule(bucket_id: str, body: RuleCreate, user: User = Depends(require_manager)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "admin")
        rule = BucketRule(
            id=str(uuid.uuid4()), bucket_id=bucket_id,
            field=body.field, operator=body.operator, value=body.value,
        )
        session.add(rule)
        rule_id = rule.id
        rule_field = rule.field
        rule_operator = rule.operator
        rule_value = rule.value
        session.commit()
    return {
        "id": rule_id, "field": rule_field, "operator": rule_operator, "value": rule_value,
    }


@router.delete("/{bucket_id}/rules/{rule_id}")
async def delete_rule(bucket_id: str, rule_id: str, user: User = Depends(require_manager)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "admin")
        rule = session.get(BucketRule, rule_id)
        if not rule or rule.bucket_id != bucket_id:
            raise HTTPException(status_code=404, detail="Rule not found")
        session.delete(rule)
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

@router.get("/{bucket_id}/permissions")
async def list_permissions(bucket_id: str, user: User = Depends(require_manager)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "admin")
        perms = session.exec(select(BucketPermission).where(BucketPermission.bucket_id == bucket_id)).all()
        result = []
        for p in perms:
            u = session.get(User, p.user_id)
            result.append({
                "id": p.id, "user_id": p.user_id,
                "user_name": u.full_name if u else None,
                "user_email": u.email if u else None,
                "permission": p.permission,
            })
    return result


@router.post("/{bucket_id}/permissions")
async def create_permission(bucket_id: str, body: PermissionCreate, user: User = Depends(require_manager)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "admin")
        target_user = session.get(User, body.user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found in your organization")
        # Verify the target user is a member of the active org (handles multi-org members)
        member = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == body.user_id,
                UserOrganization.organization_id == user.organization_id,
            )
        ).first()
        if not member:
            raise HTTPException(status_code=404, detail="User not found in your organization")
        existing = session.exec(
            select(BucketPermission).where(
                BucketPermission.bucket_id == bucket_id,
                BucketPermission.user_id == body.user_id,
            )
        ).first()
        if existing:
            existing.permission = body.permission
            session.add(existing)
            existing_id = existing.id
            session.commit()
            return {"id": existing_id, "status": "updated"}
        perm = BucketPermission(
            id=str(uuid.uuid4()), bucket_id=bucket_id,
            user_id=body.user_id, permission=body.permission,
        )
        session.add(perm)
        perm_id = perm.id
        session.commit()
    return {"id": perm_id, "status": "created"}


@router.delete("/{bucket_id}/permissions/{perm_id}")
async def delete_permission(bucket_id: str, perm_id: str, user: User = Depends(require_manager)):
    with get_session() as session:
        _user_can_access_bucket(session, bucket_id, user, "admin")
        perm = session.get(BucketPermission, perm_id)
        if not perm or perm.bucket_id != bucket_id:
            raise HTTPException(status_code=404, detail="Permission not found")
        session.delete(perm)
        session.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Auto-assignment
# ---------------------------------------------------------------------------

@router.post("/assign")
async def assign_documents(user: User = Depends(require_manager)):
    """Evaluate all bucket rules and assign matching completed documents."""
    init_db()
    with get_session() as session:
        buckets = session.exec(
            select(Bucket).where(Bucket.organization_id == user.organization_id)
        ).all()
        assigned_count = 0
        for bucket in buckets:
            rules = session.exec(
                select(BucketRule).where(BucketRule.bucket_id == bucket.id)
            ).all()
            if not rules:
                continue

            docs = session.exec(
                select(Document).where(
                    Document.organization_id == user.organization_id,
                    Document.status == "COMPLETED",
                )
            ).all()

            for doc in docs:
                already = session.exec(
                    select(BucketDocument).where(
                        BucketDocument.bucket_id == bucket.id,
                        BucketDocument.document_id == doc.id,
                    )
                ).first()
                if already:
                    continue

                if await _document_matches_rules(session, doc, rules):
                    bd = BucketDocument(
                        id=str(uuid.uuid4()), bucket_id=bucket.id,
                        document_id=doc.id, workflow_state="open",
                        created_at=datetime.utcnow(),
                    )
                    session.add(bd)
                    assigned_count += 1
        # Low-confidence bucket auto-assignment
        lc_assigned = _assign_low_confidence_bucket(session, user.organization_id, user.id)
        assigned_count += lc_assigned

        session.commit()
    return {"status": "assigned", "count": assigned_count}


def _assign_low_confidence_bucket(session, org_id: str, user_id: str) -> int:
    """Auto-assign documents below the confidence threshold to a 'Low Confidence' bucket."""
    enabled_row = session.get(SystemConfig, "low_confidence_bucket_enabled")
    if not enabled_row or enabled_row.value.lower() not in ("true", "1", "yes"):
        return 0
    threshold_row = session.get(SystemConfig, "low_confidence_threshold")
    threshold = float(threshold_row.value) if threshold_row else 0.5

    lc_bucket = session.exec(
        select(Bucket).where(
            Bucket.organization_id == org_id,
            Bucket.name == "Low Confidence",
        )
    ).first()
    if not lc_bucket:
        lc_bucket = Bucket(
            id=str(uuid.uuid4()), name="Low Confidence",
            description="Documents with pipeline confidence below threshold",
            organization_id=org_id, created_by=user_id,
            created_at=datetime.utcnow(),
        )
        session.add(lc_bucket)
        session.flush()

    docs = session.exec(
        select(Document).where(
            Document.organization_id == org_id,
            Document.status == "COMPLETED",
            Document.pipeline_confidence.isnot(None),
            Document.pipeline_confidence < threshold,
        )
    ).all()
    count = 0
    for doc in docs:
        already = session.exec(
            select(BucketDocument).where(
                BucketDocument.bucket_id == lc_bucket.id,
                BucketDocument.document_id == doc.id,
            )
        ).first()
        if already:
            continue
        session.add(BucketDocument(
            id=str(uuid.uuid4()), bucket_id=lc_bucket.id,
            document_id=doc.id, workflow_state="open",
            created_at=datetime.utcnow(),
        ))
        count += 1
    return count


async def _document_matches_rules(session, doc: Document, rules: list[BucketRule]) -> bool:
    standard_rules = [r for r in rules if not _is_llm_rule(r)]
    llm_rules = [r for r in rules if _is_llm_rule(r)]

    for rule in standard_rules:
        val = _get_field_value(session, doc, rule.field)
        if val is None:
            return False
        if not _value_matches_rule(val, rule):
            return False

    for rule in llm_rules:
        if not await _vision_rule_matches(doc, rule):
            return False
    return True


def _is_llm_rule(rule: BucketRule) -> bool:
    return rule.field in {"llm_vision", "vision_llm", "llm:image"}


def _value_matches_rule(val: str, rule: BucketRule) -> bool:
    value = str(val).lower()
    expected = rule.value.lower()
    if rule.operator == "equals":
        return value == expected
    if rule.operator == "contains":
        return expected in value
    if rule.operator == "in":
        return value in [v.strip().lower() for v in rule.value.split(",")]
    return False


def _get_field_value(session, doc: Document, field_spec: str) -> str | None:
    if field_spec == "classification_label":
        return doc.classification_label
    if field_spec == "classification_subcategory_label":
        return doc.classification_subcategory_label
    if field_spec == "classification_path":
        if not doc.classification_path:
            return None
        try:
            path = json.loads(doc.classification_path)
            if isinstance(path, list):
                return " / ".join(str(part) for part in path)
        except (json.JSONDecodeError, TypeError):
            pass
        return doc.classification_path
    if field_spec == "mode":
        return doc.mode
    if field_spec == "status":
        return doc.status
    if field_spec.startswith("field:"):
        fname = field_spec[6:]
        df = session.exec(
            select(DocumentField).where(
                DocumentField.document_id == doc.id,
                DocumentField.field_name == fname,
            )
        ).first()
        return df.field_value if df else None
    if field_spec.startswith("entity_type:"):
        etype = field_spec[12:]
        link = session.exec(
            select(DocumentEntity).where(DocumentEntity.document_id == doc.id)
        ).all()
        for lnk in link:
            ent = session.get(Entity, lnk.entity_id)
            if ent and ent.entity_type == etype:
                return ent.name
        return None
    return None


async def _vision_rule_matches(doc: Document, rule: BucketRule) -> bool:
    if not doc.storage_path or not os.path.exists(doc.storage_path):
        return False
    try:
        image_b64 = _render_first_page_for_vision(doc.storage_path)
        prompt = VISION_RULE_PROMPT.format(
            rule=rule.value,
            filename=doc.filename,
            classification_label=doc.classification_label or "",
            classification_subcategory_label=doc.classification_subcategory_label or "",
            classification_path=_get_classification_path_label(doc),
        )
        from dmsai_models.llm import call_vision_llm

        raw = await call_vision_llm(image_b64, prompt=prompt)
        result = _parse_llm_json(raw)
        matched = bool(result.get("match", False))
        if rule.operator == "does_not_match":
            return not matched
        return matched
    except Exception:
        return False


def _get_classification_path_label(doc: Document) -> str:
    if not doc.classification_path:
        return ""
    try:
        path = json.loads(doc.classification_path)
        if isinstance(path, list):
            return " / ".join(str(part) for part in path)
    except (json.JSONDecodeError, TypeError):
        pass
    return doc.classification_path


def _render_first_page_for_vision(path: str) -> str:
    import base64
    import fitz

    with fitz.open(path) as pdf:
        if pdf.page_count < 1:
            raise ValueError("Document PDF has no pages")
        page = pdf.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        return base64.b64encode(pix.tobytes("png")).decode("ascii")


def _parse_llm_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                parsed = json.loads(text[start:end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}


# ---------------------------------------------------------------------------
# Internal auto-assign (called by pipeline nodes, protected by shared secret)
# ---------------------------------------------------------------------------

@router.post("/auto-assign")
async def auto_assign_documents(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=503, detail="Internal API key is not configured")
    if x_internal_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing internal API key")
    """Internal endpoint: run bucket rule assignment across all orgs."""
    init_db()
    import logging
    _logger = logging.getLogger("buckets.auto_assign")
    with get_session() as session:
        buckets = session.exec(select(Bucket)).all()
        assigned_count = 0
        for bucket in buckets:
            rules = session.exec(
                select(BucketRule).where(BucketRule.bucket_id == bucket.id)
            ).all()
            if not rules:
                continue
            docs = session.exec(
                select(Document).where(
                    Document.organization_id == bucket.organization_id,
                    Document.status == "COMPLETED",
                )
            ).all()
            for doc in docs:
                already = session.exec(
                    select(BucketDocument).where(
                        BucketDocument.bucket_id == bucket.id,
                        BucketDocument.document_id == doc.id,
                    )
                ).first()
                if already:
                    continue
                if await _document_matches_rules(session, doc, rules):
                    bd = BucketDocument(
                        id=str(uuid.uuid4()), bucket_id=bucket.id,
                        document_id=doc.id, workflow_state="open",
                        created_at=datetime.utcnow(),
                    )
                    session.add(bd)
                    assigned_count += 1

        lc_assigned = _auto_assign_low_confidence(session)
        assigned_count += lc_assigned

        session.commit()
    _logger.info(f"Auto-assign completed: {assigned_count} documents assigned")
    return {"status": "assigned", "count": assigned_count}


def _auto_assign_low_confidence(session) -> int:
    """Assign low-confidence docs across all orgs (internal, no user context)."""
    enabled_row = session.get(SystemConfig, "low_confidence_bucket_enabled")
    if not enabled_row or enabled_row.value.lower() not in ("true", "1", "yes"):
        return 0
    threshold_row = session.get(SystemConfig, "low_confidence_threshold")
    threshold = float(threshold_row.value) if threshold_row else 0.5

    docs = session.exec(
        select(Document).where(
            Document.organization_id.isnot(None),
            Document.status == "COMPLETED",
            Document.pipeline_confidence.isnot(None),
            Document.pipeline_confidence < threshold,
        )
    ).all()
    if not docs:
        return 0

    org_buckets: dict[str, Bucket] = {}
    count = 0
    for doc in docs:
        org_id = doc.organization_id
        if not org_id:
            continue
        if org_id not in org_buckets:
            lc_bucket = session.exec(
                select(Bucket).where(Bucket.name == "Low Confidence", Bucket.organization_id == org_id)
            ).first()
            if not lc_bucket:
                lc_bucket = Bucket(
                    id=str(uuid.uuid4()), name="Low Confidence",
                    description="Documents with pipeline confidence below threshold",
                    organization_id=org_id, created_by="system",
                    created_at=datetime.utcnow(),
                )
                session.add(lc_bucket)
                session.flush()
            org_buckets[org_id] = lc_bucket

        bucket = org_buckets[org_id]
        already = session.exec(
            select(BucketDocument).where(
                BucketDocument.bucket_id == bucket.id,
                BucketDocument.document_id == doc.id,
            )
        ).first()
        if already:
            continue
        session.add(BucketDocument(
            id=str(uuid.uuid4()), bucket_id=bucket.id,
            document_id=doc.id, workflow_state="open",
            created_at=datetime.utcnow(),
        ))
        count += 1
    return count
