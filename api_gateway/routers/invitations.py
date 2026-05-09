"""Invitation tokens — Phase 3 of the auth & permissions overhaul.

Workflow:

1. Admin creates an invitation: ``POST /api/admin/invitations`` returning a
   single-use token.  The admin shares ``/invite/<token>`` with the user.
2. The user opens the URL.  The frontend looks up the context with
   ``GET /api/invitations/{token}`` (public) so it can display "Join
   <Org Name> as <Role>".
3. The user picks a password and submits ``POST /api/invitations/{token}/redeem``,
   which creates the User row, the UserOrganization membership, and any
   prebound BucketPermission rows in a single transaction.  The token is
   marked redeemed and cannot be reused.

The token lives in ``Invitation.token`` and is generated with
``secrets.token_urlsafe(32)`` — high enough entropy to be used in plain URLs
without a separate authenticator.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from dmsai_models import (
    Bucket, BucketPermission, Invitation, Organization,
    User, UserOrganization, get_session, init_db,
)
from auth import (
    require_admin, hash_password, validate_password,
    create_access_token, normalize_role as _norm_role, VALID_ROLES,
)


router = APIRouter(prefix="/api", tags=["invitations"])

_DEFAULT_EXPIRY_DAYS = 7


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BucketGrant(BaseModel):
    bucket_id: str
    permission: str = "view"  # view | edit | admin


class InvitationCreate(BaseModel):
    organization_id: Optional[str] = None  # defaults to admin's home org
    role: str = "user"
    invited_email: Optional[str] = None
    full_name_hint: Optional[str] = None
    expires_in_days: int = _DEFAULT_EXPIRY_DAYS
    bucket_grants: List[BucketGrant] = []


class InvitationRedeem(BaseModel):
    password: str
    full_name: str


class InvitationOut(BaseModel):
    id: str
    token: str
    organization_id: str
    organization_name: str
    role: str
    invited_email: Optional[str]
    full_name_hint: Optional[str]
    bucket_grants: List[BucketGrant]
    expires_at: str
    redeemed_at: Optional[str]
    created_at: str
    invite_url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_invitation_url(token: str) -> str:
    """The frontend reads VITE_API_URL but the invite URL is a frontend
    route, not an API path.  We intentionally return only the path so the
    UI can prepend ``window.location.origin`` itself — that way it works
    correctly in dev (5173), behind a reverse proxy, and on custom domains.
    """
    return f"/invite/{token}"


def _serialize_invitation(inv: Invitation, org_name: str) -> InvitationOut:
    grants_raw = json.loads(inv.bucket_grants or "[]")
    grants = [BucketGrant(**g) for g in grants_raw]
    return InvitationOut(
        id=inv.id,
        token=inv.token,
        organization_id=inv.organization_id,
        organization_name=org_name,
        role=inv.role,
        invited_email=inv.invited_email,
        full_name_hint=inv.full_name_hint,
        bucket_grants=grants,
        expires_at=str(inv.expires_at),
        redeemed_at=str(inv.redeemed_at) if inv.redeemed_at else None,
        created_at=str(inv.created_at),
        invite_url=_build_invitation_url(inv.token),
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/admin/invitations",
    summary="Create invitation token",
    description=(
        "Generate a single-use invitation token.  The recipient redeems it via "
        "`/invite/<token>` to create their account with the prebound role and "
        "bucket permissions, without needing self-service registration to be open."
    ),
    response_model=InvitationOut,
)
async def admin_create_invitation(body: InvitationCreate, admin: User = Depends(require_admin)):
    init_db()
    role = _norm_role(body.role)
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {', '.join(VALID_ROLES)}")
    if body.expires_in_days < 1 or body.expires_in_days > 90:
        raise HTTPException(status_code=400, detail="expires_in_days must be between 1 and 90")

    target_org_id = body.organization_id or admin.organization_id
    with get_session() as session:
        org = session.get(Organization, target_org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Validate bucket grants — buckets must belong to an org the admin can manage.
        # System admin has free pass; other admins are scoped to their own org.
        for g in body.bucket_grants:
            bucket = session.get(Bucket, g.bucket_id)
            if not bucket:
                raise HTTPException(status_code=404, detail=f"Bucket {g.bucket_id} not found")
            if g.permission not in ("view", "edit", "admin"):
                raise HTTPException(status_code=400, detail="permission must be view/edit/admin")
            if admin.role != "admin" and bucket.organization_id != admin.organization_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"You cannot grant access to a bucket in another organization",
                )

        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            id=str(uuid.uuid4()),
            token=token,
            organization_id=target_org_id,
            role=role,
            bucket_grants=json.dumps([g.model_dump() for g in body.bucket_grants]),
            invited_email=body.invited_email,
            full_name_hint=body.full_name_hint,
            invited_by=admin.id,
            expires_at=datetime.utcnow() + timedelta(days=body.expires_in_days),
            created_at=datetime.utcnow(),
        )
        session.add(invitation)
        session.commit()
        session.refresh(invitation)
        return _serialize_invitation(invitation, org.name)


@router.get(
    "/admin/invitations",
    summary="List invitations",
    description="List all invitations the admin has issued (or all org's invitations if system admin).",
    response_model=List[InvitationOut],
)
async def admin_list_invitations(admin: User = Depends(require_admin)):
    init_db()
    with get_session() as session:
        query = select(Invitation).order_by(Invitation.created_at.desc())
        if admin.role != "admin":
            # Org-scoped admins only see invitations for their own org.
            query = query.where(Invitation.organization_id == admin.organization_id)
        invs = session.exec(query).all()
        org_names = {
            o.id: o.name
            for o in session.exec(select(Organization).where(
                Organization.id.in_([i.organization_id for i in invs] or ["__none__"])
            )).all()
        }
        return [_serialize_invitation(i, org_names.get(i.organization_id, "?")) for i in invs]


@router.delete(
    "/admin/invitations/{invitation_id}",
    summary="Revoke an invitation",
    description="Delete an unredeemed invitation token.  Already-redeemed invitations cannot be revoked.",
)
async def admin_revoke_invitation(invitation_id: str, admin: User = Depends(require_admin)):
    with get_session() as session:
        inv = session.get(Invitation, invitation_id)
        if not inv:
            raise HTTPException(status_code=404, detail="Invitation not found")
        if admin.role != "admin" and inv.organization_id != admin.organization_id:
            raise HTTPException(status_code=403, detail="Cross-organization access denied")
        if inv.redeemed_at is not None:
            raise HTTPException(status_code=400, detail="Cannot revoke a redeemed invitation")
        session.delete(inv)
        session.commit()
    return {"status": "revoked", "id": invitation_id}


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------

@router.get(
    "/invitations/{token}",
    summary="Look up invitation context",
    description=(
        "Public endpoint used by the redeem page to display 'Join <Org> as <Role>'. "
        "Returns 404 for unknown, expired, or already-redeemed tokens.  Does NOT "
        "leak any information beyond what the recipient already needs to onboard."
    ),
    response_model=InvitationOut,
)
async def lookup_invitation(token: str):
    init_db()
    with get_session() as session:
        inv = session.exec(select(Invitation).where(Invitation.token == token)).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Invitation not found")
        if inv.redeemed_at is not None:
            raise HTTPException(status_code=410, detail="Invitation has already been redeemed")
        if inv.expires_at < datetime.utcnow():
            raise HTTPException(status_code=410, detail="Invitation has expired")
        org = session.get(Organization, inv.organization_id)
        return _serialize_invitation(inv, org.name if org else "?")


@router.post(
    "/invitations/{token}/redeem",
    summary="Redeem invitation token",
    description=(
        "Accept the invitation and create the user account with the role and "
        "bucket permissions configured by the admin.  Returns an access token "
        "so the user is logged in immediately."
    ),
)
async def redeem_invitation(token: str, body: InvitationRedeem):
    init_db()
    pw_error = validate_password(body.password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)
    if not body.full_name.strip():
        raise HTTPException(status_code=400, detail="full_name is required")

    with get_session() as session:
        inv = session.exec(select(Invitation).where(Invitation.token == token)).first()
        if not inv:
            raise HTTPException(status_code=404, detail="Invitation not found")
        if inv.redeemed_at is not None:
            raise HTTPException(status_code=410, detail="Invitation has already been redeemed")
        if inv.expires_at < datetime.utcnow():
            raise HTTPException(status_code=410, detail="Invitation has expired")

        org = session.get(Organization, inv.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization no longer exists")

        # If the invite specified an email, the user MUST sign up with that
        # email — otherwise the account is created with whatever they provide.
        # We require email at signup either way: it's the primary key for login.
        # In this minimal flow we accept the email from the body via full_name,
        # but the invite_email is canonical when present.  To keep the API
        # narrow we use ``invited_email`` when set, and require redeemers to
        # acknowledge it via the frontend display.
        email = (inv.invited_email or "").strip().lower()
        if not email:
            raise HTTPException(
                status_code=400,
                detail="This invitation is missing an email address — ask the admin to recreate it.",
            )

        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            raise HTTPException(status_code=409, detail="A user with this email already exists")

        # Create the user
        user_id = str(uuid.uuid4())
        new_user = User(
            id=user_id,
            email=email,
            password_hash=hash_password(body.password),
            full_name=body.full_name.strip(),
            role=inv.role,
            organization_id=inv.organization_id,
            is_active=True,
            auth_provider="local",
            email_verified=True,  # invitation acts as proof of email ownership
            created_at=datetime.utcnow(),
        )
        session.add(new_user)

        # UserOrganization membership in the inviting org
        session.add(UserOrganization(
            id=str(uuid.uuid4()),
            user_id=user_id,
            organization_id=inv.organization_id,
            role=inv.role,
            is_default=True,
            joined_at=datetime.utcnow(),
        ))

        # Bucket grants
        grants_raw = json.loads(inv.bucket_grants or "[]")
        for g in grants_raw:
            bucket = session.get(Bucket, g["bucket_id"])
            if not bucket:
                continue  # silently skip stale grants
            # If the bucket is in a DIFFERENT org, also create a viewer
            # UserOrganization there so the user can resolve the bucket.
            if bucket.organization_id != inv.organization_id:
                existing_membership = session.exec(
                    select(UserOrganization).where(
                        UserOrganization.user_id == user_id,
                        UserOrganization.organization_id == bucket.organization_id,
                    )
                ).first()
                if not existing_membership:
                    session.add(UserOrganization(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        organization_id=bucket.organization_id,
                        role="viewer",
                        is_default=False,
                        joined_at=datetime.utcnow(),
                    ))
            session.add(BucketPermission(
                id=str(uuid.uuid4()),
                bucket_id=g["bucket_id"],
                user_id=user_id,
                permission=g.get("permission", "view"),
            ))

        # Mark invitation as redeemed
        inv.redeemed_at = datetime.utcnow()
        inv.redeemed_by_user_id = user_id
        session.add(inv)
        session.commit()

    access_token = create_access_token(user_id, email, inv.role, inv.organization_id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "full_name": body.full_name.strip(),
            "role": inv.role,
            "organization_id": inv.organization_id,
            "organization_name": org.name,
        },
    }
