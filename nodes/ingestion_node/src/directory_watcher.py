import os
import shutil
import asyncio
import logging
import yaml
import httpx

from .ingestion_logic import build_ingestion_payload, SUPPORTED_EXTENSIONS

logger = logging.getLogger("ingestion_node.watcher")


class DirectoryWatcher:
    """Polls the inbox directory for new files and submits them to /ingest."""

    def __init__(self, config_path: str = "config/local_config.yaml", node_port: int = 8010):
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)

        self.watch_dir = cfg["watch_directory"]
        self.processed_dir = cfg["processed_directory"]
        self.poll_interval = cfg.get("poll_interval_seconds", 5)
        self.node_url = f"http://localhost:{node_port}"

        os.makedirs(self.watch_dir, exist_ok=True)
        os.makedirs(self.processed_dir, exist_ok=True)

    async def run(self):
        logger.info(f"Directory watcher started: {self.watch_dir}")
        while True:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                logger.info("Directory watcher stopping.")
                break
            except Exception as e:
                logger.error(f"Watcher error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _scan_once(self):
        if not os.path.isdir(self.watch_dir):
            return

        for entry in os.listdir(self.watch_dir):
            filepath = os.path.join(self.watch_dir, entry)
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
