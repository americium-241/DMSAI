"""Unit tests for gateway /api/users and /api/organization endpoints."""

from __future__ import annotations

import uuid

import pytest

from dmsai_models import Organization, User, get_session, init_db


class TestListUsers:
    def test_admin_can_list_users(self, gw_client, admin_headers):
        resp = gw_client.get("/api/users", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_regular_user_forbidden(self, gw_client, user_headers):
        resp = gw_client.get("/api/users", headers=user_headers)
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, gw_client):
        resp = gw_client.get("/api/users")
        assert resp.status_code == 401

    def test_response_has_user_fields(self, gw_client, admin_headers):
        resp = gw_client.get("/api/users", headers=admin_headers)
        assert resp.status_code == 200
        users = resp.json()
        if users:
            user = users[0]
            assert "id" in user
            assert "email" in user
            assert "role" in user
            assert "is_active" in user


class TestUpdateUser:
    def test_admin_can_update_role(self, gw_client, admin_headers, gw_org_and_users):
        user_id = gw_org_and_users["user_id"]
        resp = gw_client.put(
            f"/api/users/{user_id}",
            headers=admin_headers,
            json={"role": "manager"},
        )
        assert resp.status_code == 200

        # Restore role
        gw_client.put(
            f"/api/users/{user_id}",
            headers=admin_headers,
            json={"role": "user"},
        )

    def test_update_nonexistent_user_returns_404(self, gw_client, admin_headers):
        resp = gw_client.put(
            f"/api/users/{uuid.uuid4()}",
            headers=admin_headers,
            json={"role": "user"},
        )
        assert resp.status_code == 404

    def test_invalid_role_is_rejected(self, gw_client, admin_headers, gw_org_and_users):
        user_id = gw_org_and_users["user_id"]
        resp = gw_client.put(
            f"/api/users/{user_id}",
            headers=admin_headers,
            json={"role": "superadmin"},
        )
        # Invalid roles must be rejected with 400
        assert resp.status_code == 400

    def test_admin_cannot_demote_own_role(self, gw_client, admin_headers, gw_org_and_users):
        admin_id = gw_org_and_users["admin_id"]
        resp = gw_client.put(
            f"/api/users/{admin_id}",
            headers=admin_headers,
            json={"role": "user"},
        )
        assert resp.status_code == 400

    def test_regular_user_cannot_update_user(self, gw_client, user_headers, gw_org_and_users):
        user_id = gw_org_and_users["user_id"]
        resp = gw_client.put(
            f"/api/users/{user_id}",
            headers=user_headers,
            json={"role": "admin"},
        )
        assert resp.status_code == 403


class TestOrganization:
    def test_get_organization(self, gw_client, user_headers):
        resp = gw_client.get("/api/organization", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "name" in data

    def test_admin_can_update_organization(self, gw_client, admin_headers):
        resp = gw_client.put(
            "/api/organization",
            headers=admin_headers,
            json={"name": "Updated Org Name"},
        )
        assert resp.status_code == 200

    def test_regular_user_cannot_update_organization(self, gw_client, user_headers):
        resp = gw_client.put(
            "/api/organization",
            headers=user_headers,
            json={"name": "Attempted Update"},
        )
        assert resp.status_code == 403


import uuid as _uuid


class TestAdminCreateUser:
    def test_admin_can_create_user(self, gw_client, admin_headers, gw_org_and_users):
        resp = gw_client.post("/api/admin/users", headers=admin_headers, json={
            "email": f"newuser-{_uuid.uuid4().hex[:8]}@test.com",
            "password": "Created1Pass",
            "full_name": "Admin Created",
            "role": "user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["role"] == "user"
        assert data["organization_id"] == gw_org_and_users["org_id"]

    def test_admin_create_user_invalid_role_rejected(self, gw_client, admin_headers):
        resp = gw_client.post("/api/admin/users", headers=admin_headers, json={
            "email": f"badrole-{_uuid.uuid4().hex[:8]}@test.com",
            "password": "Secured1Pass",
            "full_name": "Bad Role",
            "role": "superadmin",
        })
        assert resp.status_code == 400

    def test_admin_create_user_duplicate_email_rejected(self, gw_client, admin_headers, gw_org_and_users):
        resp = gw_client.post("/api/admin/users", headers=admin_headers, json={
            "email": gw_org_and_users["admin_email"],
            "password": "Secured1Pass",
            "full_name": "Duplicate",
            "role": "user",
        })
        assert resp.status_code == 409

    def test_regular_user_cannot_create_user(self, gw_client, user_headers):
        resp = gw_client.post("/api/admin/users", headers=user_headers, json={
            "email": f"forbidden-{_uuid.uuid4().hex[:8]}@test.com",
            "password": "Secured1Pass",
            "full_name": "Forbidden",
            "role": "user",
        })
        assert resp.status_code == 403

    def test_unauthenticated_cannot_create_user(self, gw_client):
        resp = gw_client.post("/api/admin/users", json={
            "email": f"unauth-{_uuid.uuid4().hex[:8]}@test.com",
            "password": "Secured1Pass",
            "full_name": "Unauth",
            "role": "user",
        })
        assert resp.status_code == 401


class TestAdminDeactivateUser:
    def test_admin_can_deactivate_user(self, gw_client, admin_headers):
        # Create a fresh user to deactivate
        email = f"todeactivate-{_uuid.uuid4().hex[:8]}@test.com"
        create = gw_client.post("/api/admin/users", headers=admin_headers, json={
            "email": email,
            "password": "Deact1Pass",
            "full_name": "To Deactivate",
            "role": "user",
        })
        user_id = create.json()["id"]

        resp = gw_client.delete(f"/api/admin/users/{user_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

    def test_admin_cannot_deactivate_self(self, gw_client, admin_headers, gw_org_and_users):
        resp = gw_client.delete(
            f"/api/admin/users/{gw_org_and_users['admin_id']}",
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_deactivate_nonexistent_user_returns_404(self, gw_client, admin_headers):
        resp = gw_client.delete(f"/api/admin/users/{_uuid.uuid4()}", headers=admin_headers)
        assert resp.status_code == 404


class TestAdminOrganizations:
    def test_admin_can_list_organizations(self, gw_client, admin_headers):
        resp = gw_client.get("/api/admin/organizations", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_can_create_organization(self, gw_client, admin_headers):
        new_name = f"NewOrg-{_uuid.uuid4().hex[:8]}"
        resp = gw_client.post("/api/admin/organizations", headers=admin_headers, json={"name": new_name})
        assert resp.status_code == 200
        assert resp.json()["name"] == new_name
        assert resp.json()["status"] == "created"

    def test_duplicate_org_rejected(self, gw_client, admin_headers):
        name = f"DupOrg-{_uuid.uuid4().hex[:8]}"
        gw_client.post("/api/admin/organizations", headers=admin_headers, json={"name": name})
        resp = gw_client.post("/api/admin/organizations", headers=admin_headers, json={"name": name})
        assert resp.status_code == 409

    def test_regular_user_cannot_create_org(self, gw_client, user_headers):
        resp = gw_client.post(
            "/api/admin/organizations",
            headers=user_headers,
            json={"name": f"ForbiddenOrg-{_uuid.uuid4().hex[:8]}"},
        )
        assert resp.status_code == 403

    def test_regular_user_cannot_list_orgs(self, gw_client, user_headers):
        resp = gw_client.get("/api/admin/organizations", headers=user_headers)
        assert resp.status_code == 403
