"""Facebook Page Reels and Instagram Reels through Meta's Graph API.

One Facebook Login gives a Page access token that doesn't expire. The same token posts Reels to the
Page and to the Instagram professional account linked to it. Both upload the file directly (no
public URL needed) to rupload.facebook.com.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from pipeline.social import SocialError, check

SCOPES = ("pages_show_list,pages_read_engagement,pages_manage_posts,business_management,"
          "instagram_basic,instagram_content_publish")


def graph(ver: str) -> str:
    return f"https://graph.facebook.com/{ver}"


def auth_url(app_id: str, redirect_uri: str, state: str, ver: str) -> str:
    return f"https://www.facebook.com/{ver}/dialog/oauth?" + urlencode({
        "client_id": app_id, "redirect_uri": redirect_uri, "state": state, "scope": SCOPES,
        "response_type": "code",
    })


def connect(client: httpx.Client, app_id: str, secret: str, code: str, redirect_uri: str, ver: str) -> dict[str, str]:
    """Trade the login code for a long-lived Page token and find the linked Instagram account."""
    g = graph(ver)
    short = check(client.get(f"{g}/oauth/access_token", params={
        "client_id": app_id, "client_secret": secret, "redirect_uri": redirect_uri, "code": code,
    }), "Connecting Facebook")["access_token"]
    long = check(client.get(f"{g}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret, "fb_exchange_token": short,
    }), "Getting a long-lived Facebook token")["access_token"]
    pages = check(client.get(f"{g}/me/accounts", params={
        "fields": "id,name,access_token,instagram_business_account{id,username}", "access_token": long,
    }), "Listing your Facebook Pages").get("data") or []
    if not pages:
        raise SocialError("No Facebook Page was shared with the app. Connect again and select your Page.")
    page = next((p for p in pages if p.get("instagram_business_account")), pages[0])
    ig = page.get("instagram_business_account") or {}
    return {"page_id": page["id"], "page_name": page["name"], "page_token": page["access_token"],
            "ig_user_id": ig.get("id", ""), "ig_username": ig.get("username", ""), "pages": str(len(pages))}


def accounts(client: httpx.Client, ver: str, page_id: str, token: str) -> dict[str, str]:
    data = check(client.get(f"{graph(ver)}/{page_id}", params={
        "fields": "name,instagram_business_account{id,username}", "access_token": token,
    }), "Reading your Facebook Page")
    ig = data.get("instagram_business_account") or {}
    return {"page_name": data.get("name", ""), "ig_user_id": ig.get("id", ""), "ig_username": ig.get("username", "")}


def _rupload(client: httpx.Client, url: str, token: str, path: Path, what: str) -> None:
    data = path.read_bytes()
    check(client.post(url, content=data, timeout=600, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data)),
    }), what)


def post_instagram(client: httpx.Client, ver: str, ig_user_id: str, token: str, path: Path, caption: str,
                   sleep: Callable[[float], None] = time.sleep, wait_s: float = 600) -> dict[str, Any]:
    g = graph(ver)
    box = check(client.post(f"{g}/{ig_user_id}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true",
        "access_token": token,
    }), "Starting the Instagram upload")
    container = box["id"]
    _rupload(client, box.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{ver}/{container}",
             token, path, "Uploading to Instagram")
    waited = 0.0
    while True:
        st = check(client.get(f"{g}/{container}", params={"fields": "status_code,status", "access_token": token}),
                   "Checking the Instagram upload")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise SocialError(f"Instagram could not process the video: {st.get('status') or code}")
        if waited >= wait_s:
            raise SocialError("Instagram is still processing the video after 10 minutes. Try again later.")
        sleep(5)
        waited += 5
    media = check(client.post(f"{g}/{ig_user_id}/media_publish", data={"creation_id": container, "access_token": token}),
                  "Publishing on Instagram")["id"]
    link = check(client.get(f"{g}/{media}", params={"fields": "permalink", "access_token": token}),
                 "Reading the Instagram link").get("permalink")
    return {"post_id": media, "url": link or "https://www.instagram.com/"}


def post_facebook(client: httpx.Client, ver: str, page_id: str, token: str, path: Path, description: str,
                  sleep: Callable[[float], None] = time.sleep, wait_s: float = 600) -> dict[str, Any]:
    g = graph(ver)
    start = check(client.post(f"{g}/{page_id}/video_reels", data={"upload_phase": "start", "access_token": token}),
                  "Starting the Facebook upload")
    vid = start["video_id"]
    _rupload(client, start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{ver}/{vid}",
             token, path, "Uploading to Facebook")
    done = check(client.post(f"{g}/{page_id}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": description,
        "access_token": token,
    }), "Publishing on Facebook")
    if done.get("success") is False:
        raise SocialError("Facebook did not accept the Reel.")
    waited = 0.0
    while waited < wait_s:
        st = check(client.get(f"{g}/{vid}", params={"fields": "status", "access_token": token}),
                   "Checking the Facebook upload").get("status") or {}
        if st.get("video_status") == "error" or (st.get("processing_phase") or {}).get("status") == "error":
            err = (st.get("processing_phase") or {}).get("errors") or st
            raise SocialError(f"Facebook could not process the video: {err}")
        if (st.get("publishing_phase") or {}).get("status") == "complete" or st.get("video_status") == "ready":
            break
        sleep(5)
        waited += 5
    return {"post_id": vid, "url": f"https://www.facebook.com/reel/{vid}"}
