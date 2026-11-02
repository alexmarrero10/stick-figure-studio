"""Connecting YouTube, Facebook + Instagram, and TikTok accounts, and posting a video to them.

Each platform needs a developer app of your own (its ID and secret are entered on the Settings
page). "Connect" opens the platform's login page; it sends you back to /callback here, and the
tokens are kept in .env next to the other API keys.
"""
from __future__ import annotations

import html
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.config import get_key, load_config, set_api_key
from pipeline.social import SocialError, meta, pkce, tiktok, youtube

router = APIRouter(prefix="/api/social", tags=["social"])

# Per login: the developer app's ID and secret, typed in on the Settings page.
APP_KEYS = {
    "youtube": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
    "meta": ("META_APP_ID", "META_APP_SECRET"),
    "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
}
# Saved by "Connect".
TOKEN_KEYS = {
    "youtube": ("YOUTUBE_REFRESH_TOKEN", "YOUTUBE_ACCOUNT_NAME"),
    "meta": ("META_PAGE_ID", "META_PAGE_TOKEN", "META_PAGE_NAME", "INSTAGRAM_USER_ID", "INSTAGRAM_USERNAME"),
    "tiktok": ("TIKTOK_REFRESH_TOKEN", "TIKTOK_ACCOUNT_NAME"),
}
LOGINS = tuple(APP_KEYS)
# Which login each app posts with.
LOGIN_FOR = {"youtube": "youtube", "instagram": "meta", "facebook": "meta", "tiktok": "tiktok"}

_pending: dict[str, dict[str, Any]] = {}  # OAuth state -> {login, verifier, redirect_uri, at}


def http() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True)


def _ver() -> str:
    return load_config().get("social", {}).get("meta_graph_version", "v24.0")


def redirect_uri(request: Request, login: str) -> str:
    # Registered with each platform as http://localhost:<port>/api/social/<login>/callback.
    port = request.url.port or 8765
    return f"http://localhost:{port}/api/social/{login}/callback"


def _login(login: str) -> str:
    if login not in LOGINS:
        raise HTTPException(404, "Unknown account type")
    return login


def connected(platform: str) -> bool:
    if platform == "youtube":
        return bool(get_key("YOUTUBE_REFRESH_TOKEN"))
    if platform == "facebook":
        return bool(get_key("META_PAGE_TOKEN") and get_key("META_PAGE_ID"))
    if platform == "instagram":
        return bool(get_key("META_PAGE_TOKEN") and get_key("INSTAGRAM_USER_ID"))
    if platform == "tiktok":
        return bool(get_key("TIKTOK_REFRESH_TOKEN"))
    return False


def _mask(v: str | None) -> str | None:
    return f"{v[:4]}…{v[-3:]}" if v and len(v) > 10 else ("set" if v else None)


@router.get("")
def status(request: Request) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for login in LOGINS:
        app_id, app_secret = APP_KEYS[login]
        out[login] = {
            "app_id": get_key(app_id) or "",
            "app_secret": _mask(get_key(app_secret)),
            "app_ready": bool(get_key(app_id) and get_key(app_secret)),
            "redirect_uri": redirect_uri(request, login),
        }
    out["youtube"]["account"] = get_key("YOUTUBE_ACCOUNT_NAME") or ""
    out["meta"]["account"] = get_key("META_PAGE_NAME") or ""
    out["meta"]["instagram"] = get_key("INSTAGRAM_USERNAME") or ""
    out["tiktok"]["account"] = get_key("TIKTOK_ACCOUNT_NAME") or ""
    out["platforms"] = {p: connected(p) for p in LOGIN_FOR}
    return out


class AppBody(BaseModel):
    login: str
    app_id: str = ""
    app_secret: str = ""


@router.put("/app")
def save_app(body: AppBody) -> dict[str, Any]:
    id_key, secret_key = APP_KEYS[_login(body.login)]
    if body.app_id.strip():
        set_api_key(id_key, body.app_id.strip())
    if body.app_secret.strip():
        set_api_key(secret_key, body.app_secret.strip())
    return {"ok": True}


@router.get("/{login}/connect")
def connect(login: str, request: Request) -> RedirectResponse:
    _login(login)
    app_id, app_secret = (get_key(k) for k in APP_KEYS[login])
    if not app_id or not app_secret:
        raise HTTPException(400, "Save the app ID and secret on the Settings page first.")
    state = secrets.token_urlsafe(24)
    verifier, challenge, challenge_hex = pkce()
    uri = redirect_uri(request, login)
    _pending[state] = {"login": login, "verifier": verifier, "redirect_uri": uri, "at": time.time()}
    if login == "youtube":
        url = youtube.auth_url(app_id, uri, state, challenge)
    elif login == "meta":
        url = meta.auth_url(app_id, uri, state, _ver())
    else:
        url = tiktok.auth_url(app_id, uri, state, challenge_hex)
    return RedirectResponse(url)


def _page(title: str, text: str, ok: bool) -> HTMLResponse:
    color = "#1d7a3a" if ok else "#b42318"
    return HTMLResponse(
        f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"<body style='font-family:system-ui;max-width:560px;margin:80px auto;padding:0 16px'>"
        f"<h2 style='color:{color}'>{html.escape(title)}</h2><p>{html.escape(text)}</p>"
        f"<p>You can close this tab and go back to Stick Figure Studio.</p></body>",
        status_code=200 if ok else 400,
    )


@router.get("/{login}/callback")
def callback(login: str, state: str = "", code: str = "", error: str = "",
             error_description: str = "") -> HTMLResponse:
    _login(login)
    pending = _pending.pop(state, None)
    if error:
        return _page("Not connected", error_description or error, False)
    if not pending or pending["login"] != login or time.time() - pending["at"] > 900:
        return _page("Not connected", "This login link has expired. Click Connect again.", False)
    app_id, app_secret = (get_key(k) for k in APP_KEYS[login])
    try:
        with http() as c:
            if login == "youtube":
                refresh = youtube.exchange_code(c, app_id, app_secret, code, pending["redirect_uri"], pending["verifier"])
                name = youtube.channel(c, youtube.access_token(c, app_id, app_secret, refresh))["name"]
                set_api_key("YOUTUBE_REFRESH_TOKEN", refresh)
                set_api_key("YOUTUBE_ACCOUNT_NAME", name)
                return _page("YouTube connected", f"Shorts will be posted to {name}.", True)
            if login == "meta":
                acct = meta.connect(c, app_id, app_secret, code, pending["redirect_uri"], _ver())
                set_api_key("META_PAGE_ID", acct["page_id"])
                set_api_key("META_PAGE_TOKEN", acct["page_token"])
                set_api_key("META_PAGE_NAME", acct["page_name"])
                set_api_key("INSTAGRAM_USER_ID", acct["ig_user_id"])
                set_api_key("INSTAGRAM_USERNAME", acct["ig_username"])
                ig = (f" and Instagram @{acct['ig_username']}" if acct["ig_user_id"] else
                      ". No Instagram professional account is linked to this Page, so Instagram is not connected")
                more = (f" You shared {acct['pages']} Pages; this one was picked. To use another, connect again "
                        "and select only that Page." if acct["pages"] != "1" else "")
                return _page("Facebook connected", f"Reels will be posted to the Page {acct['page_name']}{ig}.{more}", True)
            tokens = tiktok.exchange_code(c, app_id, app_secret, code, pending["redirect_uri"], pending["verifier"])
            name = tiktok.user(c, tokens["access_token"])["name"]
            set_api_key("TIKTOK_REFRESH_TOKEN", tokens["refresh_token"])
            set_api_key("TIKTOK_ACCOUNT_NAME", name)
            return _page("TikTok connected", f"Videos will be posted to {name}.", True)
    except (SocialError, httpx.HTTPError, KeyError) as e:
        return _page("Not connected", str(e), False)


@router.post("/{login}/disconnect")
def disconnect(login: str) -> dict[str, Any]:
    for k in TOKEN_KEYS[_login(login)]:
        set_api_key(k, "")
    return {"ok": True}


@router.post("/{login}/test")
def test(login: str) -> dict[str, Any]:
    """Read-only check that the saved login still works. Posts nothing."""
    _login(login)
    try:
        with http() as c:
            if login == "youtube":
                return {"ok": True, "account": youtube.channel(c, _youtube_token(c))["name"]}
            if login == "meta":
                if not connected("facebook"):
                    raise SocialError("Facebook is not connected.")
                a = meta.accounts(c, _ver(), get_key("META_PAGE_ID"), get_key("META_PAGE_TOKEN"))
                return {"ok": True, "account": a["page_name"] + (f" + Instagram @{a['ig_username']}" if a["ig_user_id"] else "")}
            token = _tiktok_token(c)
            info = tiktok.creator_info(c, token)
            return {"ok": True, "account": info.get("creator_nickname") or info.get("creator_username", ""),
                    "privacy_options": info.get("privacy_level_options", [])}
    except (SocialError, httpx.HTTPError) as e:
        raise HTTPException(400, str(e))


# --- posting ---------------------------------------------------------------------

def _youtube_token(c: httpx.Client) -> str:
    if not connected("youtube"):
        raise SocialError("YouTube is not connected.")
    return youtube.access_token(c, get_key("YOUTUBE_CLIENT_ID"), get_key("YOUTUBE_CLIENT_SECRET"),
                                get_key("YOUTUBE_REFRESH_TOKEN"))


def _tiktok_token(c: httpx.Client) -> str:
    if not connected("tiktok"):
        raise SocialError("TikTok is not connected.")
    tokens = tiktok.refresh(c, get_key("TIKTOK_CLIENT_KEY"), get_key("TIKTOK_CLIENT_SECRET"),
                            get_key("TIKTOK_REFRESH_TOKEN"))
    if tokens.get("refresh_token") and tokens["refresh_token"] != get_key("TIKTOK_REFRESH_TOKEN"):
        set_api_key("TIKTOK_REFRESH_TOKEN", tokens["refresh_token"])
    return tokens["access_token"]


def post_video(c: httpx.Client, platform: str, path: Path, title: str, text: str,
               tags: list[str] | None = None) -> dict[str, Any]:
    """Post one video to one app. Returns {post_id, url}; raises SocialError."""
    cfg = load_config().get("social", {})
    if platform == "youtube":
        return youtube.upload(c, _youtube_token(c), path, title, text, tags, cfg.get("youtube_privacy", "public"))
    if platform in ("instagram", "facebook"):
        if not connected(platform):
            raise SocialError(f"{platform.title()} is not connected.")
        token = get_key("META_PAGE_TOKEN")
        if platform == "instagram":
            return meta.post_instagram(c, _ver(), get_key("INSTAGRAM_USER_ID"), token, path, text)
        return meta.post_facebook(c, _ver(), get_key("META_PAGE_ID"), token, path, text)
    if platform == "tiktok":
        return tiktok.post(c, _tiktok_token(c), path, text, cfg.get("tiktok_privacy", "PUBLIC_TO_EVERYONE"))
    raise SocialError(f"Unknown app {platform}")
