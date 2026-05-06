"""
EmailWatcher — polls IMAP mailboxes for new messages and ingests
supported attachments into the DMSAI pipeline.

On every poll cycle it queries OrgIngestionConfig for active email
configs.  Each config is scoped to an organization.

Falls back to the legacy SystemConfig-based single-mailbox config when
no OrgIngestionConfig rows exist (backward compatibility).

Uses Python stdlib imaplib + email (no extra deps required).
"""

from __future__ import annotations

import asyncio
import email as _email
import imaplib
import json
import logging
import os
import ssl
from email.message import Message
from typing import Optional

from .ingestion_logic import build_ingestion_payload, SUPPORTED_EXTENSIONS

logger = logging.getLogger("ingestion_node.email_watcher")


# ---------------------------------------------------------------------------
# DB config readers
# ---------------------------------------------------------------------------

def _read_org_email_configs() -> list[dict]:
    """Return active OrgIngestionConfig rows for source_type='email'."""
    try:
        from dmsai_models import get_session
        from dmsai_models.models import OrgIngestionConfig
        from sqlmodel import select

        with get_session() as session:
            rows = session.exec(
                select(OrgIngestionConfig).where(
                    OrgIngestionConfig.source_type == "email",
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


def _read_legacy_email_config() -> dict:
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
        logger.debug("Could not read legacy email config from DB: %s", e)
        return {}


def _bool(val: str, default: bool = False) -> bool:
    if not val:
        return default
    return str(val).lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# IMAP helpers (synchronous, run in thread)
# ---------------------------------------------------------------------------

def _connect_imap(host: str, port: int, use_tls: bool) -> imaplib.IMAP4:
    if use_tls:
        ctx = ssl.create_default_context()
        return imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    conn = imaplib.IMAP4(host, port)
    if "STARTTLS" in conn.capabilities:
        ctx = ssl.create_default_context()
        conn.starttls(ssl_context=ctx)
    return conn


def _fetch_unseen_ids(conn: imaplib.IMAP4) -> list[bytes]:
    _, data = conn.search(None, "UNSEEN")
    raw = data[0]
    if not raw:
        return []
    return raw.split()


def _fetch_message(conn: imaplib.IMAP4, msg_id: bytes) -> Optional[Message]:
    _, data = conn.fetch(msg_id, "(RFC822)")
    for part in data:
        if isinstance(part, tuple):
            return _email.message_from_bytes(part[1])
    return None


def _mark_seen(conn: imaplib.IMAP4, msg_id: bytes):
    conn.store(msg_id, "+FLAGS", "\\Seen")


def _get_attachments(msg: Message) -> list[tuple[str, bytes]]:
    """Return (filename, file_bytes) for each supported attachment."""
    attachments = []
    for part in msg.walk():
        disposition = part.get_content_disposition() or ""
        filename = part.get_filename()
        if not filename:
            continue
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            attachments.append((filename, payload))
    return attachments


def _poll_mailbox_sync(cfg: dict, node_url: str, organization_id: str | None, label: str) -> int:
    """Synchronous IMAP poll for a single mailbox config. Returns count ingested."""
    # Support both OrgIngestionConfig keys (short) and legacy SystemConfig keys (prefixed)
    host = cfg.get("imap_host") or cfg.get("ingestion_email_imap_host", "")
    user = cfg.get("imap_user") or cfg.get("ingestion_email_imap_user", "")
    password = cfg.get("imap_password") or cfg.get("ingestion_email_imap_password", "")
    port = int(cfg.get("imap_port") or cfg.get("ingestion_email_imap_port", "993") or "993")
    use_tls = _bool(
        str(cfg.get("imap_ssl") or cfg.get("ingestion_email_imap_ssl") or cfg.get("imap_tls") or "true"),
        default=True,
    )
    folder = cfg.get("imap_folder") or cfg.get("ingestion_email_folder", "INBOX") or "INBOX"
    mark_seen_flag = _bool(
        str(cfg.get("mark_seen") or cfg.get("ingestion_email_mark_seen") or "true"),
        default=True,
    )

    if not host or not user or not password:
        logger.warning("Email watcher [%s]: IMAP host/user/password not configured — skipping", label)
        return 0

    ingested = 0
    conn = None
    try:
        conn = _connect_imap(host, port, use_tls)
        conn.login(user, password)
        conn.select(folder)

        msg_ids = _fetch_unseen_ids(conn)
        if not msg_ids:
            return 0

        logger.info("Email watcher [%s]: %d unseen message(s) in %s", label, len(msg_ids), folder)

        for msg_id in msg_ids:
            try:
                msg = _fetch_message(conn, msg_id)
                if not msg:
                    continue

                subject = msg.get("Subject", "(no subject)")
                sender = msg.get("From", "")
                attachments = _get_attachments(msg)

                if not attachments:
                    logger.debug(
                        "Email [%s] '%s' from %s: no supported attachments — skipping",
                        label, subject, sender,
                    )
                    if mark_seen_flag:
                        _mark_seen(conn, msg_id)
                    continue

                for filename, file_bytes in attachments:
                    try:
                        payload = build_ingestion_payload(
                            file_bytes, filename, source="email", organization_id=organization_id
                        )
                        payload["email_subject"] = subject
                        payload["email_from"] = sender

                        import httpx
                        with httpx.Client() as client:
                            resp = client.post(
                                f"{node_url}/ingest",
                                json=payload,
                                timeout=30.0,
                            )
                            resp.raise_for_status()

                        logger.info(
                            "Email ingested [%s] org=%s: '%s' from '%s' -> %s",
                            label, organization_id or "none", filename, sender, payload["workflow_id"],
                        )
                        ingested += 1
                    except Exception as e:
                        logger.error("Failed to ingest attachment '%s' [%s]: %s", filename, label, e)

                if mark_seen_flag:
                    _mark_seen(conn, msg_id)

            except Exception as e:
                logger.error("Error processing email %s [%s]: %s", msg_id, label, e)

    except imaplib.IMAP4.error as e:
        logger.error("IMAP error [%s]: %s", label, e)
    except Exception as e:
        logger.error("Email watcher unexpected error [%s]: %s", label, e)
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    return ingested


# ---------------------------------------------------------------------------
# Async multi-org email watcher
# ---------------------------------------------------------------------------

class EmailWatcher:
    """Async loop that polls all active IMAP mailboxes on a configurable interval."""

    def __init__(self, node_port: int = 8010):
        self.node_url = f"http://localhost:{node_port}"

    async def run(self):
        logger.info("Email watcher started (multi-org with legacy fallback)")
        while True:
            interval = 60.0
            try:
                org_configs = _read_org_email_configs()

                if org_configs:
                    for cfg in org_configs:
                        try:
                            org_id = cfg.get("_org_id")
                            label = cfg.get("_name", org_id or "?")
                            count = await asyncio.to_thread(
                                _poll_mailbox_sync, cfg, self.node_url, org_id, label
                            )
                            if count:
                                logger.info("Email watcher [%s]: ingested %d document(s)", label, count)
                        except Exception as e:
                            logger.error("Email watcher org config error: %s", e)
                    # Use the minimum configured interval
                    intervals = []
                    for cfg in org_configs:
                        try:
                            intervals.append(
                                float(cfg.get("poll_interval_seconds") or cfg.get("ingestion_email_poll_interval_seconds") or 60)
                            )
                        except (TypeError, ValueError):
                            intervals.append(60.0)
                    interval = min(intervals) if intervals else 60.0
                else:
                    # Legacy single-mailbox mode
                    legacy_cfg = _read_legacy_email_config()
                    enabled = _bool(legacy_cfg.get("ingestion_email_enabled", "false"), default=False)
                    interval = float(legacy_cfg.get("ingestion_email_poll_interval_seconds", "60") or "60")

                    if enabled:
                        count = await asyncio.to_thread(
                            _poll_mailbox_sync, legacy_cfg, self.node_url, None, "legacy"
                        )
                        if count:
                            logger.info("Email watcher (legacy): ingested %d document(s)", count)
                    else:
                        logger.debug("Email watcher disabled — skipping poll")

            except asyncio.CancelledError:
                logger.info("Email watcher stopping.")
                break
            except Exception as e:
                logger.error("Email watcher loop error: %s", e)
                interval = 60.0

            await asyncio.sleep(interval)
