from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt as _bcrypt
from sqlmodel import select

from dmsai_models import User, SystemConfig, get_session

_DEFAULT_SECRET = "dmsai-dev-secret-change-in-production"


def _resolve_jwt_secret() -> str:
    """Use env var if set, otherwise auto-generate a persistent secret file."""
    env = os.environ.get("DMSAI_JWT_SECRET", "")
    if env and env != _DEFAULT_SECRET:
        return env
    secret_path = os.path.join(os.path.dirname(__file__), ".jwt_secret")
    if os.path.isfile(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()
    new_secret = secrets.token_hex(32)
    try:
        with open(secret_path, "w") as f:
            f.write(new_secret)
    except OSError:
        pass
    return new_secret


SECRET_KEY = _resolve_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_auth_config() -> dict:
    with get_session() as session:
        rows = session.query(SystemConfig).filter(
            SystemConfig.category.in_(["auth", "email", "ldap"])
        ).all()
    return {r.key: r.value for r in rows}


def is_email_verification_enabled() -> bool:
    cfg = _get_auth_config()
    return cfg.get("email_verification_enabled", "false").lower() == "true"


def is_registration_open() -> bool:
    """Whether self-service /auth/register is open to non-bootstrap users.

    Defaults to ``false`` (closed) when the SystemConfig row is missing —
    i.e. the secure default.  Admins flip it via the General Settings page.
    """
    cfg = _get_auth_config()
    return cfg.get("registration_open", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def validate_password(password: str) -> Optional[str]:
    """Return an error message if the password doesn't meet policy, else None."""
    cfg = _get_auth_config()
    min_len = int(cfg.get("password_min_length", "8"))
    require_upper = cfg.get("password_require_uppercase", "true").lower() == "true"
    require_digit = cfg.get("password_require_digit", "true").lower() == "true"

    if len(password) < min_len:
        return f"Password must be at least {min_len} characters"
    if require_upper and not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if require_digit and not re.search(r"\d", password):
        return "Password must contain at least one digit"
    return None


def generate_verification_token() -> str:
    return secrets.token_urlsafe(48)


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------

def check_account_lock(user: User) -> Optional[str]:
    """Return an error string if the account is currently locked, else None."""
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1
        return f"Account locked. Try again in {remaining} minute(s)."
    return None


def record_failed_login(user: User) -> None:
    cfg = _get_auth_config()
    max_attempts = int(cfg.get("max_failed_logins", "5"))
    lockout_min = int(cfg.get("lockout_duration_minutes", "15"))

    with get_session() as session:
        u = session.get(User, user.id)
        if not u:
            return
        u.failed_login_attempts = (u.failed_login_attempts or 0) + 1
        if u.failed_login_attempts >= max_attempts:
            u.locked_until = datetime.utcnow() + timedelta(minutes=lockout_min)
        session.add(u)
        session.commit()


def clear_failed_logins(user: User) -> None:
    with get_session() as session:
        u = session.get(User, user.id)
        if not u:
            return
        u.failed_login_attempts = 0
        u.locked_until = None
        session.add(u)
        session.commit()


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(user_id: str, email: str, role: str, org_id: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "org": org_id,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    with get_session() as session:
        user = session.get(User, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
        session.expunge(user)

    # Override with JWT active org/role so org-switching is reflected without a DB round-trip
    user.organization_id = payload.get("org", user.organization_id)
    user.role = payload.get("role", user.role)
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Role canonicalization.
#
# Phase 4 introduced two role changes that we keep backwards-compatible:
#   - `manager`  -> renamed to `org_admin`
#   - `viewer`   -> new read-only role
# JWTs already in flight may still carry `manager`, and old DB rows are
# updated lazily by the init_db migration.  These helpers normalize the
# input so call sites only deal with the new names.
# ---------------------------------------------------------------------------

#: Roles accepted as input via API payloads (request body validation).
VALID_ROLES = ("admin", "org_admin", "user", "viewer")

#: Roles that satisfy require_org_admin.  Includes legacy "manager" for
#: stale JWTs issued before the rename.
ORG_ADMIN_ROLES = ("admin", "org_admin", "manager")


def normalize_role(role: str | None) -> str:
    """Translate legacy/alias role names to canonical form.

    - ``manager`` -> ``org_admin`` (Phase 4 rename)
    - empty -> ``user`` (default)
    - anything else: returned unchanged so callers can reject it via
      ``role not in VALID_ROLES`` and produce a 400 with the user's input.
    """
    if not role:
        return "user"
    if role == "manager":
        return "org_admin"
    return role


async def require_org_admin(user: User = Depends(get_current_user)) -> User:
    """Allow `admin` (system) or `org_admin` (org-scoped admin).

    `org_admin` replaces the legacy `manager` role.  For a transitional
    period we still accept `manager` so JWTs issued before the rename
    keep working until they expire.
    """
    if user.role not in ORG_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org-admin or admin access required",
        )
    return user


# Backwards-compat alias so existing imports keep working until we sweep them
require_manager = require_org_admin


async def require_viewer(user: User = Depends(get_current_user)) -> User:
    """Allow any logged-in user — viewers, members, org_admins, admins.

    Used for read-only endpoints to make intent explicit.  ``get_current_user``
    is already enforced by the dependency chain, so this is currently a
    semantic alias; future tightening (e.g. blocking deactivated accounts
    differently per endpoint) goes here.
    """
    if normalize_role(user.role) not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authentication required")
    return user
