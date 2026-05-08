"""
Gateway test setup.

Adds api_gateway/ to sys.path so bare imports like `from auth import ...`
work when importing the gateway router modules.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# sys.path setup (runs at collection time)
# ---------------------------------------------------------------------------

_GW_PATH = str(Path(__file__).resolve().parent.parent.parent.parent / "api_gateway")
if _GW_PATH not in sys.path:
    sys.path.insert(0, _GW_PATH)

# ---------------------------------------------------------------------------
# Import gateway app (after path is set)
# ---------------------------------------------------------------------------

from dmsai_models import (
    Organization, User, UserOrganization, Document, get_session, init_db,
)


def _make_test_org(session) -> Organization:
    org = Organization(id=str(uuid.uuid4()), name=f"GW Test Org {uuid.uuid4().hex[:6]}")
    session.add(org)
    session.flush()
    return org


def _make_test_user(session, org_id: str, role: str = "user") -> tuple[User, str]:
    from auth import hash_password, create_access_token
    password = "TestPass1"
    user = User(
        id=str(uuid.uuid4()),
        email=f"testuser-{uuid.uuid4().hex[:8]}@gw.test",
        password_hash=hash_password(password),
        full_name=f"Test {role.title()}",
        role=role,
        organization_id=org_id,
        is_active=True,
        auth_provider="local",
        email_verified=True,
    )
    session.add(user)
    session.flush()
    # Create UserOrganization membership so multi-org scope checks pass
    session.add(UserOrganization(
        id=str(uuid.uuid4()),
        user_id=user.id,
        organization_id=org_id,
        role=role,
        is_default=True,
    ))
    token = create_access_token(user.id, user.email, user.role, user.organization_id)
    return user, token


@pytest.fixture(scope="module")
def gw_app():
    """Return the gateway FastAPI app."""
    from main import app  # noqa: E402
    return app


@pytest.fixture(scope="module")
def gw_client(gw_app):
    """Return a TestClient for the gateway app."""
    return TestClient(gw_app, raise_server_exceptions=True)


@pytest.fixture(scope="module")
def gw_org_and_users():
    """Create org + admin + regular user in the test DB. Returns a dict with tokens."""
    init_db()
    with get_session() as session:
        org = _make_test_org(session)
        admin_user, admin_token = _make_test_user(session, org.id, role="admin")
        regular_user, user_token = _make_test_user(session, org.id, role="user")
        session.commit()
        return {
            "org_id": org.id,
            "admin_id": admin_user.id,
            "admin_email": admin_user.email,
            "admin_token": admin_token,
            "user_id": regular_user.id,
            "user_email": regular_user.email,
            "user_token": user_token,
        }


@pytest.fixture
def admin_headers(gw_org_and_users):
    return {"Authorization": f"Bearer {gw_org_and_users['admin_token']}"}


@pytest.fixture
def user_headers(gw_org_and_users):
    return {"Authorization": f"Bearer {gw_org_and_users['user_token']}"}


@pytest.fixture
def org_id(gw_org_and_users):
    return gw_org_and_users["org_id"]
