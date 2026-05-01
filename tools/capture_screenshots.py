#!/usr/bin/env python3
"""
Capture README screenshots from a running DMSAI instance.

Usage:
    python dmsai.py start
    python tools/capture_screenshots.py

Requirements:
    pip install playwright requests
    playwright install chromium
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

API = "http://localhost:8080"
APP = "http://localhost:5173"
OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

EMAIL = "admin@dmsai.com"
PASSWORD = "admin123"
VIEWPORT = {"width": 1280, "height": 860}


def _login(page) -> None:
    page.goto(f"{APP}/login", wait_until="networkidle")
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{APP}/**", timeout=10_000)
    time.sleep(1)


def _shot(page, name: str, url: str, tab: Optional[str] = None, wait_ms: int = 1500) -> None:
    print(f"  -> {name}")
    page.goto(url, wait_until="networkidle")
    time.sleep(wait_ms / 1000)
    if tab:
        for sel in [f"button:has-text('{tab}')", f"[role=tab]:has-text('{tab}')"]:
            try:
                page.click(sel, timeout=2000)
                time.sleep(1.0)
                break
            except Exception:
                continue
    # Always scroll to top so the viewport is consistent across all screenshots
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.3)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)


def _ensure_document() -> Optional[str]:
    """Return first document ID, uploading the canva sample if none exist."""
    import requests

    token = requests.post(
        f"{API}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=10,
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    docs = requests.get(f"{API}/api/documents?page_size=1", headers=headers, timeout=10).json()
    items = docs.get("items") or docs.get("documents") or (docs if isinstance(docs, list) else [])
    if items:
        return items[0].get("id") or items[0].get("document_id")

    root = Path(__file__).resolve().parent.parent
    candidates = sorted(root.glob("example_docs/canva*.jpg")) + sorted(root.glob("example_docs/canva*.png"))
    if not candidates:
        print("  ! No example document found to upload")
        return None

    print(f"  Uploading {candidates[0].name}...")
    with open(candidates[0], "rb") as f:
        resp = requests.post(
            f"{API}/api/upload",
            headers=headers,
            files={"file": (candidates[0].name, f, "image/jpeg")},
            data={"priority": "0", "mode": "auto"},
            timeout=30,
        )
    if resp.status_code >= 400:
        print(f"  ! Upload failed: {resp.text}")
        return None
    return resp.json().get("document_id")


def main() -> None:
    from playwright.sync_api import sync_playwright

    print(f"\nCapturing screenshots -> {OUT}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()

        _login(page)
        doc_id = _ensure_document()

        # Main pages
        _shot(page, "dashboard",        f"{APP}/")
        _shot(page, "documents",        f"{APP}/documents")
        _shot(page, "upload",           f"{APP}/upload")
        _shot(page, "buckets",          f"{APP}/buckets")

        # Document detail tabs
        if doc_id:
            base = f"{APP}/documents/{doc_id}"
            _shot(page, "document-confidence",  base)                        # default tab
            _shot(page, "document-entities",    base, tab="Entities")        # entity extraction tab
            _shot(page, "document-fields",      base, tab="Fields")          # field extraction tab
            _shot(page, "document-extraction",  base, tab="Fields")          # alias kept for README compat
            _shot(page, "document-ocr",         base, tab="OCR Text")
            _shot(page, "document-relations",   base, tab="Relations")
            _shot(page, "document-history",     base, tab="History", wait_ms=2000)

        # Admin pages
        _shot(page, "pipeline",          f"{APP}/admin/pipeline",   wait_ms=1000)
        _shot(page, "llm-settings",      f"{APP}/admin/llm-settings")
        _shot(page, "general-settings",  f"{APP}/admin/settings")

        # Swagger UI
        _shot(page, "swagger", f"{API}/docs", wait_ms=2000)

        ctx.close()
        browser.close()

    print(f"\nDone. {len(list(OUT.glob('*.png')))} images in {OUT}\n")
    for f in sorted(OUT.glob("*.png")):
        print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
