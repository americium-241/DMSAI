from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func
from sqlmodel import select

from dmsai_models import SystemConfig, User, get_session

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status", summary="First-run setup status (no auth required)")
async def setup_status():
    """Return whether initial setup has been completed.

    Checks two signals:
    - ``setup_completed`` SystemConfig key set to ``"true"``
    - Whether any User rows exist in the database

    No authentication is required so the frontend can detect a fresh
    installation before any account has been created.
    """
    with get_session() as session:
        user_count: int = session.exec(
            select(func.count()).select_from(User)
        ).one()

        llm_cfg = session.get(SystemConfig, "llm_provider")
        setup_cfg = session.get(SystemConfig, "setup_completed")

    has_users = user_count > 0
    llm_configured = bool(llm_cfg and llm_cfg.value and llm_cfg.value not in ("", "ollama"))

    # Treat existing installations (already have users) as "completed" even
    # if the setup_completed flag was never set.  This avoids redirecting
    # users of an instance that pre-dates the wizard to the setup flow.
    explicitly_done = bool(setup_cfg and setup_cfg.value == "true")
    completed = explicitly_done or has_users

    return {
        "completed": completed,
        "has_users": has_users,
        "llm_configured": llm_configured,
    }
