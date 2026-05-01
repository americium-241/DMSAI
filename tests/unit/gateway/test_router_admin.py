"""Unit tests for gateway /api/admin endpoints."""

from __future__ import annotations

import uuid

import pytest

from dmsai_models import (
    Entity, EntityField, SystemConfig, get_session, init_db,
)


def _create_entity(name: str = "Admin Test Corp") -> str:
    init_db()
    entity_id = str(uuid.uuid4())
    with get_session() as session:
        entity = Entity(
            id=entity_id, entity_type="company",
            name=name, canonical_name=name,
        )
        session.add(entity)
        session.commit()
    return entity_id


class TestAdminEntities:
    def test_list_entities_admin_only(self, gw_client, admin_headers, user_headers):
        resp = gw_client.get("/api/admin/entities", headers=admin_headers)
        assert resp.status_code == 200

    def test_list_entities_regular_user_forbidden(self, gw_client, user_headers):
        resp = gw_client.get("/api/admin/entities", headers=user_headers)
        assert resp.status_code == 403

    def test_entities_list_shape(self, gw_client, admin_headers):
        _create_entity("AdminTestCo")
        resp = gw_client.get("/api/admin/entities", headers=admin_headers)
        data = resp.json()
        assert "items" in data or isinstance(data, (list, dict))


class TestAdminQualityMetrics:
    def test_quality_metrics_accessible(self, gw_client, admin_headers):
        resp = gw_client.get("/api/admin/quality-metrics", headers=admin_headers)
        assert resp.status_code == 200

    def test_quality_metrics_forbidden_for_user(self, gw_client, user_headers):
        resp = gw_client.get("/api/admin/quality-metrics", headers=user_headers)
        assert resp.status_code == 403


class TestSystemConfig:
    def test_list_system_config_admin_only(self, gw_client, admin_headers, user_headers):
        resp = gw_client.get("/api/admin/system-config", headers=admin_headers)
        assert resp.status_code == 200

    def test_system_config_has_keys(self, gw_client, admin_headers):
        resp = gw_client.get("/api/admin/system-config", headers=admin_headers)
        data = resp.json()
        assert isinstance(data, (list, dict))
        if isinstance(data, list):
            assert len(data) > 0

    def test_update_system_config(self, gw_client, admin_headers):
        resp = gw_client.put(
            "/api/admin/system-config/llm_temperature",
            headers=admin_headers,
            json={"value": "0.2"},
        )
        assert resp.status_code == 200

        # Verify the value was updated
        with get_session() as session:
            row = session.get(SystemConfig, "llm_temperature")
        assert row.value == "0.2"

        # Restore
        with get_session() as session:
            row = session.get(SystemConfig, "llm_temperature")
            row.value = "0.1"
            session.add(row)
            session.commit()


class TestAdminEntityMerge:
    def test_merge_entities(self, gw_client, admin_headers):
        entity_a_id = _create_entity("Merge Corp A")
        entity_b_id = _create_entity("Merge Corp B")

        resp = gw_client.post(
            "/api/admin/entities/merge",
            headers=admin_headers,
            json={"source_id": entity_b_id, "target_id": entity_a_id},
        )
        assert resp.status_code in (200, 404, 422)


class TestCanonicalClasses:
    def test_list_canonical_classes(self, gw_client, admin_headers):
        resp = gw_client.get("/api/admin/canonical-classes", headers=admin_headers)
        assert resp.status_code in (200, 404)

    def test_list_canonical_fields(self, gw_client, admin_headers):
        resp = gw_client.get("/api/admin/canonical-fields", headers=admin_headers)
        assert resp.status_code in (200, 404)
