"""Unit tests for gateway /api/dashboard and /api/activity endpoints."""

from __future__ import annotations

import pytest


class TestDashboard:
    def test_dashboard_authenticated(self, gw_client, admin_headers):
        resp = gw_client.get("/api/dashboard", headers=admin_headers)
        assert resp.status_code == 200

    def test_dashboard_has_stats(self, gw_client, admin_headers):
        resp = gw_client.get("/api/dashboard", headers=admin_headers)
        data = resp.json()
        # Dashboard should return some aggregated counts
        assert isinstance(data, dict)

    def test_dashboard_unauthenticated_returns_401(self, gw_client):
        resp = gw_client.get("/api/dashboard")
        assert resp.status_code == 401

    def test_dashboard_regular_user_can_access(self, gw_client, user_headers):
        resp = gw_client.get("/api/dashboard", headers=user_headers)
        assert resp.status_code == 200


class TestRecentActivity:
    def test_recent_activity_authenticated(self, gw_client, admin_headers):
        resp = gw_client.get("/api/activity/recent", headers=admin_headers)
        assert resp.status_code == 200

    def test_recent_activity_returns_list(self, gw_client, admin_headers):
        resp = gw_client.get("/api/activity/recent", headers=admin_headers)
        data = resp.json()
        # Endpoint wraps results: {"items": [...]}
        assert isinstance(data.get("items"), list)

    def test_recent_activity_unauthenticated_returns_401(self, gw_client):
        resp = gw_client.get("/api/activity/recent")
        assert resp.status_code == 401
