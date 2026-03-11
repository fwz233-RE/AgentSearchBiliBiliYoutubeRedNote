from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import yt_dlp

from config import AUDIO_DIR, SUBTITLES_DIR, get_youtube_cookies_path
from scrapers.base import ScrapedContent, ScrapedMetrics, SearchResult


def _yt_cookie_opts() -> dict:
    """Return yt-dlp opts for YouTube cookies if configured."""
    path = get_youtube_cookies_path()
    return {"cookiefile": path} if path else {}


def _parse_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _parse_upload_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d")
    except Exception:
        return None


async def youtube_search(query: str, page: int = 1, page_size: int = 20) -> list[SearchResult]:
    total_needed = page * page_size

    def _search():
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "ignore_no_formats_error": True,
            **_yt_cookie_opts(),
        }
        results = []
        with yt_dlp.YoutubeDL(opts) as ydl:
            search_url = f"ytsearch{total_needed}:{query}"
            info = ydl.extract_info(search_url, download=False)
            for entry in (info or {}).get("entries", []):
                if not entry:
                    continue
                thumb = entry.get("thumbnail", "")
                if not thumb and entry.get("thumbnails"):
                    thumb = entry["thumbnails"][0].get("url", "")
                results.append(SearchResult(
                    platform="youtube",
                    platform_id=entry.get("id", ""),
                    url=entry.get("url", "") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                    title=entry.get("title", ""),
                    author=entry.get("uploader", "") or entry.get("channel", ""),
                    thumbnail_url=thumb,
                    duration=_parse_duration(entry.get("duration")),
                    views=entry.get("view_count", 0) or 0,
                    publish_time=entry.get("upload_date", ""),
                ))
        return results

    all_results = await asyncio.to_thread(_search)
    start = (page - 1) * page_size
    return all_results[start:start + page_size]


async def youtube_scrape(url: str) -> ScrapedContent:
    def _scrape():
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "ignore_no_formats_error": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["zh-Hans", "zh-Hant", "zh", "en", "ja"],
            "subtitlesformat": "json3/srv3/vtt/best",
            **_yt_cookie_opts(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ValueError(f"Failed to extract info from {url}")

        video_id = info.get("id", "")
        subtitle_text = ""
        subtitle_source = "none"

        subs = info.get("subtitles", {})
        auto_subs = info.get("automatic_captions", {})

        sub_data = None
        for lang_key in ["zh-Hans", "zh-Hant", "zh", "en", "ja"]:
            if lang_key in subs:
                sub_data = subs[lang_key]
                subtitle_source = "external"
                break
        if not sub_data:
            for lang_key in ["zh-Hans", "zh-Hant", "zh", "en", "ja"]:
                if lang_key in auto_subs:
                    sub_data = auto_subs[lang_key]
                    subtitle_source = "ai_generated"
                    break

        if sub_data:
            json3 = next((s for s in sub_data if s.get("ext") == "json3"), None)
            if json3 and json3.get("url"):
                import httpx
                resp = httpx.get(json3["url"], timeout=30)
                if resp.status_code == 200:
                    j = resp.json()
                    lines = []
                    for ev in j.get("events", []):
                        segs = ev.get("segs", [])
                        text = "".join(s.get("utf8", "") for s in segs).strip()
                        if text and text != "\n":
                            lines.append(text)
                    subtitle_text = "\n".join(lines)

            if not subtitle_text:
                vtt = next((s for s in sub_data if s.get("ext") == "vtt"), None)
                if vtt and vtt.get("url"):
                    import httpx
                    resp = httpx.get(vtt["url"], timeout=30)
                    if resp.status_code == 200:
                        raw = resp.text
                        lines = []
                        for line in raw.splitlines():
                            if "-->" in line or line.strip().isdigit() or line.startswith("WEBVTT") or not line.strip():
                                continue
                            clean = re.sub(r"<[^>]+>", "", line).strip()
                            if clean and clean not in lines[-1:]:
                                lines.append(clean)
                        subtitle_text = "\n".join(lines)

        if subtitle_text:
            sub_path = SUBTITLES_DIR / f"youtube_{video_id}.txt"
            sub_path.write_text(subtitle_text, encoding="utf-8")

        return ScrapedContent(
            platform="youtube",
            platform_id=video_id,
            url=info.get("webpage_url", url),
            title=info.get("title", ""),
            author=info.get("uploader", "") or info.get("channel", ""),
            author_id=info.get("uploader_id", "") or info.get("channel_id", ""),
            description=info.get("description", ""),
            publish_time=_parse_upload_date(info.get("upload_date")),
            content_type="video",
            subtitle_text=subtitle_text,
            subtitle_source=subtitle_source,
            thumbnail_url=info.get("thumbnail", ""),
            metrics=ScrapedMetrics(
                views=info.get("view_count", 0) or 0,
                likes=info.get("like_count", 0) or 0,
                shares=0,
                comments_count=info.get("comment_count", 0) or 0,
            ),
        )

    return await asyncio.to_thread(_scrape)


async def youtube_download_audio(url: str, video_id: str) -> str:
    """Download audio for transcription. Returns path to audio file."""
    mp3_path = AUDIO_DIR / f"youtube_{video_id}.mp3"
    if mp3_path.exists():
        print(f"[YouTube] Audio already exists: {mp3_path}")
        return str(mp3_path)

    out_path = str(AUDIO_DIR / f"youtube_{video_id}.%(ext)s")

    def _download():
        cookie_opts = _yt_cookie_opts()
        formats_to_try = ["bestaudio/best", "ba/w/b", "worstaudio"]
        last_err = None
        for fmt in formats_to_try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "format": fmt,
                "outtmpl": out_path,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                "socket_timeout": 30,
                "retries": 3,
                **cookie_opts,
            }
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                print(f"[YouTube] Download succeeded with format={fmt}")
                return
            except Exception as e:
                last_err = e
                print(f"[YouTube] Format {fmt} failed: {e}")
                continue
        raise last_err or RuntimeError("All format attempts failed")

    await asyncio.to_thread(_download)

    if mp3_path.exists():
        print(f"[YouTube] Downloaded audio: {mp3_path}")
        return str(mp3_path)
    for f in AUDIO_DIR.glob(f"youtube_{video_id}.*"):
        print(f"[YouTube] Found audio file: {f}")
        return str(f)
    print(f"[YouTube] No audio file found after download for {video_id}")
    return ""
