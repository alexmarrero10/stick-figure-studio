"""TikTok Content Posting API (Direct Post): Login Kit OAuth, then upload the file in one chunk."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from pipeline.social import SocialError

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.publish"


def _check(r: httpx.Response, what: str) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        raise SocialError(f"{what} failed ({r.status_code}): {r.text[:300]}")
    err = body.get("error")
    if isinstance(err, dict) and err.get("code") not in (None, "ok"):
        raise SocialError(f"{what} failed: {err.get('message') or err.get('code')} ({err.get('code')})")
    if isinstance(err, str):  # the OAuth endpoint reports errors this way
        raise SocialError(f"{what} failed: {body.get('error_description') or err}")
    if r.status_code >= 400:
        raise SocialError(f"{what} failed ({r.status_code}): {r.text[:300]}")
    return body.get("data", body)


def auth_url(client_key: str, redirect_uri: str, state: str, challenge_hex: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_key": client_key, "response_type": "code", "scope": SCOPES, "redirect_uri": redirect_uri,
        "state": state, "code_challenge": challenge_hex, "code_challenge_method": "S256",
    })


def _token(client: httpx.Client, form: dict[str, str], what: str) -> dict[str, Any]:
    return _check(client.post(f"{API}/oauth/token/", data=form,
                              headers={"Content-Type": "application/x-www-form-urlencoded"}), what)


def exchange_code(client: httpx.Client, key: str, secret: str, code: str, redirect_uri: str,
                  verifier: str) -> dict[str, Any]:
    """{access_token, refresh_token, open_id, ...}"""
    return _token(client, {"client_key": key, "client_secret": secret, "code": code,
                           "grant_type": "authorization_code", "redirect_uri": redirect_uri,
                           "code_verifier": verifier}, "Connecting TikTok")


def refresh(client: httpx.Client, key: str, secret: str, refresh_token: str) -> dict[str, Any]:
    """A fresh access token. TikTok may also hand back a new refresh token, which must be kept."""
    try:
        return _token(client, {"client_key": key, "client_secret": secret, "grant_type": "refresh_token",
                               "refresh_token": refresh_token}, "Refreshing TikTok access")
    except SocialError as e:
        raise SocialError(f"{e}. Connect TikTok again on the Settings page.") from e


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}


def user(client: httpx.Client, token: str) -> dict[str, str]:
    data = _check(client.get(f"{API}/user/info/", params={"fields": "open_id,display_name"},
                             headers={"Authorization": f"Bearer {token}"}), "Reading your TikTok account")
    return {"name": (data.get("user") or {}).get("display_name", "")}


def creator_info(client: httpx.Client, token: str) -> dict[str, Any]:
    return _check(client.post(f"{API}/post/publish/creator_info/query/", headers=_auth(token), json={}),
                  "Checking your TikTok account")


def post(client: httpx.Client, token: str, path: Path, caption: str, privacy: str = "PUBLIC_TO_EVERYONE",
         sleep: Callable[[float], None] = time.sleep, wait_s: float = 600) -> dict[str, Any]:
    info = creator_info(client, token)
    options = info.get("privacy_level_options") or []
    if options and privacy not in options:
        raise SocialError(f"TikTok won't allow the privacy setting {privacy} for this account "
                          f"(allowed: {', '.join(options)}). Change it on the Settings page.")
    size = path.stat().st_size
    if size > 64 * 1024 * 1024:
        raise SocialError("The Short is over 64 MB, too big to send to TikTok in one piece.")
    init = _check(client.post(f"{API}/post/publish/video/init/", headers=_auth(token), json={
        "post_info": {"title": caption[:2200], "privacy_level": privacy, "disable_duet": False,
                      "disable_comment": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
    }), "Starting the TikTok upload")
    r = client.put(init["upload_url"], content=path.read_bytes(), timeout=600, headers={
        "Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}",
    })
    if r.status_code >= 400:
        raise SocialError(f"Uploading to TikTok failed ({r.status_code}): {r.text[:300]}")
    publish_id = init["publish_id"]
    waited = 0.0
    while True:
        st = _check(client.post(f"{API}/post/publish/status/fetch/", headers=_auth(token),
                                json={"publish_id": publish_id}), "Checking the TikTok upload")
        status = st.get("status")
        if status == "PUBLISH_COMPLETE":
            ids = st.get("publicaly_available_post_id") or []
            who = info.get("creator_username", "")
            url = f"https://www.tiktok.com/@{who}/video/{ids[0]}" if ids and who else "https://www.tiktok.com/"
            return {"post_id": str(ids[0]) if ids else publish_id, "url": url}
        if status == "FAILED":
            raise SocialError(f"TikTok could not publish the video: {st.get('fail_reason') or 'unknown reason'}")
        if waited >= wait_s:
            raise SocialError("TikTok is still processing the video after 10 minutes. Check the TikTok app.")
        sleep(5)
        waited += 5
