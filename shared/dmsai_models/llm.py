"""Shared LLM caller that dispatches to Ollama or LiteLLM based on SystemConfig.

Token usage is recorded automatically into LLMUsage for every successful call.
Both providers are supported:
  - Ollama:   response["prompt_eval_count"] / response["eval_count"]
  - LiteLLM:  response["usage"]["prompt_tokens"] / ["completion_tokens"]
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

import httpx
from sqlmodel import select

logger = logging.getLogger("dmsai_llm")

_config_cache: dict[str, str] = {}
_cache_ts: float = 0.0
_CACHE_TTL = 30.0


def _refresh_config() -> dict[str, str]:
    """Load LLM + OCR settings from SystemConfig (cached for _CACHE_TTL)."""
    global _config_cache, _cache_ts
    now = time.time()
    if _config_cache and (now - _cache_ts) < _CACHE_TTL:
        return _config_cache
    try:
        from .connection import get_engine
        from .models import SystemConfig
        from sqlmodel import Session
        with Session(get_engine()) as session:
            rows = session.exec(
                select(SystemConfig).where(
                    SystemConfig.category.in_(["llm", "ocr"])
                )
            ).all()
            _config_cache = {r.key: r.value for r in rows}
            _cache_ts = now
    except Exception as e:
        logger.warning("Failed to load LLM config from DB, using cached/defaults: %s", e)
        if not _config_cache:
            _config_cache = {
                "llm_provider": "ollama",
                "ollama_base_url": "http://localhost:11434",
                "llm_model": "gemma3:27b",
                "litellm_base_url": "",
                "litellm_api_key": "",
                "litellm_model": "",
            }
    return _config_cache


# ---------------------------------------------------------------------------
# Token usage recording
# ---------------------------------------------------------------------------

def _record_usage(
    provider: str,
    model: str,
    stage: str,
    call_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    document_id: Optional[str] = None,
) -> None:
    """Write one LLMUsage row.  Silently absorbs all errors."""
    if prompt_tokens == 0 and completion_tokens == 0:
        return
    try:
        from datetime import datetime
        from .connection import get_engine
        from .models import LLMUsage
        from sqlmodel import Session
        with Session(get_engine()) as session:
            session.add(LLMUsage(
                id=str(uuid.uuid4()),
                provider=provider,
                model=model,
                stage=stage,
                call_type=call_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                document_id=document_id,
            ))
            session.commit()
    except Exception as e:
        logger.debug("Failed to record LLM usage (non-critical): %s", e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def call_llm(
    prompt: str,
    json_format: bool = False,
    timeout: float = 300.0,
    stage: str = "unknown",
    document_id: Optional[str] = None,
) -> str:
    """
    Unified LLM text call.  Reads provider from SystemConfig (cached).
    - ollama:   POST {base}/api/chat
    - litellm:  POST {base}/chat/completions  (OpenAI-compatible)

    Token usage is recorded into LLMUsage after every successful call.
    """
    cfg = _refresh_config()
    provider = cfg.get("llm_provider", "ollama")
    try:
        timeout = float(cfg.get("llm_timeout_seconds", timeout))
    except (TypeError, ValueError):
        pass

    if provider == "litellm":
        return await _call_litellm(prompt, json_format, timeout, cfg, stage, document_id)
    return await _call_ollama(prompt, json_format, timeout, cfg, stage, document_id)


async def _call_ollama(
    prompt: str,
    json_format: bool,
    timeout: float,
    cfg: dict[str, str],
    stage: str,
    document_id: Optional[str],
) -> str:
    base_url = cfg.get("ollama_base_url", "http://localhost:11434")
    model = cfg.get("llm_model", "gemma3:27b")
    temperature = float(cfg.get("llm_temperature", "0.1"))
    url = f"{base_url}/api/chat"
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_format:
        body["format"] = "json"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    prompt_tokens     = data.get("prompt_eval_count", 0) or 0
    completion_tokens = data.get("eval_count", 0) or 0
    _record_usage("ollama", model, stage, "text", prompt_tokens, completion_tokens, document_id)

    return data.get("message", {}).get("content", "")


async def _call_litellm(
    prompt: str,
    json_format: bool,
    timeout: float,
    cfg: dict[str, str],
    stage: str,
    document_id: Optional[str],
) -> str:
    base_url = cfg.get("litellm_base_url", "").rstrip("/")
    if not base_url:
        raise RuntimeError("litellm_base_url is not configured")
    api_key = cfg.get("litellm_api_key", "")
    model = cfg.get("litellm_model", "")
    temperature = float(cfg.get("llm_temperature", "0.1"))
    if not model:
        raise RuntimeError("litellm_model is not configured")

    url = f"{base_url}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if json_format:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    usage = data.get("usage") or {}
    prompt_tokens     = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    _record_usage("litellm", model, stage, "text", prompt_tokens, completion_tokens, document_id)

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


# ---------------------------------------------------------------------------
# Vision LLM
# ---------------------------------------------------------------------------

def get_ocr_config() -> dict[str, str]:
    return _refresh_config()


async def call_vision_llm(
    image_b64: str,
    prompt: str | None = None,
    timeout: float = 300.0,
    stage: str = "ocr",
    document_id: Optional[str] = None,
) -> str:
    """Send a base64 PNG image to a vision-capable LLM."""
    cfg = _refresh_config()
    try:
        timeout = float(cfg.get("llm_vision_timeout_seconds", timeout))
    except (TypeError, ValueError):
        pass
    provider = cfg.get("llm_provider", "ollama")

    if not prompt:
        prompt = cfg.get(
            "ocr_vision_prompt",
            "Extract ALL text from this document image exactly as it appears.",
        )

    if provider == "litellm":
        return await _vision_litellm(image_b64, prompt, timeout, cfg, stage, document_id)
    return await _vision_ollama(image_b64, prompt, timeout, cfg, stage, document_id)


async def _vision_ollama(
    image_b64: str,
    prompt: str,
    timeout: float,
    cfg: dict[str, str],
    stage: str,
    document_id: Optional[str],
) -> str:
    base_url = cfg.get("ollama_base_url", "http://localhost:11434")
    model = cfg.get("ocr_vision_model", "") or cfg.get("llm_model", "gemma3:27b")
    url = f"{base_url}/api/chat"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    prompt_tokens     = data.get("prompt_eval_count", 0) or 0
    completion_tokens = data.get("eval_count", 0) or 0
    _record_usage("ollama", model, stage, "vision", prompt_tokens, completion_tokens, document_id)

    return data.get("message", {}).get("content", "")


async def _vision_litellm(
    image_b64: str,
    prompt: str,
    timeout: float,
    cfg: dict[str, str],
    stage: str,
    document_id: Optional[str],
) -> str:
    base_url = cfg.get("litellm_base_url", "").rstrip("/")
    if not base_url:
        raise RuntimeError("litellm_base_url is not configured")
    api_key = cfg.get("litellm_api_key", "")
    model = cfg.get("ocr_vision_model", "") or cfg.get("litellm_model", "")
    temperature = float(cfg.get("llm_temperature", "0.1"))
    if not model:
        raise RuntimeError("No vision model configured (ocr_vision_model / litellm_model)")

    url = f"{base_url}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }
        ],
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    usage = data.get("usage") or {}
    prompt_tokens     = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    _record_usage("litellm", model, stage, "vision", prompt_tokens, completion_tokens, document_id)

    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""
