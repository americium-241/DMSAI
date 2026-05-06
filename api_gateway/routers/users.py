from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import select, func

from dmsai_models import Organization, User, UserOrganization, SystemConfig, get_session, init_db
from auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin, require_manager,
    validate_password, generate_verification_token,
    is_email_verification_enabled, is_registration_open,
    check_account_lock, record_failed_login, clear_failed_logins,
    _get_auth_config,
)
from email_utils import send_verification_email
from ldap_auth import authenticate_ldap, is_ldap_enabled

router = APIRouter(prefix="/api", tags=["auth", "users"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    organization_name: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class OrgUpdate(BaseModel):
    name: str


class ResendVerificationRequest(BaseModel):
    email: str


class SwitchOrgRequest(BaseModel):
    org_id: str


def _get_user_orgs(session, user_id: str) -> list[dict]:
    """Return all organizations the user belongs to with their per-org role."""
    memberships = session.exec(
        select(UserOrganization).where(UserOrganization.user_id == user_id)
    ).all()
    result = []
    for m in memberships:
        org = session.get(Organization, m.organization_id)
        if org:
            result.append({
                "organization_id": m.organization_id,
                "organization_name": org.name,
                "role": m.role,
                "is_default": m.is_default,
            })
    return result


def _build_user_response(user_id, user_email, user_full_name, user_role, org_id, org_name,
                          *, email_verified=True, auth_provider="local", organizations=None):
    return {
        "id": user_id,
        "email": user_email,
        "full_name": user_full_name,
        "role": user_role,
        "organization_id": org_id,
        "organization_name": org_name,
        "email_verified": email_verified,
        "auth_provider": auth_provider,
        "organizations": organizations or [],
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/auth/login")
async def login(body: LoginRequest):
    init_db()

    # --- Try LDAP first if enabled ---
    if is_ldap_enabled():
        ldap_info = authenticate_ldap(body.email, body.password)
        if ldap_info:
            return await _handle_ldap_login(ldap_info)

    # --- Local auth ---
    with get_session() as session:
        user = session.exec(select(User).where(User.email == body.email)).first()
        if not user or user.auth_provider != "local":
            if user and user.auth_provider != "local":
                raise HTTPException(
                    status_code=400,
                    detail=f"This account uses {user.auth_provider} authentication. "
                           f"Please log in via {user.auth_provider}.",
                )
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

        lock_msg = check_account_lock(user)
        if lock_msg:
            raise HTTPException(status_code=429, detail=lock_msg)

        if not verify_password(body.password, user.password_hash):
            session.expunge(user)
            record_failed_login(user)
            raise HTTPException(status_code=401, detail="Invalid email or password")

        session.expunge(user)
        clear_failed_logins(user)

    verification_enabled = is_email_verification_enabled()
    if verification_enabled and not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Please check your inbox or request a new verification link.",
        )

    with get_session() as session:
        u = session.get(User, user.id)
        u.last_login_at = datetime.utcnow()
        session.add(u)
        org = session.get(Organization, u.organization_id)
        org_name = org.name if org else None
        # Ensure UserOrganization row exists (backward compat)
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == u.id,
                UserOrganization.organization_id == u.organization_id,
            )
        ).first()
        if not membership:
            session.add(UserOrganization(
                id=str(uuid.uuid4()),
                user_id=u.id,
                organization_id=u.organization_id,
                role=u.role,
                is_default=True,
                joined_at=datetime.utcnow(),
            ))
        orgs = _get_user_orgs(session, u.id)
        session.commit()

    token = create_access_token(user.id, user.email, user.role, user.organization_id)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _build_user_response(
            user.id, user.email, user.full_name, user.role,
            user.organization_id, org_name,
            email_verified=user.email_verified,
            auth_provider=user.auth_provider,
            organizations=orgs,
        ),
    }


async def _handle_ldap_login(ldap_info):
    """Auto-provision or update LDAP user and return a JWT."""
    cfg = _get_auth_config()
    default_org_name = cfg.get("ldap_default_organization", "LDAP Users")
    default_role = cfg.get("ldap_default_role", "user")

    with get_session() as session:
        user = session.exec(select(User).where(User.email == ldap_info.email)).first()
        if user:
            user.full_name = ldap_info.full_name
            user.last_login_at = datetime.utcnow()
            user.failed_login_attempts = 0
            user.locked_until = None
            session.add(user)
        else:
            org = session.exec(
                select(Organization).where(Organization.name == default_org_name)
            ).first()
            if not org:
                org = Organization(
                    id=str(uuid.uuid4()),
                    name=default_org_name,
                    created_at=datetime.utcnow(),
                )
                session.add(org)
                session.flush()

            user = User(
                id=str(uuid.uuid4()),
                email=ldap_info.email,
                password_hash="",
                full_name=ldap_info.full_name,
                role=default_role if default_role in ("user", "manager", "admin") else "user",
                organization_id=org.id,
                is_active=True,
                auth_provider="ldap",
                email_verified=True,
                created_at=datetime.utcnow(),
                last_login_at=datetime.utcnow(),
            )
            session.add(user)

        session.flush()
        # Ensure UserOrganization row exists
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.organization_id == user.organization_id,
            )
        ).first()
        if not membership:
            session.add(UserOrganization(
                id=str(uuid.uuid4()),
                user_id=user.id,
                organization_id=user.organization_id,
                role=user.role,
                is_default=True,
                joined_at=datetime.utcnow(),
            ))
        org = session.get(Organization, user.organization_id)
        org_name = org.name if org else None
        user_id = user.id
        user_email = user.email
        user_full_name = user.full_name
        user_role = user.role
        user_org_id = user.organization_id
        orgs = _get_user_orgs(session, user.id)
        session.commit()

    token = create_access_token(user_id, user_email, user_role, user_org_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _build_user_response(
            user_id, user_email, user_full_name, user_role,
            user_org_id, org_name,
            email_verified=True, auth_provider="ldap",
            organizations=orgs,
        ),
    }


@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request):
    init_db()

    if not is_registration_open():
        raise HTTPException(status_code=403, detail="Self-service registration is disabled. Contact an administrator.")

    pw_error = validate_password(body.password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)

    verification_enabled = is_email_verification_enabled()

    with get_session() as session:
        existing = session.exec(select(User).where(User.email == body.email)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        total_users = session.exec(select(func.count()).select_from(User)).one()
        is_first_user = total_users == 0

        if is_first_user:
            # Bootstrap: first user creates the initial organization and becomes its admin.
            org_name = body.organization_name or "Default Organization"
            org = Organization(
                id=str(uuid.uuid4()),
                name=org_name,
                created_at=datetime.utcnow(),
            )
            session.add(org)
            session.flush()
            org_id = org.id
            role = "admin"
        else:
            # Subsequent users must JOIN an existing organization as a regular user.
            # New organizations can only be created by an administrator via the admin API.
            if not body.organization_name:
                raise HTTPException(
                    status_code=400,
                    detail="organization_name is required. Provide the exact name of your organization.",
                )
            existing_org = session.exec(
                select(Organization).where(Organization.name == body.organization_name)
            ).first()
            if not existing_org:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Organization not found. "
                        "Contact an administrator to create your account or to create the organization."
                    ),
                )
            org_id = existing_org.id
            org_name = existing_org.name
            # Always a regular user — admins must promote via PUT /api/users/{id}
            role = "user"

        verification_token = generate_verification_token() if verification_enabled else None
        mark_verified = is_first_user or not verification_enabled

        user = User(
            id=str(uuid.uuid4()),
            email=body.email,
            password_hash=hash_password(body.password),
            full_name=body.full_name,
            role=role,
            organization_id=org_id,
            is_active=True,
            auth_provider="local",
            email_verified=mark_verified,
            email_verification_token=verification_token,
            email_verification_sent_at=datetime.utcnow() if verification_token else None,
            created_at=datetime.utcnow(),
        )
        session.add(user)
        session.flush()
        # Create UserOrganization membership
        session.add(UserOrganization(
            id=str(uuid.uuid4()),
            user_id=user.id,
            organization_id=org_id,
            role=role,
            is_default=True,
            joined_at=datetime.utcnow(),
        ))
        user_id = user.id
        user_email = user.email
        user_full_name = user.full_name
        user_role = role
        session.commit()

    new_org_membership = [{"organization_id": org_id, "organization_name": org_name,
                            "role": user_role, "is_default": True}]

    if verification_enabled and not mark_verified:
        base_url = str(request.base_url).rstrip("/")
        send_verification_email(user_email, user_full_name, verification_token, base_url)
        return {
            "status": "verification_required",
            "message": "Account created. Please check your email to verify your address.",
            "user": _build_user_response(
                user_id, user_email, user_full_name, user_role,
                org_id, org_name, email_verified=False, organizations=new_org_membership,
            ),
        }

    token = create_access_token(user_id, user_email, user_role, org_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _build_user_response(
            user_id, user_email, user_full_name, user_role,
            org_id, org_name, email_verified=True, organizations=new_org_membership,
        ),
    }


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@router.get("/auth/verify-email")
async def verify_email(token: str):
    """Verify a user's email address via the token sent in the verification
    email.  Returns an HTML page so it works when the user clicks the link
    directly from their email client."""
    with get_session() as session:
        user = session.exec(
            select(User).where(User.email_verification_token == token)
        ).first()
        if not user:
            return HTMLResponse(
                _verification_html("Verification Failed",
                                   "Invalid or expired verification link.",
                                   success=False),
                status_code=400,
            )

        cfg_row = session.exec(
            select(SystemConfig).where(SystemConfig.key == "email_verification_token_expiry_hours")
        ).first()
        expiry_hours = int(cfg_row.value) if cfg_row else 24

        if user.email_verification_sent_at:
            age = datetime.utcnow() - user.email_verification_sent_at
            if age.total_seconds() > expiry_hours * 3600:
                return HTMLResponse(
                    _verification_html("Link Expired",
                                       "This verification link has expired. Please request a new one.",
                                       success=False),
                    status_code=400,
                )

        user.email_verified = True
        user.email_verification_token = None
        user.email_verification_sent_at = None
        session.add(user)
        session.commit()

    return HTMLResponse(
        _verification_html("Email Verified",
                           "Your email has been verified. You can now log in.",
                           success=True),
    )


@router.post("/auth/resend-verification")
async def resend_verification(body: ResendVerificationRequest, request: Request):
    with get_session() as session:
        user = session.exec(select(User).where(User.email == body.email)).first()
        if not user:
            return {"status": "ok", "message": "If the email exists, a verification link has been sent."}
        if user.email_verified:
            return {"status": "ok", "message": "Email is already verified."}

        new_token = generate_verification_token()
        user.email_verification_token = new_token
        user.email_verification_sent_at = datetime.utcnow()
        session.add(user)
        session.commit()

    base_url = str(request.base_url).rstrip("/")
    send_verification_email(user.email, user.full_name, new_token, base_url)
    return {"status": "ok", "message": "If the email exists, a verification link has been sent."}


def _verification_html(title: str, message: str, *, success: bool) -> str:
    color = "#22c55e" if success else "#ef4444"
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title} — DMSAI</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0a0a0a; color: #e5e5e5;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .card {{ background: #171717; border: 1px solid #262626; border-radius: 12px; padding: 40px;
           max-width: 440px; text-align: center; }}
  h1 {{ color: {color}; margin-top: 0; }}
  a {{ color: #3b82f6; text-decoration: none; }}
</style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{message}</p>
    <p style="margin-top:24px;"><a href="/login">Go to Login</a></p>
  </div>
</body>
</html>"""


@router.get("/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    with get_session() as session:
        org = session.get(Organization, user.organization_id)
        org_name = org.name if org else None
        orgs = _get_user_orgs(session, user.id)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "organization_id": user.organization_id,
        "organization_name": org_name,
        "is_active": user.is_active,
        "email_verified": user.email_verified,
        "auth_provider": user.auth_provider,
        "organizations": orgs,
    }


@router.get("/auth/organizations")
async def list_my_organizations(user: User = Depends(get_current_user)):
    """List all organizations the current user belongs to."""
    with get_session() as session:
        return _get_user_orgs(session, user.id)


@router.post("/auth/switch-org")
async def switch_org(body: SwitchOrgRequest, user: User = Depends(get_current_user)):
    """Issue a new JWT scoped to a different organization the user belongs to."""
    with get_session() as session:
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.organization_id == body.org_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=403, detail="You are not a member of this organization")
        org = session.get(Organization, body.org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        orgs = _get_user_orgs(session, user.id)

    token = create_access_token(user.id, user.email, membership.role, body.org_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _build_user_response(
            user.id, user.email, user.full_name, membership.role,
            body.org_id, org.name,
            email_verified=user.email_verified,
            auth_provider=user.auth_provider,
            organizations=orgs,
        ),
    }


# ---------------------------------------------------------------------------
# Auth provider info (public)
# ---------------------------------------------------------------------------

@router.get("/auth/providers")
async def auth_providers():
    """Return which authentication methods are available so the frontend
    can adjust the login UI accordingly."""
    return {
        "local": True,
        "ldap": is_ldap_enabled(),
        "registration_open": is_registration_open(),
        "email_verification": is_email_verification_enabled(),
    }


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(current: User = Depends(require_manager)):
    """List all users who are members of the current active organization."""
    with get_session() as session:
        # Use UserOrganization so multi-org members are visible in each org they belong to
        memberships = session.exec(
            select(UserOrganization).where(
                UserOrganization.organization_id == current.organization_id
            )
        ).all()
        user_ids = [m.user_id for m in memberships]
        # Build role-in-this-org map from memberships
        org_role_map = {m.user_id: m.role for m in memberships}

        users = session.exec(select(User).where(User.id.in_(user_ids))).all() if user_ids else []
        return [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": org_role_map.get(u.id, u.role),  # prefer org-specific role
                "is_active": u.is_active,
                "auth_provider": u.auth_provider,
                "email_verified": u.email_verified,
                "created_at": str(u.created_at),
                "last_login_at": str(u.last_login_at) if u.last_login_at else None,
            }
            for u in users
        ]


@router.put("/users/{user_id}")
async def update_user(user_id: str, body: UserUpdate, current: User = Depends(require_admin)):
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        # Verify the target user is a member of the admin's active org
        membership = session.exec(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == current.organization_id,
            )
        ).first()
        if not membership:
            raise HTTPException(status_code=404, detail="User not found")
        if body.full_name is not None:
            user.full_name = body.full_name
        if body.role is not None:
            if body.role not in ("admin", "manager", "user"):
                raise HTTPException(status_code=400, detail="role must be admin, manager, or user")
            if user_id == current.id and body.role != "admin":
                raise HTTPException(
                    status_code=400,
                    detail="You cannot demote your own admin account. Ask another admin to do this.",
                )
            # Update the org-specific role in UserOrganization
            membership.role = body.role
            session.add(membership)
            # Also sync to User.role if this is the user's home org
            if user.organization_id == current.organization_id:
                user.role = body.role
        if body.is_active is not None:
            if user_id == current.id and not body.is_active:
                raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
            user.is_active = body.is_active
        session.add(user)
        session.commit()
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Organization management
# ---------------------------------------------------------------------------

@router.get("/organization")
async def get_organization(current: User = Depends(get_current_user)):
    with get_session() as session:
        org = session.get(Organization, current.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        return {"id": org.id, "name": org.name, "created_at": str(org.created_at)}


@router.put("/organization")
async def update_organization(body: OrgUpdate, current: User = Depends(require_admin)):
    with get_session() as session:
        org = session.get(Organization, current.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        org.name = body.name
        updated_name = org.name
        session.add(org)
        session.commit()
    return {"status": "updated", "name": updated_name}
