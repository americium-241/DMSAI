"""
Integration tests for multi-organization support:
- switch-org endpoint
- multi-org isolation (documents scoped to org)
- per-org ingestion config CRUD
- org membership management
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

_GW_PATH = str(Path(__file__).resolve().parent.parent.parent / "api_gateway")
if _GW_PATH not in sys.path:
    sys.path.insert(0, _GW_PATH)

from fastapi.testclient import TestClient
from dmsai_models import Organization, User, UserOrganization, OrgIngestionConfig, get_session, init_db
from auth import hash_password, create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_email():
    return f"multi-org-{uuid.uuid4().hex[:8]}@test.com"


def _make_org(session, name: str | None = None) -> Organization:
    org = Organization(
        id=str(uuid.uuid4()),
        name=name or f"TestOrg-{uuid.uuid4().hex[:6]}",
        created_at=datetime.utcnow(),
    )
    session.add(org)
    session.flush()
    return org


def _make_user(session, org_id: str, role: str = "user") -> tuple[User, str]:
    user = User(
        id=str(uuid.uuid4()),
        email=_unique_email(),
        password_hash=hash_password("TestPass1"),
        full_name=f"Test {role.title()}",
        role=role,
        organization_id=org_id,
        is_active=True,
        auth_provider="local",
        email_verified=True,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    session.add(UserOrganization(
        id=str(uuid.uuid4()),
        user_id=user.id,
        organization_id=org_id,
        role=role,
        is_default=True,
        joined_at=datetime.utcnow(),
    ))
    token = create_access_token(user.id, user.email, user.role, org_id)
    return user, token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def multi_org_setup():
    """
    Create two orgs, an admin user belonging to both, and a regular user in org_a only.
    Returns a dict with all IDs and tokens.
    """
    init_db()
    with get_session() as session:
        org_a = _make_org(session, "MultiOrg-A")
        org_b = _make_org(session, "MultiOrg-B")
        org_a_id = org_a.id
        org_b_id = org_b.id

        admin, admin_token_a = _make_user(session, org_a_id, role="admin")
        admin_id = admin.id
        admin_email = admin.email
        # Also add admin to org_b
        session.add(UserOrganization(
            id=str(uuid.uuid4()),
            user_id=admin_id,
            organization_id=org_b_id,
            role="manager",
            is_default=False,
            joined_at=datetime.utcnow(),
        ))

        regular, user_token = _make_user(session, org_a_id, role="user")
        user_id = regular.id

        session.commit()

    admin_headers_a = {"Authorization": f"Bearer {admin_token_a}"}
    user_headers = {"Authorization": f"Bearer {user_token}"}

    return {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "admin_id": admin_id,
        "admin_email": admin_email,
        "admin_token_a": admin_token_a,
        "admin_headers_a": admin_headers_a,
        "user_id": user_id,
        "user_token": user_token,
        "user_headers": user_headers,
    }


# ---------------------------------------------------------------------------
# Tests: GET /api/auth/organizations
# ---------------------------------------------------------------------------

class TestListMyOrganizations:
    def test_admin_sees_both_orgs(self, client, multi_org_setup):
        resp = client.get("/api/auth/organizations",
                          headers=multi_org_setup["admin_headers_a"])
        assert resp.status_code == 200
        orgs = resp.json()
        ids = {o["organization_id"] for o in orgs}
        assert multi_org_setup["org_a_id"] in ids
        assert multi_org_setup["org_b_id"] in ids

    def test_regular_user_sees_one_org(self, client, multi_org_setup):
        resp = client.get("/api/auth/organizations",
                          headers=multi_org_setup["user_headers"])
        assert resp.status_code == 200
        orgs = resp.json()
        assert len(orgs) == 1
        assert orgs[0]["organization_id"] == multi_org_setup["org_a_id"]

    def test_unauthenticated_rejected(self, client):
        resp = client.get("/api/auth/organizations")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: POST /api/auth/switch-org
# ---------------------------------------------------------------------------

class TestSwitchOrg:
    def test_switch_to_valid_org_returns_new_token(self, client, multi_org_setup):
        resp = client.post(
            "/api/auth/switch-org",
            json={"org_id": multi_org_setup["org_b_id"]},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["organization_id"] == multi_org_setup["org_b_id"]
        assert data["user"]["role"] == "manager"

    def test_switch_to_non_member_org_is_forbidden(self, client, multi_org_setup):
        # regular user only belongs to org_a
        resp = client.post(
            "/api/auth/switch-org",
            json={"org_id": multi_org_setup["org_b_id"]},
            headers=multi_org_setup["user_headers"],
        )
        assert resp.status_code == 403

    def test_switch_to_nonexistent_org_is_forbidden(self, client, multi_org_setup):
        resp = client.post(
            "/api/auth/switch-org",
            json={"org_id": str(uuid.uuid4())},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 403

    def test_new_token_scopes_to_switched_org(self, client, multi_org_setup):
        """After switching, the new JWT should carry the new org in its me response."""
        switch_resp = client.post(
            "/api/auth/switch-org",
            json={"org_id": multi_org_setup["org_b_id"]},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert switch_resp.status_code == 200
        new_token = switch_resp.json()["access_token"]
        me_resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["organization_id"] == multi_org_setup["org_b_id"]


# ---------------------------------------------------------------------------
# Tests: Org membership management (admin)
# ---------------------------------------------------------------------------

class TestOrgMembership:
    def test_list_members(self, client, multi_org_setup):
        resp = client.get(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members",
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        members = resp.json()
        user_ids = {m["user_id"] for m in members}
        assert multi_org_setup["admin_id"] in user_ids

    def test_add_existing_user_to_org(self, client, multi_org_setup):
        # regular user is not in org_b yet — add them
        resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_b_id']}/members",
            json={"user_id": multi_org_setup["user_id"], "role": "user"},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "added"

    def test_add_duplicate_member_returns_409(self, client, multi_org_setup):
        resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members",
            json={"user_id": multi_org_setup["admin_id"], "role": "user"},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 409

    def test_update_member_role(self, client, multi_org_setup):
        resp = client.put(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members/{multi_org_setup['user_id']}",
            json={"role": "manager"},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    def test_update_invalid_role_rejected(self, client, multi_org_setup):
        resp = client.put(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members/{multi_org_setup['user_id']}",
            json={"role": "superuser"},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 400

    def test_remove_member(self, client, multi_org_setup):
        # First add a throwaway user
        with get_session() as session:
            tmp_org = _make_org(session)
            tmp_org_id = tmp_org.id
            tmp_user, tmp_token = _make_user(session, tmp_org_id)
            tmp_uid = tmp_user.id
            session.commit()

        # Add to org_a
        client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members",
            json={"user_id": tmp_uid, "role": "user"},
            headers=multi_org_setup["admin_headers_a"],
        )
        # Remove
        resp = client.delete(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members/{tmp_uid}",
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_non_admin_cannot_manage_members(self, client, multi_org_setup):
        resp = client.get(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/members",
            headers=multi_org_setup["user_headers"],
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: Per-org ingestion config
# ---------------------------------------------------------------------------

class TestOrgIngestionConfig:
    def test_list_empty_initially(self, client, multi_org_setup):
        resp = client.get(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        # May be empty or pre-populated from migration; just check it's a list
        assert isinstance(resp.json(), list)

    def test_create_directory_config(self, client, multi_org_setup):
        resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            json={
                "name": "Test inbox",
                "source_type": "directory",
                "config": {"watch_directory": "/tmp/test-inbox"},
                "is_active": True,
            },
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert "id" in data

    def test_create_email_config(self, client, multi_org_setup):
        resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            json={
                "name": "Test email",
                "source_type": "email",
                "config": {"imap_host": "mail.example.com", "imap_user": "test@example.com"},
                "is_active": False,
            },
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        assert resp.json()["source_type"] == "email"

    def test_invalid_source_type_rejected(self, client, multi_org_setup):
        resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            json={"name": "Bad", "source_type": "ftp", "config": {}},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 400

    def test_update_config(self, client, multi_org_setup):
        # Create first
        create_resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            json={
                "name": "To update",
                "source_type": "directory",
                "config": {"watch_directory": "/old"},
                "is_active": True,
            },
            headers=multi_org_setup["admin_headers_a"],
        )
        assert create_resp.status_code == 200
        cfg_id = create_resp.json()["id"]

        # Update
        resp = client.put(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion/{cfg_id}",
            json={"config": {"watch_directory": "/new"}, "is_active": False},
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    def test_delete_config(self, client, multi_org_setup):
        # Create
        create_resp = client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            json={"name": "To delete", "source_type": "directory", "config": {}},
            headers=multi_org_setup["admin_headers_a"],
        )
        cfg_id = create_resp.json()["id"]

        # Delete
        resp = client.delete(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion/{cfg_id}",
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_config_isolated_to_org(self, client, multi_org_setup):
        """Configs created for org_a should not appear under org_b."""
        client.post(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            json={"name": "Org-A only", "source_type": "directory", "config": {"watch_directory": "/a"}},
            headers=multi_org_setup["admin_headers_a"],
        )
        resp_b = client.get(
            f"/api/admin/organizations/{multi_org_setup['org_b_id']}/ingestion",
            headers=multi_org_setup["admin_headers_a"],
        )
        assert resp_b.status_code == 200
        names_b = [c["name"] for c in resp_b.json()]
        assert "Org-A only" not in names_b

    def test_non_admin_cannot_manage_ingestion(self, client, multi_org_setup):
        resp = client.get(
            f"/api/admin/organizations/{multi_org_setup['org_a_id']}/ingestion",
            headers=multi_org_setup["user_headers"],
        )
        assert resp.status_code == 403
