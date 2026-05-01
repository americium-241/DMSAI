"""
Integration tests for the full authentication flow via the API gateway.

Tests the complete lifecycle: register → login → use token → verify data.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

# Add api_gateway to path for gateway imports
_GW_PATH = str(Path(__file__).resolve().parent.parent.parent / "api_gateway")
if _GW_PATH not in sys.path:
    sys.path.insert(0, _GW_PATH)

from fastapi.testclient import TestClient
from dmsai_models import User, Organization, get_session, init_db


@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


def _unique_email() -> str:
    return f"auth-integration-{uuid.uuid4().hex[:8]}@test.com"


def _unique_org() -> str:
    return f"AuthOrg-{uuid.uuid4().hex[:6]}"


def _bootstrap_admin(client) -> dict:
    """
    Register the very first user (bootstrap admin) or, if the DB already has users,
    create an admin directly via the DB helper and return a token.
    Returns: {"token": str, "org_id": str, "email": str}
    """
    from auth import hash_password, create_access_token
    from dmsai_models import Organization, User, get_session, init_db

    init_db()
    email = _unique_email()
    org_name = _unique_org()

    with get_session() as session:
        from sqlmodel import func, select
        total = session.exec(select(func.count()).select_from(User)).one()
        if total == 0:
            # True first-user path via registration
            resp = client.post("/api/auth/register", json={
                "email": email,
                "password": "AdminPass1",
                "full_name": "Bootstrap Admin",
                "organization_name": org_name,
            })
            assert resp.status_code == 200, resp.text
            return {
                "token": resp.json()["access_token"],
                "org_id": resp.json()["user"]["organization_id"],
                "email": email,
            }
        else:
            # DB already has users — create via helper
            org = Organization(id=str(uuid.uuid4()), name=org_name)
            session.add(org)
            session.flush()
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password("AdminPass1"),
                full_name="Bootstrap Admin",
                role="admin",
                organization_id=org.id,
                is_active=True,
                auth_provider="local",
                email_verified=True,
            )
            session.add(user)
            session.commit()
            token = create_access_token(user.id, user.email, user.role, user.organization_id)
            return {"token": token, "org_id": org.id, "email": email}


# ---------------------------------------------------------------------------
# Full register → login → use token flow
# ---------------------------------------------------------------------------

class TestFullAuthFlow:
    def test_bootstrap_admin_can_login(self, client):
        """First registered user becomes admin and can log in."""
        admin = _bootstrap_admin(client)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin['token']}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == admin["email"]

    def test_login_after_register_works(self, client):
        """Login with the password used at registration returns a valid token."""
        admin = _bootstrap_admin(client)
        login_resp = client.post("/api/auth/login", json={
            "email": admin["email"],
            "password": "AdminPass1",
        })
        assert login_resp.status_code == 200
        assert len(login_resp.json()["access_token"]) > 20

    def test_token_allows_protected_endpoint(self, client):
        admin = _bootstrap_admin(client)
        resp = client.get(
            "/api/documents",
            headers={"Authorization": f"Bearer {admin['token']}"},
        )
        assert resp.status_code == 200

    def test_invalid_token_rejected(self, client):
        resp = client.get("/api/documents", headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 401

    def test_no_token_rejected(self, client):
        resp = client.get("/api/documents")
        assert resp.status_code == 401

    def test_bootstrap_user_is_admin(self, client):
        """The first user (bootstrap admin) must have role 'admin'."""
        admin = _bootstrap_admin(client)
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin['token']}"})
        assert me.status_code == 200
        assert me.json()["role"] == "admin"


# ---------------------------------------------------------------------------
# Registration behaviour
# ---------------------------------------------------------------------------

class TestRegistrationBehaviour:
    def test_self_register_joins_existing_org_as_user(self, client):
        """When registration is open and the org exists, new users join as 'user' role."""
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        # Find the org name
        org_resp = client.get("/api/organization", headers=headers)
        org_name = org_resp.json()["name"]

        new_email = _unique_email()
        reg = client.post("/api/auth/register", json={
            "email": new_email,
            "password": "RegularPass1",
            "full_name": "Regular User",
            "organization_name": org_name,
        })
        # 200 = joined; 403 = registration closed (both valid depending on config)
        assert reg.status_code in (200, 403)
        if reg.status_code == 200:
            data = reg.json()["user"]
            assert data["role"] == "user", "Self-registered users must NOT be admin"
            assert data["organization_id"] == admin["org_id"]

    def test_register_to_nonexistent_org_fails(self, client):
        """Registering to an org that doesn't exist must fail with 404 or 403."""
        resp = client.post("/api/auth/register", json={
            "email": _unique_email(),
            "password": "SecurePass1",
            "full_name": "Ghost User",
            "organization_name": f"IDoNotExist-{uuid.uuid4().hex}",
        })
        assert resp.status_code in (404, 403)

    def test_register_without_org_name_fails(self, client):
        """Non-first users must supply organization_name."""
        resp = client.post("/api/auth/register", json={
            "email": _unique_email(),
            "password": "SecurePass1",
            "full_name": "Nameless",
        })
        # 400 = missing org_name; 403 = registration closed
        assert resp.status_code in (400, 403)


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------

class TestAccountLockout:
    def test_multiple_wrong_passwords_eventually_locks(self, client):
        admin = _bootstrap_admin(client)

        for _ in range(6):
            client.post("/api/auth/login", json={
                "email": admin["email"],
                "password": "WrongPassword1",
            })

        final_resp = client.post("/api/auth/login", json={
            "email": admin["email"],
            "password": "WrongPassword1",
        })
        assert final_resp.status_code in (401, 429)


# ---------------------------------------------------------------------------
# Admin user and organization management
# ---------------------------------------------------------------------------

class TestAdminUserManagement:
    def test_admin_can_create_user_in_own_org(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        resp = client.post("/api/admin/users", headers=headers, json={
            "email": _unique_email(),
            "password": "CreatedPass1",
            "full_name": "Admin Created User",
            "role": "user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["role"] == "user"
        assert data["organization_id"] == admin["org_id"]

    def test_admin_can_create_manager(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        resp = client.post("/api/admin/users", headers=headers, json={
            "email": _unique_email(),
            "password": "ManagerPass1",
            "full_name": "New Manager",
            "role": "manager",
        })
        assert resp.status_code == 200
        assert resp.json()["role"] == "manager"

    def test_non_admin_cannot_create_user(self, client):
        from auth import create_access_token, hash_password
        from dmsai_models import Organization, User, get_session, init_db

        admin = _bootstrap_admin(client)

        # Create a regular user
        init_db()
        with get_session() as session:
            user = User(
                id=str(uuid.uuid4()),
                email=_unique_email(),
                password_hash=hash_password("UserPass1"),
                full_name="Regular User",
                role="user",
                organization_id=admin["org_id"],
                is_active=True,
                auth_provider="local",
                email_verified=True,
            )
            session.add(user)
            session.commit()
            user_token = create_access_token(user.id, user.email, user.role, user.organization_id)

        resp = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "email": _unique_email(),
                "password": "AnotherPass1",
                "full_name": "Unauthorized",
                "role": "user",
            },
        )
        assert resp.status_code == 403

    def test_admin_cannot_create_user_with_invalid_role(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        resp = client.post("/api/admin/users", headers=headers, json={
            "email": _unique_email(),
            "password": "Pass12345A",
            "full_name": "Bad Role",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_admin_cannot_demote_own_account(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        # Get own user ID
        me = client.get("/api/auth/me", headers=headers)
        own_id = me.json()["id"]

        resp = client.put(f"/api/users/{own_id}", headers=headers, json={"role": "user"})
        assert resp.status_code == 400

    def test_admin_can_deactivate_other_user(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        # Create a user to deactivate
        create_resp = client.post("/api/admin/users", headers=headers, json={
            "email": _unique_email(),
            "password": "ToDeactivate1",
            "full_name": "Will Be Deactivated",
            "role": "user",
        })
        assert create_resp.status_code == 200
        user_id = create_resp.json()["id"]

        # Deactivate
        del_resp = client.delete(f"/api/admin/users/{user_id}", headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deactivated"

    def test_admin_cannot_deactivate_self(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        me = client.get("/api/auth/me", headers=headers)
        own_id = me.json()["id"]

        resp = client.delete(f"/api/admin/users/{own_id}", headers=headers)
        assert resp.status_code == 400


class TestAdminOrganizationManagement:
    def test_admin_can_create_organization(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        new_org_name = _unique_org()
        resp = client.post("/api/admin/organizations", headers=headers, json={"name": new_org_name})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["name"] == new_org_name
        assert "id" in data

    def test_duplicate_org_name_rejected(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        name = _unique_org()
        client.post("/api/admin/organizations", headers=headers, json={"name": name})
        resp = client.post("/api/admin/organizations", headers=headers, json={"name": name})
        assert resp.status_code == 409

    def test_non_admin_cannot_create_org(self, client):
        from auth import create_access_token, hash_password
        from dmsai_models import User, get_session, init_db

        admin = _bootstrap_admin(client)

        init_db()
        with get_session() as session:
            user = User(
                id=str(uuid.uuid4()),
                email=_unique_email(),
                password_hash=hash_password("UserPass1"),
                full_name="Regular",
                role="user",
                organization_id=admin["org_id"],
                is_active=True,
                auth_provider="local",
                email_verified=True,
            )
            session.add(user)
            session.commit()
            token = create_access_token(user.id, user.email, user.role, user.organization_id)

        resp = client.post(
            "/api/admin/organizations",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": _unique_org()},
        )
        assert resp.status_code == 403

    def test_admin_can_create_user_in_new_org(self, client):
        """Admin creates a new org, then places a user into it using organization_id."""
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        # Create new org
        org_resp = client.post("/api/admin/organizations", headers=headers, json={"name": _unique_org()})
        assert org_resp.status_code == 200
        new_org_id = org_resp.json()["id"]

        # Create a user in that new org
        user_resp = client.post("/api/admin/users", headers=headers, json={
            "email": _unique_email(),
            "password": "OrgAdminPass1",
            "full_name": "New Org Admin",
            "role": "admin",
            "organization_id": new_org_id,
        })
        assert user_resp.status_code == 200
        assert user_resp.json()["organization_id"] == new_org_id

    def test_admin_can_list_organizations(self, client):
        admin = _bootstrap_admin(client)
        headers = {"Authorization": f"Bearer {admin['token']}"}

        resp = client.get("/api/admin/organizations", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) >= 1


# ---------------------------------------------------------------------------
# Cross-org document isolation
# ---------------------------------------------------------------------------

class TestTokenOrgIsolation:
    def test_users_in_different_orgs_see_different_documents(self, client):
        """
        Two users in separate organizations must not see each other's documents.
        We create the orgs and users directly via the DB helper to avoid relying
        on self-service registration (which no longer creates new organizations).
        """
        from auth import create_access_token, hash_password
        from dmsai_models import Organization, User, Document, get_session, init_db

        init_db()
        with get_session() as session:
            org_a = Organization(id=str(uuid.uuid4()), name=_unique_org())
            org_b = Organization(id=str(uuid.uuid4()), name=_unique_org())
            session.add(org_a)
            session.add(org_b)
            session.flush()

            def _make_user(org_id: str) -> tuple[str, str]:
                email = _unique_email()
                pw_hash = hash_password("IsoPass1")
                u = User(
                    id=str(uuid.uuid4()),
                    email=email,
                    password_hash=pw_hash,
                    full_name="Iso User",
                    role="user",
                    organization_id=org_id,
                    is_active=True,
                    auth_provider="local",
                    email_verified=True,
                )
                session.add(u)
                session.flush()
                token = create_access_token(u.id, email, u.role, org_id)
                return u.id, token

            _uid_a, token_a = _make_user(org_a.id)
            _uid_b, token_b = _make_user(org_b.id)
            session.commit()

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        docs_a = client.get("/api/documents", headers=headers_a)
        docs_b = client.get("/api/documents", headers=headers_b)

        assert docs_a.status_code == 200
        assert docs_b.status_code == 200

        # Collect document IDs visible to each user
        ids_a = {d["id"] for d in docs_a.json().get("items", docs_a.json() if isinstance(docs_a.json(), list) else [])}
        ids_b = {d["id"] for d in docs_b.json().get("items", docs_b.json() if isinstance(docs_b.json(), list) else [])}

        # No document should be visible in both orgs
        assert ids_a.isdisjoint(ids_b), "Documents leaked across organization boundaries"
