from __future__ import annotations

import os
import shutil
import asyncio
import json
import logging
import yaml

from .ingestion_logic import build_ingestion_payload, SUPPORTED_EXTENSIONS

logger = logging.getLogger("ingestion_node.watcher")


# ---------------------------------------------------------------------------
# Config readers
# ---------------------------------------------------------------------------

def _read_org_directory_configs() -> list[dict]:
    """Return active OrgIngestionConfig rows for source_type='directory'."""
    try:
        from dmsai_models import get_session
        from dmsai_models.models import OrgIngestionConfig
        from sqlmodel import select

        with get_session() as session:
            rows = session.exec(
                select(OrgIngestionConfig).where(
                    OrgIngestionConfig.source_type == "directory",
                    OrgIngestionConfig.is_active == True,  # noqa: E712
                )
            ).all()
            result = []
            for r in rows:
                try:
                    cfg = json.loads(r.config_json) if r.config_json else {}
                except Exception:
                    cfg = {}
                cfg["_org_id"] = r.organization_id
                cfg["_config_id"] = r.id
                cfg["_name"] = r.name
                result.append(cfg)
            return result
    except Exception as e:
        logger.debug("Could not read OrgIngestionConfig from DB: %s", e)
        return []


def _read_legacy_db_config() -> dict:
    """Read ingestion directory settings from SystemConfig (legacy fallback)."""
    try:
        from dmsai_models import get_session
        from dmsai_models.models import SystemConfig
        from sqlmodel import select

        with get_session() as session:
            rows = session.exec(
                select(SystemConfig).where(SystemConfig.category == "ingestion")
            ).all()
            return {r.key: r.value for r in rows}
    except Exception as e:
        logger.debug("Could not read legacy ingestion config from DB: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Multi-org directory watcher
# ---------------------------------------------------------------------------

class DirectoryWatcher:
    """
    Polls directories for new files and submits them to /ingest.

    On every scan cycle it queries OrgIngestionConfig for active directory
    configs.  Each config is scoped to an organization and may watch a
    different path.

    Falls back to the old SystemConfig-based single-directory config when
    no OrgIngestionConfig rows exist (backward compatibility).
    """

    def __init__(self, config_path: str = "config/local_config.yaml", node_port: int = 8010):
        self._config_path = config_path
        self._node_port = node_port
        self.node_url = f"http://localhost:{node_port}"

        self._yaml_defaults: dict = {}
        try:
            with open(config_path, "r") as f:
                self._yaml_defaults = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Could not read %s: %s", config_path, e)

    # ------------------------------------------------------------------
    # Legacy single-config helpers (used as fallback)
    # ------------------------------------------------------------------

    def _legacy_get_cfg(self, key_db: str, key_yaml: str, default):
        db = _read_legacy_db_config()
        if key_db in db and db[key_db]:
            return db[key_db]
        return self._yaml_defaults.get(key_yaml, default)

    @property
    def _legacy_watch_dir(self) -> str:
        val = self._legacy_get_cfg(
            "ingestion_watch_directory", "watch_directory",
            os.environ.get("DMSAI_INBOX_DIR", "./data/inbox"),
        )
        # Resolve relative paths against CWD at call time; dmsai.py already
        # converts DMSAI_INBOX_DIR to absolute, so this is only a safety net.
        return os.path.abspath(val)

    @property
    def _legacy_processed_dir(self) -> str:
        val = self._legacy_get_cfg(
            "ingestion_processed_directory", "processed_directory",
            os.environ.get("DMSAI_PROCESSED_DIR", "./data/processed"),
        )
        return os.path.abspath(val)

    @property
    def _legacy_poll_interval(self) -> float:
        try:
            return float(self._legacy_get_cfg("ingestion_poll_interval_seconds", "poll_interval_seconds", 5))
        except (ValueError, TypeError):
            return 5.0

    @property
    def _legacy_enabled(self) -> bool:
        val = self._legacy_get_cfg("ingestion_watch_enabled", "watch_enabled", "true")
        return str(val).lower() in ("true", "1", "yes")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        logger.info("Directory watcher started (multi-org with legacy fallback)")
        while True:
            try:
                await self._scan_all()
            except asyncio.CancelledError:
                logger.info("Directory watcher stopping.")
                break
            except Exception as e:
                logger.error("Watcher error: %s", e)

            interval = self._get_poll_interval()
            await asyncio.sleep(interval)

    def _get_poll_interval(self) -> float:
        """Shortest active poll interval across all configs."""
        org_configs = _read_org_directory_configs()
        if org_configs:
            intervals = []
            for cfg in org_configs:
                try:
                    intervals.append(float(cfg.get("poll_interval_seconds", 5)))
                except (TypeError, ValueError):
                    intervals.append(5.0)
            return min(intervals) if intervals else 5.0
        return self._legacy_poll_interval

    async def _scan_all(self):
        """Scan all configured directories (org-specific + legacy fallback)."""
        org_configs = _read_org_directory_configs()

        if org_configs:
            for cfg in org_configs:
                await self._scan_directory(
                    watch_dir=cfg.get("watch_directory", ""),
                    processed_dir=cfg.get("processed_directory", "./data/processed"),
                    organization_id=cfg.get("_org_id"),
                    label=cfg.get("_name", cfg.get("_org_id", "?")),
                )
        else:
            # Legacy single-directory mode
            if not self._legacy_enabled:
                logger.debug("Directory watcher disabled — skipping scan")
                return
            self._ensure_dir(self._legacy_watch_dir)
            self._ensure_dir(self._legacy_processed_dir)
            await self._scan_directory(
                watch_dir=self._legacy_watch_dir,
                processed_dir=self._legacy_processed_dir,
                organization_id=None,
                label="legacy",
            )

    async def _scan_directory(
        self, watch_dir: str, processed_dir: str, organization_id: str | None, label: str
    ):
        if not watch_dir or not os.path.isdir(watch_dir):
            return

        self._ensure_dir(processed_dir)

        for entry in os.listdir(watch_dir):
            filepath = os.path.join(watch_dir, entry)
            if not os.path.isfile(filepath):
                continue

            ext = os.path.splitext(entry)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                logger.warning("Skipping unsupported file [%s]: %s", label, entry)
                continue

            try:
                with open(filepath, "rb") as f:
                    file_bytes = f.read()

                payload = build_ingestion_payload(
                    file_bytes, entry, source="directory", organization_id=organization_id
                )

                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.node_url}/ingest",
                        json=payload,
                        timeout=30.0,
                    )
                    resp.raise_for_status()

                dest = os.path.join(processed_dir, entry)
                shutil.move(filepath, dest)
                logger.info(
                    "Ingested [%s] org=%s: %s -> %s",
                    label, organization_id or "none", entry, payload["workflow_id"],
                )
            except Exception as e:
                logger.error("Failed to ingest %s [%s]: %s", entry, label, e)

    @staticmethod
    def _ensure_dir(path: str):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            logger.warning("Could not create directory %s: %s", path, e)
