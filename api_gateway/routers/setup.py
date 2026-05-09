from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from auth import get_current_user
from dmsai_models import SystemConfig, User, get_session

router = APIRouter(prefix="/api/setup", tags=["setup"])

# Absolute path to the project root litellm_config.yaml
# api_gateway/ is one level below the project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LITELLM_CONFIG = _PROJECT_ROOT / "litellm_config.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENV_VAR_FOR_PROVIDER = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "cohere": "COHERE_API_KEY",
}


def _api_key_env(model: str) -> str:
    """Return the env-var name to use in litellm_config.yaml for a given model string."""
    prefix = model.split("/")[0].lower() if "/" in model else "gemini"
    return _ENV_VAR_FOR_PROVIDER.get(prefix, "GEMINI_API_KEY")


def _write_litellm_config(
    text_model: str,
    vision_model: str,
    embedding_model: Optional[str],
) -> None:
    """Generate and write litellm_config.yaml for the given models."""
    models_seen: set[str] = set()
    model_list = []

    for m in [text_model, vision_model, embedding_model]:
        if not m or m in models_seen:
            continue
        models_seen.add(m)
        env_var = _api_key_env(m)
        model_list.append({
            "model_name": m,
            "litellm_params": {
                "model": m,
                "api_key": f"os.environ/{env_var}",
            },
        })

    config = {
        "model_list": model_list,
        "general_settings": {"drop_params": True},
    }

    _LITELLM_CONFIG.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def _save_system_config(key: str, value: str, session) -> None:
    row = session.get(SystemConfig, key)
    if row:
        row.value = value
    else:
        from datetime import datetime
        row = SystemConfig(key=key, value=value, category="llm",
                           description="", updated_at=datetime.utcnow())
    session.add(row)


def _restart_litellm() -> None:
    """Best-effort restart of the litellm service via the CLI helper."""
    dmsai_cli = _PROJECT_ROOT / "dmsai.py"
    if not dmsai_cli.exists():
        return
    subprocess.Popen(
        [sys.executable, str(dmsai_cli), "restart", "--only", "litellm"],
        cwd=str(_PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Public endpoint — no auth (checked before any account exists)
# ---------------------------------------------------------------------------

@router.get("/status", summary="First-run setup status (no auth required)")
async def setup_status():
    """Return whether initial setup has been completed."""
    with get_session() as session:
        user_count: int = session.exec(
            select(func.count()).select_from(User)
        ).one()

        llm_cfg = session.get(SystemConfig, "llm_provider")
        setup_cfg = session.get(SystemConfig, "setup_completed")

    has_users = user_count > 0
    llm_configured = bool(llm_cfg and llm_cfg.value and llm_cfg.value not in ("", "ollama"))

    explicitly_done = bool(setup_cfg and setup_cfg.value == "true")
    completed = explicitly_done or has_users

    return {
        "completed": completed,
        "has_users": has_users,
        "llm_configured": llm_configured,
    }


# ---------------------------------------------------------------------------
# Auth-required endpoint — called from wizard Step 2 after account creation
# ---------------------------------------------------------------------------

class LLMConfigPayload(BaseModel):
    provider: str          # "ollama" | "gemini" | "openai" | "anthropic" | "litellm"
    text_model: str
    vision_model: str = ""
    api_key: str = ""
    ollama_url: str = "http://localhost:11434"
    embedding_enabled: bool = False
    embedding_model: str = ""


@router.post("/apply-llm", summary="Apply LLM config and restart LiteLLM proxy (admin only)")
async def apply_llm_config(
    payload: LLMConfigPayload,
    current_user=Depends(get_current_user),
):
    """Write SystemConfig rows + regenerate litellm_config.yaml + restart proxy."""
    if current_user.role not in ("admin", "org_admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or org_admin required")

    provider = payload.provider.lower()

    with get_session() as session:
        if provider == "ollama":
            _save_system_config("llm_provider", "ollama", session)
            _save_system_config("ollama_base_url", payload.ollama_url, session)
            _save_system_config("llm_model", payload.text_model, session)
            if payload.vision_model:
                _save_system_config("ocr_vision_model", payload.vision_model, session)
        else:
            # Cloud provider — route via LiteLLM proxy
            full_model = payload.text_model if "/" in payload.text_model else f"{provider}/{payload.text_model}"
            full_vision = payload.vision_model if (not payload.vision_model or "/" in payload.vision_model) else f"{provider}/{payload.vision_model}"
            full_embed = payload.embedding_model if (not payload.embedding_model or "/" in payload.embedding_model) else f"{provider}/{payload.embedding_model}"

            _save_system_config("llm_provider", "litellm", session)
            _save_system_config("litellm_base_url", "http://localhost:4000", session)
            _save_system_config("litellm_model", full_model, session)
            _save_system_config("litellm_api_key", payload.api_key, session)
            if full_vision:
                _save_system_config("ocr_vision_model", full_vision, session)

            # Write litellm_config.yaml with all required models
            embed_model = full_embed if payload.embedding_enabled else None
            vision_for_cfg = full_vision or full_model  # vision falls back to text model
            try:
                _write_litellm_config(full_model, vision_for_cfg, embed_model)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to write LiteLLM config: {e}")

        if payload.embedding_enabled:
            _save_system_config("embedding_enabled", "true", session)
            if payload.embedding_model:
                embed_key = payload.embedding_model if "/" in payload.embedding_model else f"{provider}/{payload.embedding_model}"
                _save_system_config("embedding_model", embed_key, session)
            _save_system_config("embedding_provider",
                                "ollama" if provider == "ollama" else "litellm", session)
        else:
            _save_system_config("embedding_enabled", "false", session)

        session.commit()

    # Restart LiteLLM proxy in background so it picks up the new config + API key
    if provider != "ollama":
        _restart_litellm()

    return {"status": "ok", "provider": provider, "model": payload.text_model}
