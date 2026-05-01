"""Unit tests for gateway auth endpoints."""

from __future__ import annotations

import uuid

import pytest

from dmsai_models import User, Organization, get_session, init_db


class TestLogin:
    def test_login_success(self, gw_client, gw_org_and_users):
        resp = gw_client.post("/api/auth/login", json={
            "email": gw_org_and_users["admin_email"],
            "password": "TestPass1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data

    def test_login_wrong_password(self, gw_client, gw_org_and_users):
        resp = gw_client.post("/api/auth/login", json={
            "email": gw_org_and_users["admin_email"],
            "password": "WrongPass999",
        })
        assert resp.status_code == 401

    def test_login_unknown_email(self, gw_client):
        resp = gw_client.post("/api/auth/login", json={
            "email": "nobody@unknown.com",
            "password": "SomePass1",
        })
        assert resp.status_code == 401

    def test_login_response_contains_user_info(self, gw_client, gw_org_and_users):
        resp = gw_client.post("/api/auth/login", json={
            "email": gw_org_and_users["admin_email"],
            "password": "TestPass1",
        })
        user_data = resp.json()["user"]
        assert user_data["email"] == gw_org_and_users["admin_email"]
        assert "role" in user_data
        assert "organization_id" in user_data


class TestRegister:
    def test_register_to_existing_org_as_user(self, gw_client, gw_org_and_users):
        """Non-first users who provide a valid org name join as 'user' role."""
        # Find the org name created by the conftest fixture
        resp = gw_client.get(
            "/api/organization",
            headers={"Authorization": f"Bearer {gw_org_and_users['admin_token']}"},
        )
        org_name = resp.json()["name"]

        new_email = f"selfregister-{uuid.uuid4().hex[:8]}@test.com"
        reg = gw_client.post("/api/auth/register", json={
            "email": new_email,
            "password": "SecurePass1",
            "full_name": "Self Registered",
            "organization_name": org_name,
        })
        # Either 200 (joined) or 403 (registration closed) — both are valid
        assert reg.status_code in (200, 403)
        if reg.status_code == 200:
            data = reg.json()
            assert data["user"]["role"] == "user", "Self-registered users must not be admins"
            assert data["user"]["organization_id"] == gw_org_and_users["org_id"]

    def test_register_to_nonexistent_org_fails(self, gw_client):
        """Registering with an org name that does not exist must return 404."""
        new_email = f"noorg-{uuid.uuid4().hex[:8]}@test.com"
        resp = gw_client.post("/api/auth/register", json={
            "email": new_email,
            "password": "SecurePass1",
            "full_name": "No Org User",
            "organization_name": f"NonExistentOrg-{uuid.uuid4().hex}",
        })
        # 404 = org not found; 403 = registration closed; both are correct
        assert resp.status_code in (404, 403)

    def test_register_duplicate_email_fails(self, gw_client, gw_org_and_users):
        resp = gw_client.post("/api/auth/register", json={
            "email": gw_org_and_users["admin_email"],
            "password": "SecurePass1",
            "full_name": "Duplicate",
            "organization_name": "SomeOrg",
        })
        assert resp.status_code in (409, 403)

    def test_register_weak_password_rejected(self, gw_client):
        resp = gw_client.post("/api/auth/register", json={
            "email": f"weak-{uuid.uuid4().hex[:8]}@test.com",
            "password": "weak",
            "full_name": "Test",
            "organization_name": f"Org-{uuid.uuid4().hex[:6]}",
        })
        assert resp.status_code == 400

    def test_register_without_org_name_fails(self, gw_client):
        """Non-first users must always provide an organization_name."""
        resp = gw_client.post("/api/auth/register", json={
            "email": f"noname-{uuid.uuid4().hex[:8]}@test.com",
            "password": "SecurePass1",
            "full_name": "No Org Name",
        })
        # 400 = org name required; 403 = registration closed
        assert resp.status_code in (400, 403)


class TestGetMe:
    def test_get_me_with_valid_token(self, gw_client, admin_headers):
        resp = gw_client.get("/api/auth/me", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "email" in data
        assert "role" in data

    def test_get_me_without_token_returns_401(self, gw_client):
        resp = gw_client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_get_me_with_bad_token_returns_401(self, gw_client):
        resp = gw_client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401


class TestAuthProviders:
    def test_providers_endpoint_public(self, gw_client):
        resp = gw_client.get("/api/auth/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "local" in data
        assert data["local"] is True
        assert "ldap" in data
        assert "registration_open" in data


class TestPipelineHealth:
    def test_health_endpoint_no_auth(self, gw_client):
        """Pipeline health is public — no auth required."""
        resp = gw_client.get("/api/pipeline/health")
        assert resp.status_code == 200
        data = resp.json()
        expected_nodes = [
            "ingestion", "conversion", "storage", "ocr",
            "entity_extraction", "classification", "entity_resolution", "field_extraction",
        ]
        for node in expected_nodes:
            assert node in data
