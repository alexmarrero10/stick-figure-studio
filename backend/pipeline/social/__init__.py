"""Uploading Shorts to YouTube, Instagram, Facebook and TikTok through their official APIs.

Each module takes an httpx.Client, so tests can swap in a fake transport, and raises SocialError
with a readable message when the platform refuses.
"""
from __future__ import annotations

import base64
import hashlib
import secrets

import httpx


class SocialError(RuntimeError):
    pass


def check(r: httpx.Response, what: str) -> dict:
    """The JSON body of a successful response, or a SocialError with the platform's own message."""
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {}
    if r.status_code >= 400:
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = err.get("message") or err.get("error_user_msg") or err.get("code") or str(err)
        elif isinstance(err, str):
            msg = data.get("error_description") or err
        else:
            msg = r.text[:300] or f"HTTP {r.status_code}"
        raise SocialError(f"{what} failed ({r.status_code}): {msg}")
    return data if isinstance(data, dict) else {}


def pkce() -> tuple[str, str, str]:
    """(verifier, S256 challenge in base64url as Google wants, S256 challenge in hex as TikTok wants)."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode(), digest.hex()
