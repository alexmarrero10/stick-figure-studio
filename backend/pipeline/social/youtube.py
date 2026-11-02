"""YouTube Data API v3: OAuth for a desktop app, then a resumable upload. A vertical video under
three minutes is published as a Short automatically."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from pipeline.social import SocialError, check

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES,
        "state": state, "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256",
    })


def exchange_code(client: httpx.Client, client_id: str, secret: str, code: str, redirect_uri: str,
                  verifier: str) -> str:
    """Returns the refresh token, which the app keeps to upload later without asking again."""
    data = check(client.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": secret, "code": code, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri, "code_verifier": verifier,
    }), "Connecting YouTube")
    if not data.get("refresh_token"):
        raise SocialError("Google did not return a refresh token. Remove the app's access at "
                          "myaccount.google.com/permissions and connect again.")
    return data["refresh_token"]


def access_token(client: httpx.Client, client_id: str, secret: str, refresh_token: str) -> str:
    r = client.post(TOKEN_URL, data={"client_id": client_id, "client_secret": secret,
                                     "refresh_token": refresh_token, "grant_type": "refresh_token"})
    if r.status_code == 400 and "invalid_grant" in r.text:
        raise SocialError("YouTube access has expired or was revoked. Connect YouTube again on the Settings "
                          "page. (Google expires it after 7 days while the OAuth app is in Testing mode.)")
    return check(r, "Refreshing YouTube access")["access_token"]


def channel(client: httpx.Client, token: str) -> dict[str, str]:
    data = check(client.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                            headers={"Authorization": f"Bearer {token}"}), "Reading your YouTube channel")
    items = data.get("items") or []
    if not items:
        raise SocialError("This Google account has no YouTube channel.")
    return {"id": items[0]["id"], "name": items[0]["snippet"]["title"]}


def upload(client: httpx.Client, token: str, path: Path, title: str, description: str,
           tags: list[str] | None = None, privacy: str = "public") -> dict[str, Any]:
    size = path.stat().st_size
    meta = {
        "snippet": {"title": title, "description": description, "tags": tags or [], "categoryId": "27"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    r = client.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=meta,
                    headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                             "X-Upload-Content-Length": str(size)})
    check(r, "Starting the YouTube upload")
    location = r.headers.get("location")
    if not location:
        raise SocialError("YouTube did not return an upload address.")
    data = check(client.put(location, content=path.read_bytes(),
                            headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"},
                            timeout=600), "Uploading to YouTube")
    vid = data["id"]
    return {"post_id": vid, "url": f"https://www.youtube.com/shorts/{vid}"}
