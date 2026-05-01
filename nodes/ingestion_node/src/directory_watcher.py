import os
import shutil
import asyncio
import logging
import yaml
import httpx

from .ingestion_logic import build_ingestion_payload, SUPPORTED_EXTENSIONS

logger = logging.getLogger("ingestion_node.watcher")


def _read_db_config() -> dict:
    """Read ingestion directory settings from SystemConfig (DB-backed)."""
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
        logger.debug(f"Could not read ingestion config from DB: {e}")
        return {}


class DirectoryWatcher:
    """
    Polls the inbox directory for new files and submits them to /ingest.

    Configuration priority (highest wins):
      1. SystemConfig DB keys (live — changes take effect on next scan)
      2. local_config.yaml (fallback / bootstrap defaults)
    """

    def __init__(self, config_path: str = "config/local_config.yaml", node_port: int = 8010):
        self._config_path = config_path
        self._node_port = node_port

        # Load YAML defaults once (used as fallback when DB is unavailable)
        self._yaml_defaults: dict = {}
        try:
            with open(config_path, "r") as f:
                self._yaml_defaults = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Could not read {config_path}: {e}")

        self.node_url = f"http://localhost:{node_port}"
        self._ensure_dirs()

    # ------------------------------------------------------------------
    # Live config (re-read from DB on every poll iteration)
    # ------------------------------------------------------------------

    def _get_cfg(self, key_db: str, key_yaml: str, default):
        db = _read_db_config()
        if key_db in db and db[key_db]:
            return db[key_db]
        return self._yaml_defaults.get(key_yaml, default)

    @property
    def watch_dir(self) -> str:
        return self._get_cfg("ingestion_watch_directory", "watch_directory", "./data/inbox")

    @property
    def processed_dir(self) -> str:
        return self._get_cfg("ingestion_processed_directory", "processed_directory", "./data/processed")

    @property
    def poll_interval(self) -> float:
        try:
            return float(self._get_cfg("ingestion_poll_interval_seconds", "poll_interval_seconds", 5))
        except (ValueError, TypeError):
            return 5.0

    @property
    def enabled(self) -> bool:
        val = self._get_cfg("ingestion_watch_enabled", "watch_enabled", "true")
        return str(val).lower() in ("true", "1", "yes")

    def _ensure_dirs(self):
        try:
            os.makedirs(self.watch_dir, exist_ok=True)
            os.makedirs(self.processed_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create directories: {e}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self):
        logger.info(f"Directory watcher started (config from DB with YAML fallback)")
        while True:
            try:
                if self.enabled:
                    self._ensure_dirs()
                    await self._scan_once()
                else:
                    logger.debug("Directory watcher disabled — skipping scan")
            except asyncio.CancelledError:
                logger.info("Directory watcher stopping.")
                break
            except Exception as e:
                logger.error(f"Watcher error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _scan_once(self):
        watch = self.watch_dir
        if not os.path.isdir(watch):
            return

        for entry in os.listdir(watch):
            filepath = os.path.join(watch, entry)
            if not os.path.isfile(filepath):
                continue

            ext = os.path.splitext(entry)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                logger.warning(f"Skipping unsupported file: {entry}")
                continue

            try:
                with open(filepath, "rb") as f:
                    file_bytes = f.read()

                payload = build_ingestion_payload(file_bytes, entry, source="directory")

                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{self.node_url}/ingest",
                        json=payload,
                        timeout=30.0,
                    )
                    resp.raise_for_status()

                dest = os.path.join(self.processed_dir, entry)
                shutil.move(filepath, dest)
                logger.info(f"Ingested from directory: {entry} -> {payload['workflow_id']}")

            except Exception as e:
                logger.error(f"Failed to ingest {entry}: {e}")
