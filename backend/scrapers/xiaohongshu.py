from __future__ import annotations
import asyncio
import json
import random
import string
from datetime import datetime
from pathlib import Path

import httpx
from xhshow import Xhshow

from config import IMAGES_DIR, AUDIO_DIR, get_config
from scrapers.base import ScrapedContent, ScrapedMetrics, ScrapedImage, SearchResult

_xhs_signer = Xhshow()

_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.xiaohongshu.com/",
    "Origin": "https://www.xiaohongshu.com",
    "Content-Type": "application/json;charset=UTF-8",
}

_SEARCH_API = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
_FEED_API = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
_HOMEFEED_API = "https://edith.xiaohongshu.com/api/sns/web/v1/homefeed"


def _gen_search_id() -> str:
    return "2c" + "".join(random.choices(string.ascii_lowercase + string.digits, k=19))


def _build_headers(cookie: str, sign_headers: dict) -> dict:
    return {**_BASE_HEADERS, "Cookie": cookie, **sign_headers}


def _fix_img_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def _extract_note_id(url: str) -> str:
    import re
    patterns = [
        r"/explore/([a-f0-9]+)",
        r"/discovery/item/([a-f0-9]+)",
        r"/note/([a-f0-9]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    m = re.search(r"([a-f0-9]{24})", url)
    if m:
        return m.group(1)
    return ""


def _extract_xsec_token(url: str) -> str:
    import re
    m = re.search(r"xsec_token=([^&]+)", url)
    return m.group(1) if m else ""


async def xiaohongshu_search(query: str, page: int = 1, page_size: int = 20) -> list[SearchResult]:
    xhs_cookie = get_config("XHS_COOKIE")
    if not xhs_cookie:
        return [SearchResult(
            platform="xiaohongshu",
            title="[需要在设置页配置小红书 Cookie 才能搜索]",
            url="",
        )]

    def _search():
        body = {
            "keyword": query,
            "page": page,
            "page_size": page_size,
            "search_id": _gen_search_id(),
            "sort": "general",
            "note_type": 0,
            "ext_flags": [],
            "image_formats": ["jpg", "webp", "avif"],
        }
        sign = _xhs_signer.sign_headers_post(uri=_SEARCH_API, cookies=xhs_cookie, payload=body)
        headers = _build_headers(xhs_cookie, sign)
        raw_body = _xhs_signer.build_json_body(body)

        resp = httpx.post(_SEARCH_API, content=raw_body, headers=headers, timeout=15, follow_redirects=True)
        data = resp.json()
        if not data.get("success"):
            raise ValueError(f"XHS search failed: {data.get('msg', 'unknown')}")

        results = []
        for item in (data.get("data") or {}).get("items", []):
            nc = item.get("note_card", {})
            if not nc:
                continue
            note_id = item.get("id", "")
            if not note_id:
                continue
            title = nc.get("display_title", "")
            if not title:
                continue
            user = nc.get("user", {})
            cover = nc.get("cover", {})
            interact = nc.get("interact_info", {})
            xsec_token = item.get("xsec_token", "")

            cover_url = _fix_img_url(
                cover.get("url_default", "")
                or (cover.get("info_list", [{}])[0].get("url", "") if cover.get("info_list") else "")
            )

            results.append(SearchResult(
                platform="xiaohongshu",
                platform_id=note_id,
                url=f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search",
                title=title,
                author=user.get("nick_name", "") or user.get("nickname", ""),
                thumbnail_url=cover_url,
                views=0,
                publish_time="",
            ))
        return results

    try:
        results = await asyncio.to_thread(_search)
        if not results:
            return [SearchResult(
                platform="xiaohongshu",
                title="[搜索无结果，可能被限频，请稍后重试或换个关键词]",
                url="",
            )]
        return results
    except Exception as e:
        return [SearchResult(
            platform="xiaohongshu",
            title=f"[搜索失败: {str(e)[:80]}]",
            url="",
        )]


async def _search_for_xsec_token(note_id: str, cookie: str) -> str:
    """Try to find a xsec_token for a specific note via homefeed."""
    def _fetch():
        body = {
            "cursor_score": "",
            "num": 40,
            "refresh_type": 1,
            "note_index": 0,
            "category": "homefeed_recommend",
            "image_formats": ["jpg", "webp", "avif"],
        }
        sign = _xhs_signer.sign_headers_post(uri=_HOMEFEED_API, cookies=cookie, payload=body)
        headers = _build_headers(cookie, sign)
        resp = httpx.post(_HOMEFEED_API, content=_xhs_signer.build_json_body(body), headers=headers, timeout=15, follow_redirects=True)
        data = resp.json()
        for item in data.get("data", {}).get("items", []):
            if item.get("id") == note_id:
                return item.get("xsec_token", "")
        return ""
    return await asyncio.to_thread(_fetch)


def _extract_xhs_video_url(nc: dict) -> str:
    """
    Extract video download URL from note_card data.
    Logic from JoeanAmier/XHS-Downloader (source/application/video.py):
      1. video.consumer.originVideoKey → https://sns-video-bd.xhscdn.com/{key}
      2. Fallback: video.media.stream.h264/h265 → backupUrls or masterUrl
    """
    video_info = nc.get("video", {})

    origin_key = video_info.get("consumer", {}).get("originVideoKey", "")
    if origin_key:
        return f"https://sns-video-bd.xhscdn.com/{origin_key}"

    media = video_info.get("media", {})
    stream = media.get("stream", {})
    all_streams = []
    for codec in ["h264", "h265", "h266", "av1"]:
        items = stream.get(codec, [])
        if isinstance(items, list):
            all_streams.extend(items)

    if all_streams:
        all_streams.sort(key=lambda x: x.get("height", 0) or 0, reverse=True)
        best = all_streams[0]
        backup = best.get("backupUrls") or best.get("backup_urls") or []
        if backup:
            return backup[0]
        master = best.get("masterUrl") or best.get("master_url") or ""
        if master:
            return master

    for key in ["media", "video"]:
        sub = video_info.get(key, {})
        if isinstance(sub, dict):
            for url_key in ["originVideoKey", "videoKey", "streamUrl"]:
                v = sub.get(url_key, "")
                if v and v.startswith("http"):
                    return v
                if v and not v.startswith("http"):
                    return f"https://sns-video-bd.xhscdn.com/{v}"

    return ""


async def _download_image(client: httpx.AsyncClient, img_url: str, note_id: str, idx: int) -> ScrapedImage:
    try:
        img_url = _fix_img_url(img_url)
        resp = await client.get(img_url, timeout=30)
        if resp.status_code == 200:
            ext = "jpg"
            ct = resp.headers.get("content-type", "")
            if "png" in ct:
                ext = "png"
            elif "webp" in ct:
                ext = "webp"
            local_name = f"xhs_{note_id}_{idx}.{ext}"
            local_path = IMAGES_DIR / local_name
            local_path.write_bytes(resp.content)
            return ScrapedImage(image_url=img_url, local_path=str(local_path))
    except Exception:
        pass
    return ScrapedImage(image_url=img_url)


async def xiaohongshu_scrape(url: str) -> ScrapedContent:
    note_id = _extract_note_id(url)
    if not note_id:
        raise ValueError(f"Cannot extract note ID from: {url}")

    xhs_cookie = get_config("XHS_COOKIE")
    if not xhs_cookie:
        raise ValueError("需要在设置页配置小红书 Cookie")

    xsec_token = _extract_xsec_token(url)
    xsec_source = "pc_search"

    if not xsec_token:
        xsec_token = await _search_for_xsec_token(note_id, xhs_cookie)
        xsec_source = "pc_feed"

    if not xsec_token:
        raise ValueError(
            "无法获取该笔记的访问令牌。小红书限制了直接链接访问，"
            "请使用搜索功能找到该笔记后点击抓取"
        )

    def _scrape():
        body = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        sign = _xhs_signer.sign_headers_post(uri=_FEED_API, cookies=xhs_cookie, payload=body)
        headers = _build_headers(xhs_cookie, sign)
        resp = httpx.post(_FEED_API, content=_xhs_signer.build_json_body(body), headers=headers, timeout=15, follow_redirects=True)
        return resp.json()

    data = await asyncio.to_thread(_scrape)

    if data.get("code") == 300031:
        raise ValueError("小红书返回 笔记暂时无法浏览, 可能需要更新 Cookie 或稍后重试")

    items = data.get("data", {}).get("items", [])
    if not items:
        raise ValueError(f"未获取到笔记数据 (code={data.get('code')})")

    nc = items[0].get("note_card", {})
    canonical_url = f"https://www.xiaohongshu.com/explore/{note_id}"

    title = nc.get("title", "")
    desc = nc.get("desc", "")
    note_type = nc.get("type", "normal")
    user = nc.get("user", {})
    interact = nc.get("interact_info", {})

    publish_time = None
    ts = nc.get("time")
    if ts:
        try:
            publish_time = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
        except Exception:
            pass

    content_type = "video" if note_type == "video" else "image_text"

    image_list_raw = nc.get("image_list", [])
    images: list[ScrapedImage] = []
    if image_list_raw and content_type == "image_text":
        async with httpx.AsyncClient(follow_redirects=True) as dl_client:
            tasks = []
            for idx, img in enumerate(image_list_raw):
                img_url = img.get("url_default", "")
                if not img_url and img.get("info_list"):
                    img_url = img["info_list"][0].get("url", "")
                if img_url:
                    tasks.append(_download_image(dl_client, img_url, note_id, idx))
            if tasks:
                images = await asyncio.gather(*tasks)

    audio_path = ""
    if content_type == "video":
        video_url = _extract_xhs_video_url(nc)
        print(f"[XHS] note={note_id} video_url={'found' if video_url else 'NOT FOUND'}")
        if video_url:
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=120) as dl_client:
                    r = await dl_client.get(video_url, headers={
                        "User-Agent": _BASE_HEADERS["User-Agent"],
                        "Referer": "https://www.xiaohongshu.com/",
                    })
                    if r.status_code == 200 and len(r.content) > 1000:
                        audio_file = AUDIO_DIR / f"xhs_{note_id}.mp4"
                        audio_file.write_bytes(r.content)
                        audio_path = str(audio_file)
                        print(f"[XHS] Downloaded video: {audio_file} ({len(r.content)} bytes)")
                    else:
                        print(f"[XHS] Video download failed: status={r.status_code} size={len(r.content)}")
            except Exception as e:
                print(f"[XHS] Video download error: {e}")

    cover_url = ""
    if image_list_raw:
        cover_url = _fix_img_url(image_list_raw[0].get("url_default", ""))
    elif nc.get("cover"):
        cover_url = _fix_img_url(nc["cover"].get("url_default", ""))

    return ScrapedContent(
        platform="xiaohongshu",
        platform_id=note_id,
        url=canonical_url,
        title=title,
        author=user.get("nickname", "") or user.get("nick_name", ""),
        author_id=user.get("user_id", ""),
        description=desc,
        publish_time=publish_time,
        content_type=content_type,
        text_content=f"{title}\n\n{desc}" if content_type == "image_text" else "",
        subtitle_text="",
        subtitle_source="none",
        thumbnail_url=cover_url,
        metrics=ScrapedMetrics(
            views=0,
            likes=int(interact.get("liked_count", 0) or 0),
            shares=int(interact.get("share_count", 0) or 0),
            favorites=int(interact.get("collected_count", 0) or 0),
            comments_count=int(interact.get("comment_count", 0) or 0),
        ),
        images=[img for img in images if img.image_url],
        audio_path=audio_path,
    )
