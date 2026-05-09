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
    """Self-service registration is CLOSED by default.

    The only exceptions are:
    - the very first user (zero users in the DB) — bootstrap path
    - SystemConfig.registration_open == 'true' — explicitly re-opened
    """

    def test_register_blocked_when_users_exist(self, gw_client, gw_org_and_users):
        """With registration closed (default) and any user already in DB, register returns 403."""
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
        assert reg.status_code == 403, "Registration must be closed by default for non-first users"
        assert "administrator" in reg.json()["detail"].lower() or "invitation" in reg.json()["detail"].lower()

    def test_register_to_nonexistent_org_blocked(self, gw_client, gw_org_and_users):
        """Even with a non-existent org, registration is blocked when closed."""
        resp = gw_client.post("/api/auth/register", json={
            "email": f"noorg-{uuid.uuid4().hex[:8]}@test.com",
            "password": "SecurePass1",
            "full_name": "No Org User",
            "organization_name": f"NonExistentOrg-{uuid.uuid4().hex}",
        })
        assert resp.status_code == 403

    def test_register_duplicate_email_returns_409(self, gw_client, gw_org_and_users):
        """Duplicate email is detected before the closed-registration gate so
        existing users can't be enumerated by attackers checking for 403 vs 409."""
        resp = gw_client.post("/api/auth/register", json={
            "email": gw_org_and_users["admin_email"],
            "password": "SecurePass1",
            "full_name": "Duplicate",
            "organization_name": "SomeOrg",
        })
        assert resp.status_code == 409

    def test_register_weak_password_rejected_before_close_gate(self, gw_client, gw_org_and_users):
        """Password validation runs before the closed-registration check, so weak
        passwords always return 400 regardless of the registration_open flag."""
        resp = gw_client.post("/api/auth/register", json={
            "email": f"weak-{uuid.uuid4().hex[:8]}@test.com",
            "password": "weak",
            "full_name": "Test",
            "organization_name": f"Org-{uuid.uuid4().hex[:6]}",
        })
        assert resp.status_code == 400

    def test_register_without_org_name_blocked(self, gw_client, gw_org_and_users):
        resp = gw_client.post("/api/auth/register", json={
            "email": f"noname-{uuid.uuid4().hex[:8]}@test.com",
            "password": "SecurePass1",
            "full_name": "No Org Name",
        })
        assert resp.status_code == 403



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
