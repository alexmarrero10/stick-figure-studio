from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_key, load_config, save_config, set_api_key
from pipeline import claude_code, ffmpeg
from pipeline.voice import VoiceError, list_voices, resolve_voice

router = APIRouter(prefix="/api/settings", tags=["settings"])

KEY_NAMES = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY")


def _mask(v: str | None) -> str | None:
    return f"{v[:6]}…{v[-4:]}" if v and len(v) > 12 else ("set" if v else None)


@router.get("/voices")
def voices() -> list[dict[str, Any]]:
    key = get_key("ELEVENLABS_API_KEY")
    if not key:
        raise HTTPException(400, "ELEVENLABS_API_KEY is not set. Add it on the Settings page.")
    return list_voices(key)


@router.get("")
def get_settings() -> dict[str, Any]:
    return {"config": load_config(), "keys": {k: _mask(get_key(k)) for k in KEY_NAMES}}


@router.put("/config")
def put_config(cfg: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    for section, values in cfg.items():
        if section in current and isinstance(values, dict):
            current[section].update(values)
    save_config(current)
    return current


class KeyBody(BaseModel):
    name: str
    value: str


@router.put("/key")
def put_key(body: KeyBody) -> dict[str, Any]:
    if body.name not in KEY_NAMES:
        raise HTTPException(400, "Unknown key")
    set_api_key(body.name, body.value.strip())
    return {"ok": True, "masked": _mask(body.value.strip())}


@router.get("/health")
def health() -> dict[str, Any]:
    cfg = load_config()
    provider = cfg["claude"].get("provider", "claude_code")
    out: dict[str, Any] = {
        "ffmpeg": ffmpeg.available(),
        "claude_provider": provider,
        "claude_code": claude_code.auth_status() if provider == "claude_code" else None,
        "anthropic_key": bool(get_key("ANTHROPIC_API_KEY")),
        "elevenlabs_key": bool(get_key("ELEVENLABS_API_KEY")),
        "voice": None,
        "voice_error": None,
    }
    key = get_key("ELEVENLABS_API_KEY")
    if key:
        try:
            v = resolve_voice(key, cfg["voice"]["voice_id"], cfg["voice"].get("voice_name", "Josh"))
            out["voice"] = v
            if v["voice_id"] != cfg["voice"]["voice_id"]:
                cfg["voice"]["voice_id"] = v["voice_id"]
                save_config(cfg)
        except (VoiceError, Exception) as e:  # network errors included
            out["voice_error"] = str(e)
    return out
