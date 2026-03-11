from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import httpx

from config import AUDIO_DIR, SUBTITLES_DIR, get_config
from scrapers.base import ScrapedContent, ScrapedMetrics, SearchResult


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _extract_bvid(url: str) -> str:
    m = re.search(r"(BV[\w]+)", url)
    return m.group(1) if m else ""


def _fix_pic_url(url: str) -> str:
    """Ensure Bilibili image URLs use https protocol."""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


async def bilibili_search(query: str, page: int = 1, page_size: int = 20) -> list[SearchResult]:
    """Search Bilibili by scraping search page HTML for initial state data."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    results = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            f"https://search.bilibili.com/all",
            params={"keyword": query},
            headers=headers,
        )
        html = resp.text

        # Extract unique BV IDs from search page HTML (~42 per page)
        all_bvids = re.findall(r'bilibili\.com/video/(BV[\w]+)', html)
        seen_bvids = set()
        unique_bvids = []
        for bvid in all_bvids:
            if bvid not in seen_bvids:
                seen_bvids.add(bvid)
                unique_bvids.append(bvid)

        # Server-side pagination over the extracted results
        start = (page - 1) * page_size
        page_bvids = unique_bvids[start:start + page_size]
        card_bvids = [(bvid, "") for bvid in page_bvids]

        view_headers = {
            "User-Agent": headers["User-Agent"],
            "Referer": "https://www.bilibili.com",
        }
        for bvid, title in card_bvids:
            try:
                vresp = await client.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params={"bvid": bvid},
                    headers=view_headers,
                )
                d = vresp.json().get("data", {})
                if not d:
                    results.append(SearchResult(
                        platform="bilibili",
                        platform_id=bvid,
                        url=f"https://www.bilibili.com/video/{bvid}",
                        title=title,
                    ))
                    continue
                stat = d.get("stat", {})
                owner = d.get("owner", {})
                results.append(SearchResult(
                    platform="bilibili",
                    platform_id=bvid,
                    url=f"https://www.bilibili.com/video/{bvid}",
                    title=d.get("title", title),
                    author=owner.get("name", ""),
                    thumbnail_url=_fix_pic_url(d.get("pic", "")),
                    duration=_format_duration(d.get("duration")),
                    views=stat.get("view", 0),
                    publish_time=datetime.fromtimestamp(d.get("pubdate", 0)).strftime("%Y-%m-%d") if d.get("pubdate") else "",
                ))
            except Exception:
                results.append(SearchResult(
                    platform="bilibili",
                    platform_id=bvid,
                    url=f"https://www.bilibili.com/video/{bvid}",
                    title=title,
                ))

    if not results:
        results.append(SearchResult(
            platform="bilibili",
            title="[搜索无结果] 请尝试其他关键词或直接粘贴视频链接抓取",
            url="",
        ))

    return results


async def _get_bilibili_subtitle(bvid: str) -> tuple[str, str]:
    """
    Fetch subtitle from Bilibili.
    Strategy (inspired by bilibili-subtitle project):
      1. Try player/wbi/v2 API (works for AI-generated subs without login)
      2. Fallback: scrape video page HTML for __INITIAL_STATE__ subtitle data
      3. Fallback: try player/v2 API (legacy)
    Returns (subtitle_text, source).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://www.bilibili.com/video/{bvid}",
    }
    bili_cookie = get_config("BILIBILI_COOKIE")
    if bili_cookie:
        headers["Cookie"] = bili_cookie

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid}, headers=headers,
        )
        view_data = resp.json().get("data", {})
        cid = view_data.get("cid")
        aid = view_data.get("aid")
        if not cid or not aid:
            return "", "none"

        subtitles_list = []

        # Method 1: player/wbi/v2 API
        for api_url in [
            "https://api.bilibili.com/x/player/wbi/v2",
            "https://api.bilibili.com/x/player/v2",
        ]:
            try:
                resp2 = await client.get(
                    api_url,
                    params={"aid": aid, "cid": cid, "bvid": bvid},
                    headers=headers,
                )
                player_data = resp2.json().get("data", {})
                subtitle_info = player_data.get("subtitle", {})
                subtitles_list = subtitle_info.get("subtitles", [])
                if subtitles_list:
                    break
            except Exception:
                continue

        # Method 2: Scrape page HTML for subtitle info
        if not subtitles_list:
            try:
                page_resp = await client.get(
                    f"https://www.bilibili.com/video/{bvid}",
                    headers=headers,
                )
                html = page_resp.text
                m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});\s*\(function", html, re.DOTALL)
                if m:
                    raw = m.group(1).replace("undefined", "null")
                    state = json.loads(raw)
                    # Try videoData.subtitle.list
                    sub_list = state.get("videoData", {}).get("subtitle", {}).get("list", [])
                    if sub_list:
                        subtitles_list = sub_list
            except Exception:
                pass

        if not subtitles_list:
            return "", "none"

        # Prefer: zh-CN > ai-zh > zh-Hans > zh > en > first available
        preferred_langs = ["zh-CN", "ai-zh", "zh-Hans", "zh", "en", "ja"]
        chosen = None
        for lang in preferred_langs:
            for sub in subtitles_list:
                sub_lan = sub.get("lan", "") or sub.get("lan_doc", "")
                if sub_lan == lang:
                    chosen = sub
                    break
            if chosen:
                break
        if not chosen:
            chosen = subtitles_list[0]

        sub_url = chosen.get("subtitle_url", "") or chosen.get("subtitleUrl", "")
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url

        if not sub_url:
            return "", "none"

        resp3 = await client.get(sub_url, headers=headers)
        sub_json = resp3.json()
        lines = []
        for item in sub_json.get("body", []):
            text = item.get("content", "").strip()
            if text:
                lines.append(text)

        chosen_lan = chosen.get("lan", "")
        if chosen_lan.startswith("ai"):
            source = "ai_generated"
        else:
            source = "external"

        return "\n".join(lines), source


async def bilibili_scrape(url: str) -> ScrapedContent:
    bvid = _extract_bvid(url)
    if not bvid:
        raise ValueError(f"Cannot extract BV ID from: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid}, headers=headers,
        )
        data = resp.json().get("data", {})

        stat = data.get("stat", {})
        owner = data.get("owner", {})

        publish_time = None
        pubdate = data.get("pubdate")
        if pubdate:
            publish_time = datetime.fromtimestamp(pubdate)

    subtitle_text, subtitle_source = await _get_bilibili_subtitle(bvid)

    if subtitle_text:
        sub_path = SUBTITLES_DIR / f"bilibili_{bvid}.txt"
        sub_path.write_text(subtitle_text, encoding="utf-8")

    return ScrapedContent(
        platform="bilibili",
        platform_id=bvid,
        url=f"https://www.bilibili.com/video/{bvid}",
        title=data.get("title", ""),
        author=owner.get("name", ""),
        author_id=str(owner.get("mid", "")),
        description=data.get("desc", ""),
        publish_time=publish_time,
        content_type="video",
        subtitle_text=subtitle_text,
        subtitle_source=subtitle_source,
        thumbnail_url=_fix_pic_url(data.get("pic", "")),
        metrics=ScrapedMetrics(
            views=stat.get("view", 0),
            likes=stat.get("like", 0),
            coins=stat.get("coin", 0),
            shares=stat.get("share", 0),
            favorites=stat.get("favorite", 0),
            comments_count=stat.get("reply", 0),
        ),
    )


async def bilibili_download_audio(bvid: str) -> str:
    """Download audio from Bilibili using its DASH API (avoids yt-dlp 412 errors)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://www.bilibili.com/video/{bvid}",
    }
    bili_cookie = get_config("BILIBILI_COOKIE")
    if bili_cookie:
        headers["Cookie"] = bili_cookie

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid}, headers=headers,
        )
        view_data = resp.json().get("data", {})
        cid = view_data.get("cid")
        aid = view_data.get("aid")
        if not cid or not aid:
            print(f"[Bilibili] Cannot get cid/aid for {bvid}")
            return ""

        # fnval=16 requests DASH format which separates audio/video streams
        resp2 = await client.get(
            "https://api.bilibili.com/x/player/playurl",
            params={"bvid": bvid, "avid": aid, "cid": cid, "fnval": 16, "fnver": 0, "fourk": 1},
            headers=headers,
        )
        play_data = resp2.json().get("data", {})
        dash = play_data.get("dash", {})
        if not dash:
            print(f"[Bilibili] No DASH data for {bvid}, trying wbi endpoint")
            resp3 = await client.get(
                "https://api.bilibili.com/x/player/wbi/playurl",
                params={"bvid": bvid, "avid": aid, "cid": cid, "fnval": 16, "fnver": 0, "fourk": 1},
                headers=headers,
            )
            play_data = resp3.json().get("data", {})
            dash = play_data.get("dash", {})

        audio_list = dash.get("audio") or []
        if not audio_list:
            print(f"[Bilibili] No audio streams found for {bvid}")
            return ""

        # Sort by bandwidth (higher = better quality), pick best
        audio_list.sort(key=lambda x: x.get("bandwidth", 0), reverse=True)
        audio_stream = audio_list[0]
        audio_url = audio_stream.get("baseUrl") or audio_stream.get("base_url") or ""
        if not audio_url:
            backup = audio_stream.get("backupUrl") or audio_stream.get("backup_url") or []
            audio_url = backup[0] if backup else ""

        if not audio_url:
            print(f"[Bilibili] No audio URL found for {bvid}")
            return ""

        print(f"[Bilibili] Downloading audio for {bvid} (bandwidth={audio_stream.get('bandwidth')})")
        dl_headers = {**headers, "Referer": "https://www.bilibili.com"}
        resp_audio = await client.get(audio_url, headers=dl_headers, timeout=120)
        if resp_audio.status_code == 200 and len(resp_audio.content) > 1000:
            audio_file = AUDIO_DIR / f"bilibili_{bvid}.m4s"
            audio_file.write_bytes(resp_audio.content)
            print(f"[Bilibili] Downloaded audio: {audio_file} ({len(resp_audio.content)} bytes)")
            return str(audio_file)
        else:
            print(f"[Bilibili] Audio download failed: status={resp_audio.status_code} size={len(resp_audio.content)}")
            return ""
