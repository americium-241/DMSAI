"""
EmailWatcher — polls an IMAP mailbox for new messages and ingests
supported attachments (PDF, images) into the DMSAI pipeline.

Configuration is read live from SystemConfig (DB) on every poll cycle,
so admin changes take effect without restarting the node.

Uses Python stdlib imaplib + email (no extra deps required).
"""

from __future__ import annotations

import asyncio
import email as _email
import imaplib
import logging
import os
import ssl
from email.message import Message
from typing import Optional

import httpx

from .ingestion_logic import build_ingestion_payload, SUPPORTED_EXTENSIONS

logger = logging.getLogger("ingestion_node.email_watcher")


# ---------------------------------------------------------------------------
# DB config helpers
# ---------------------------------------------------------------------------

def _read_email_config() -> dict:
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
        logger.debug(f"Could not read email config from DB: {e}")
        return {}


def _bool(val: str, default: bool = False) -> bool:
    if not val:
        return default
    return str(val).lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# IMAP helpers (sync, run in thread)
# ---------------------------------------------------------------------------

def _connect_imap(host: str, port: int, use_tls: bool) -> imaplib.IMAP4:
    if use_tls:
        ctx = ssl.create_default_context()
        return imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    conn = imaplib.IMAP4(host, port)
    # Try STARTTLS if available
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


def _poll_mailbox_sync(cfg: dict, node_url: str) -> int:
    """Synchronous IMAP poll. Returns count of documents ingested."""
    host = cfg.get("ingestion_email_imap_host", "")
    user = cfg.get("ingestion_email_imap_user", "")
    password = cfg.get("ingestion_email_imap_password", "")
    port = int(cfg.get("ingestion_email_imap_port", "993") or "993")
    use_tls = _bool(cfg.get("ingestion_email_imap_tls", "true"), default=True)
    folder = cfg.get("ingestion_email_folder", "INBOX") or "INBOX"
    mark_seen = _bool(cfg.get("ingestion_email_mark_seen", "true"), default=True)

    if not host or not user or not password:
        logger.warning("Email watcher: IMAP host/user/password not configured — skipping")
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

        logger.info(f"Email watcher: {len(msg_ids)} unseen message(s) in {folder}")

        for msg_id in msg_ids:
            try:
                msg = _fetch_message(conn, msg_id)
                if not msg:
                    continue

                subject = msg.get("Subject", "(no subject)")
                sender = msg.get("From", "")
                attachments = _get_attachments(msg)

                if not attachments:
                    logger.debug(f"Email '{subject}' from {sender}: no supported attachments — skipping")
                    if mark_seen:
                        _mark_seen(conn, msg_id)
                    continue

                for filename, file_bytes in attachments:
                    try:
                        payload = build_ingestion_payload(
                            file_bytes, filename, source="email"
                        )
                        # Annotate with email metadata for traceability
                        payload["email_subject"] = subject
                        payload["email_from"] = sender

                        with __import__("httpx").Client() as client:
                            resp = client.post(
                                f"{node_url}/ingest",
                                json=payload,
                                timeout=30.0,
                            )
                            resp.raise_for_status()

                        logger.info(
                            f"Email ingested: '{filename}' from '{sender}' "
                            f"(subject: {subject}) -> {payload['workflow_id']}"
                        )
                        ingested += 1
                    except Exception as e:
                        logger.error(f"Failed to ingest attachment '{filename}': {e}")

                if mark_seen:
                    _mark_seen(conn, msg_id)

            except Exception as e:
                logger.error(f"Error processing email {msg_id}: {e}")

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
    except Exception as e:
        logger.error(f"Email watcher unexpected error: {e}")
    finally:
        if conn:
            try:
                conn.logout()
            except Exception:
                pass

    return ingested


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------

class EmailWatcher:
    """Async loop that polls an IMAP mailbox on a configurable interval."""

    def __init__(self, node_port: int = 8010):
        self.node_url = f"http://localhost:{node_port}"

    async def run(self):
        logger.info("Email watcher started")
        while True:
            try:
                cfg = _read_email_config()
                enabled = _bool(cfg.get("ingestion_email_enabled", "false"), default=False)
                interval = float(cfg.get("ingestion_email_poll_interval_seconds", "60") or "60")

                if enabled:
                    count = await asyncio.to_thread(_poll_mailbox_sync, cfg, self.node_url)
                    if count:
                        logger.info(f"Email watcher: ingested {count} document(s)")
                else:
                    logger.debug("Email watcher disabled — skipping poll")
            except asyncio.CancelledError:
                logger.info("Email watcher stopping.")
                break
            except Exception as e:
                logger.error(f"Email watcher loop error: {e}")
                interval = 60.0

            await asyncio.sleep(interval)
