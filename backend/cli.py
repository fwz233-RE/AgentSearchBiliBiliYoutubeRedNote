#!/usr/bin/env python3
"""
Content Hub CLI — 多平台内容聚合抓取工具（命令行版）

支持 YouTube、Bilibili、小红书 的搜索、抓取、字幕获取与 AI 打标。
可编译为 Windows / macOS / Linux 独立可执行文件。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# 确保当前目录在 sys.path 中，以便 PyInstaller 打包后也能找到模块
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的运行路径
    _BUNDLE_DIR = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
    os.chdir(_BUNDLE_DIR)
    sys.path.insert(0, str(_BUNDLE_DIR))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    try:
        if sys.stdout and getattr(sys.stdout, 'encoding', None):
            sys.stdout.reconfigure(encoding=sys.stdout.encoding, errors="replace")
        if sys.stderr and getattr(sys.stderr, 'encoding', None):
            sys.stderr.reconfigure(encoding=sys.stderr.encoding, errors="replace")
    except Exception:
        pass

from config import get_config, set_config, get_all_config, _ALL_KEYS, DATA_DIR, SUBTITLES_DIR
from database import init_db, close_db, async_session, Content, ScrapeRecord, ContentImage, Task


# ── 颜色输出工具 ──────────────────────────────────────────────────

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    DIM = "\033[2m"


def _c(text: str, color: str) -> str:
    """给文字添加颜色"""
    return f"{color}{text}{Colors.RESET}"


def _header(text: str):
    print(f"\n{_c('═' * 60, Colors.CYAN)}")
    print(f"  {_c(text, Colors.BOLD + Colors.CYAN)}")
    print(f"{_c('═' * 60, Colors.CYAN)}\n")


def _success(text: str):
    print(f"  {_c('✓', Colors.GREEN)} {text}")


def _error(text: str):
    print(f"  {_c('✗', Colors.RED)} {text}")


def _info(text: str):
    print(f"  {_c('→', Colors.BLUE)} {text}")


def _warn(text: str):
    print(f"  {_c('!', Colors.YELLOW)} {text}")


# ── 异步运行辅助 ──────────────────────────────────────────────────

def _run(coro):
    """跨平台运行异步函数"""
    async def _wrapper():
        try:
            return await coro
        finally:
            await close_db()
    return asyncio.run(_wrapper())


# ── 搜索命令 ──────────────────────────────────────────────────────

async def _do_search(platform: str, query: str, page: int, page_size: int, fmt: Optional[str] = None, output_file: Optional[str] = None):
    await init_db()

    from scrapers.youtube import youtube_search
    from scrapers.bilibili import bilibili_search
    from scrapers.xiaohongshu import xiaohongshu_search

    title = "搜索 {} — \"{}\"".format(platform.upper(), query)
    _header(title)

    if platform == "youtube":
        results = await youtube_search(query, page, page_size)
    elif platform == "bilibili":
        results = await bilibili_search(query, page, page_size)
    elif platform == "xiaohongshu":
        results = await xiaohongshu_search(query, page, page_size)
    else:
        _error(f"不支持的平台: {platform}")
        return

    if not results:
        _warn("没有找到结果")
        return

    for i, r in enumerate(results, 1):
        try:
            print(f"  {_c(str(i), Colors.YELLOW)}. {_c(r.title or '(无标题)', Colors.BOLD)}")
            if r.author:
                print(f"     {_c('作者:', Colors.DIM)} {r.author}")
            if r.url:
                print(f"     {_c('链接:', Colors.DIM)} {r.url}")
            if r.duration:
                print(f"     {_c('时长:', Colors.DIM)} {r.duration}")
            if r.views is not None:
                try:
                    print(f"     {_c('播放:', Colors.DIM)} {int(r.views):,}")
                except (ValueError, TypeError):
                    print(f"     {_c('播放:', Colors.DIM)} {r.views}")
            print()
        except Exception:
            continue

    _success(f"共找到 {len(results)} 条结果 (第 {page} 页)")

    if output_file:
        items = []
        for r in results:
            items.append({
                "platform": r.platform,
                "platform_id": r.platform_id,
                "title": r.title,
                "author": r.author,
                "url": r.url,
                "thumbnail_url": r.thumbnail_url,
                "duration": r.duration,
                "views": r.views,
                "publish_time": r.publish_time,
            })
        if fmt == "json":
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            _success(f"已将搜索结果导出到 {output_file}")
        elif fmt == "csv":
            import csv
            with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
                if items:
                    writer = csv.DictWriter(f, fieldnames=items[0].keys())
                    writer.writeheader()
                    writer.writerows(items)
            _success(f"已将搜索结果导出到 {output_file}")


def cmd_search(args):
    query_str = " ".join(args.query) if isinstance(args.query, list) else args.query
    query_str = query_str.strip('"').strip("'")
    _run(_do_search(args.platform, query_str, args.page, args.page_size, args.format, args.output))


# ── 抓取命令 ──────────────────────────────────────────────────────

def _detect_platform(url: str) -> str:
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "bilibili.com" in url or "b23.tv" in url:
        return "bilibili"
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        return "xiaohongshu"
    return ""


async def _do_scrape(urls: list[str], auto_transcribe: bool, auto_tag: bool):
    await init_db()

    from scrapers.youtube import youtube_scrape, youtube_download_audio
    from scrapers.bilibili import bilibili_scrape, bilibili_download_audio
    from scrapers.xiaohongshu import xiaohongshu_scrape
    from services.transcription import transcribe_audio
    from services.vision import tag_image

    _header("批量抓取")

    for url in urls:
        url = url.strip()
        if not url:
            continue

        platform = _detect_platform(url)
        if not platform:
            _error(f"无法识别平台: {url}")
            continue

        _info(f"抓取中: {url} ({platform})")

        try:
            # 1. 抓取元数据
            if platform == "youtube":
                sc = await youtube_scrape(url)
            elif platform == "bilibili":
                sc = await bilibili_scrape(url)
            elif platform == "xiaohongshu":
                sc = await xiaohongshu_scrape(url)

            _success(f"标题: {sc.title}")
            _info(f"作者: {sc.author}")
            _info(f"类型: {sc.content_type}")
            _info(f"播放: {sc.metrics.views:,}  点赞: {sc.metrics.likes:,}")

            # 2. 下载音频
            audio_path = ""
            if sc.content_type == "video":
                _info("下载音频中...")
                try:
                    if platform == "youtube":
                        audio_path = await youtube_download_audio(url, sc.platform_id)
                    elif platform == "bilibili":
                        audio_path = await bilibili_download_audio(sc.platform_id)
                    elif platform == "xiaohongshu":
                        audio_path = sc.audio_path
                    if audio_path:
                        _success(f"音频已下载: {Path(audio_path).name}")
                except Exception:
                    _warn("音频下载失败")
                    traceback.print_exc()

            # 3. 语音转写
            if auto_transcribe and sc.content_type == "video" and sc.subtitle_source not in ("external", "ai_generated") and audio_path:
                _info("语音转写中...")
                try:
                    text = await transcribe_audio(audio_path)
                    if text and not text.startswith("["):
                        sc.subtitle_text = text
                        sc.subtitle_source = "transcribed"
                        _success(f"转写完成: {len(text)} 字")
                    else:
                        _warn(f"转写结果: {text[:100] if text else '无'}")
                except Exception:
                    _warn("转写失败")
                    traceback.print_exc()

            # 4. 保存到数据库
            async with async_session() as session:
                # 检查是否已存在
                from sqlalchemy import select
                result = await session.execute(
                    select(Content).where(
                        Content.platform == sc.platform,
                        Content.platform_id == sc.platform_id,
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    content = existing
                    content.title = sc.title or content.title
                    content.author = sc.author or content.author
                    content.description = sc.description or content.description
                    if sc.subtitle_text and not content.subtitle_text:
                        content.subtitle_text = sc.subtitle_text
                        content.subtitle_source = sc.subtitle_source
                else:
                    content = Content(
                        platform=sc.platform,
                        platform_id=sc.platform_id,
                        url=sc.url,
                        title=sc.title,
                        author=sc.author,
                        author_id=sc.author_id,
                        description=sc.description,
                        publish_time=sc.publish_time,
                        content_type=sc.content_type,
                        text_content=sc.text_content,
                        subtitle_text=sc.subtitle_text,
                        subtitle_source=sc.subtitle_source,
                        thumbnail_url=sc.thumbnail_url,
                        created_at=datetime.utcnow(),
                    )
                    session.add(content)
                    await session.flush()

                record = ScrapeRecord(
                    content_id=content.id,
                    scrape_time=datetime.utcnow(),
                    views=sc.metrics.views,
                    likes=sc.metrics.likes,
                    coins=sc.metrics.coins,
                    shares=sc.metrics.shares,
                    favorites=sc.metrics.favorites,
                    comments_count=sc.metrics.comments_count,
                )
                session.add(record)

                if not existing and sc.images:
                    for img in sc.images:
                        session.add(ContentImage(
                            content_id=content.id,
                            image_url=img.image_url,
                            local_path=img.local_path,
                        ))

                await session.commit()
                _success(f"已保存到数据库 (ID: {content.id})")

            # 5. AI 打标
            if auto_tag and sc.images:
                _info("AI 打标中...")
                async with async_session() as session:
                    for img in sc.images:
                        if img.local_path:
                            try:
                                tag_result = await tag_image(img.local_path)
                                _success(f"图片标签: {tag_result.get('tags', [])}")
                                await session.execute(
                                    ContentImage.__table__.update()
                                    .where(ContentImage.local_path == img.local_path)
                                    .values(
                                        ai_tags=tag_result.get("tags", []),
                                        ai_description=tag_result.get("description", ""),
                                    )
                                )
                            except Exception:
                                _warn(f"打标失败: {img.local_path}")
                    await session.commit()

            # 显示字幕摘要
            if sc.subtitle_text:
                _info(f"字幕来源: {sc.subtitle_source}")
                preview = sc.subtitle_text[:200].replace('\n', ' ')
                _info(f"字幕预览: {preview}...")
                
                # 计算字幕文件路径并显示
                sub_filename = f"{platform}_{sc.platform_id}.txt"
                sub_path = SUBTITLES_DIR / sub_filename
                if sub_path.exists():
                    _info(f"字幕文件: {sub_path}")

            print()

        except Exception as e:
            _error(f"抓取失败: {e}")
            traceback.print_exc()
            print()


def cmd_scrape(args):
    urls = args.urls
    # 支持从文件读取 URL 列表
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            urls.extend([line.strip() for line in f if line.strip()])
    if not urls:
        _error("请提供至少一个 URL")
        return
    _run(_do_scrape(urls, not args.no_transcribe, not args.no_tag))


# ── 内容列表命令 ──────────────────────────────────────────────────

async def _do_list(platform: Optional[str], page: int, page_size: int):
    await init_db()
    from sqlalchemy import select, func

    _header("内容列表")

    async with async_session() as session:
        q = select(Content).order_by(Content.created_at.desc())
        count_q = select(func.count()).select_from(Content)

        if platform:
            q = q.where(Content.platform == platform)
            count_q = count_q.where(Content.platform == platform)

        total = (await session.execute(count_q)).scalar() or 0
        q = q.offset((page - 1) * page_size).limit(page_size)
        result = await session.execute(q)
        contents = result.scalars().all()

        if not contents:
            _warn("暂无内容")
            return

        for c in contents:
            r = await session.execute(
                select(ScrapeRecord)
                .where(ScrapeRecord.content_id == c.id)
                .order_by(ScrapeRecord.scrape_time.desc())
                .limit(1)
            )
            latest = r.scalar_one_or_none()

            platform_icon = {"youtube": "🎬", "bilibili": "📺", "xiaohongshu": "📕"}.get(c.platform, "📄")
            print(f"  {_c(f'#{c.id}', Colors.YELLOW)} {platform_icon} {_c(c.title or '(无标题)', Colors.BOLD)}")
            print(f"     {_c('平台:', Colors.DIM)} {c.platform}  {_c('作者:', Colors.DIM)} {c.author}")
            print(f"     {_c('链接:', Colors.DIM)} {c.url}")
            if latest:
                print(f"     {_c('播放:', Colors.DIM)} {latest.views:,}  "
                      f"{_c('点赞:', Colors.DIM)} {latest.likes:,}  "
                      f"{_c('收藏:', Colors.DIM)} {latest.favorites:,}")
            if c.subtitle_text:
                print(f"     {_c('字幕:', Colors.DIM)} ✓ ({c.subtitle_source})")
            print()

        _success(f"共 {total} 条记录 (第 {page}/{(total + page_size - 1) // page_size} 页)")


def cmd_list(args):
    _run(_do_list(args.platform, args.page, args.page_size))


# ── 内容详情命令 ──────────────────────────────────────────────────

async def _do_show(content_id: int, show_subtitle: bool):
    await init_db()
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Content).where(Content.id == content_id))
        content = result.scalar_one_or_none()
        if not content:
            _error(f"内容 #{content_id} 不存在")
            return

        _header(f"内容详情 — #{content.id}")

        print(f"  {_c('标题:', Colors.CYAN)} {content.title}")
        print(f"  {_c('平台:', Colors.CYAN)} {content.platform}")
        print(f"  {_c('作者:', Colors.CYAN)} {content.author} ({content.author_id})")
        print(f"  {_c('链接:', Colors.CYAN)} {content.url}")
        print(f"  {_c('类型:', Colors.CYAN)} {content.content_type}")
        if content.publish_time:
            print(f"  {_c('发布:', Colors.CYAN)} {content.publish_time.isoformat()}")
        if content.description:
            print(f"  {_c('描述:', Colors.CYAN)} {content.description[:300]}")

        # 抓取记录
        records_r = await session.execute(
            select(ScrapeRecord)
            .where(ScrapeRecord.content_id == content_id)
            .order_by(ScrapeRecord.scrape_time.desc())
        )
        records = records_r.scalars().all()

        if records:
            print(f"\n  {_c('数据记录:', Colors.MAGENTA)}")
            for r in records:
                print(f"    {_c(r.scrape_time.isoformat() if r.scrape_time else '?', Colors.DIM)}: "
                      f"播放={r.views:,} 点赞={r.likes:,} 投币={r.coins:,} "
                      f"转发={r.shares:,} 收藏={r.favorites:,} 评论={r.comments_count:,}")

        # 图片
        images_r = await session.execute(
            select(ContentImage).where(ContentImage.content_id == content_id)
        )
        images = images_r.scalars().all()
        if images:
            print(f"\n  {_c('图片:', Colors.MAGENTA)} {len(images)} 张")
            for img in images:
                print(f"    {_c('URL:', Colors.DIM)} {img.image_url}")
                if img.local_path:
                    print(f"    {_c('本地:', Colors.DIM)} {img.local_path}")
                if img.ai_tags:
                    print(f"    {_c('标签:', Colors.DIM)} {img.ai_tags}")
                if img.ai_description:
                    print(f"    {_c('描述:', Colors.DIM)} {img.ai_description}")

        # 字幕
        if show_subtitle and content.subtitle_text:
            print(f"\n  {_c(f'字幕 ({content.subtitle_source}):', Colors.MAGENTA)}")
            print(f"  {'-' * 50}")
            for line in content.subtitle_text.splitlines():
                print(f"  {line}")
            print(f"  {'-' * 50}")
        elif content.subtitle_text:
            _info(f"有字幕 ({content.subtitle_source}, {len(content.subtitle_text)} 字) — 使用 --subtitle 显示")

        print()


def cmd_show(args):
    _run(_do_show(args.id, args.subtitle))


# ── 删除命令 ──────────────────────────────────────────────────────

async def _do_delete(content_ids: list[int]):
    await init_db()
    from sqlalchemy import select

    _header("删除内容")

    async with async_session() as session:
        deleted = 0
        for cid in content_ids:
            result = await session.execute(select(Content).where(Content.id == cid))
            content = result.scalar_one_or_none()
            if content:
                _info(f"删除 #{cid}: {content.title}")
                await session.delete(content)
                deleted += 1
            else:
                _warn(f"内容 #{cid} 不存在")
        await session.commit()
        _success(f"已删除 {deleted} 条记录")


def cmd_delete(args):
    _run(_do_delete(args.ids))


# ── 刷新命令 ──────────────────────────────────────────────────────

async def _do_refresh(content_ids: list[int]):
    await init_db()
    from sqlalchemy import select

    from scrapers.youtube import youtube_scrape
    from scrapers.bilibili import bilibili_scrape
    from scrapers.xiaohongshu import xiaohongshu_scrape

    _header("刷新内容指标")

    async with async_session() as session:
        for cid in content_ids:
            result = await session.execute(select(Content).where(Content.id == cid))
            content = result.scalar_one_or_none()
            if not content:
                _warn(f"内容 #{cid} 不存在")
                continue

            _info(f"刷新 #{cid}: {content.title}")

            try:
                if content.platform == "youtube":
                    sc = await youtube_scrape(content.url)
                elif content.platform == "bilibili":
                    sc = await bilibili_scrape(content.url)
                elif content.platform == "xiaohongshu":
                    sc = await xiaohongshu_scrape(content.url)
                else:
                    _warn(f"未知平台: {content.platform}")
                    continue

                record = ScrapeRecord(
                    content_id=cid,
                    scrape_time=datetime.utcnow(),
                    views=sc.metrics.views,
                    likes=sc.metrics.likes,
                    coins=sc.metrics.coins,
                    shares=sc.metrics.shares,
                    favorites=sc.metrics.favorites,
                    comments_count=sc.metrics.comments_count,
                )
                session.add(record)
                _success(f"播放={sc.metrics.views:,} 点赞={sc.metrics.likes:,}")
            except Exception as e:
                _error(f"刷新失败: {e}")

        await session.commit()


def cmd_refresh(args):
    _run(_do_refresh(args.ids))


# ── 配置命令 ──────────────────────────────────────────────────────

def cmd_config(args):

    if args.action == "list":
        _header("当前配置")
        config = get_all_config()
        for key, value in config.items():
            display_val = value if value else _c("(未配置)", Colors.DIM)
            if value == "configured":
                display_val = _c("✓ 已配置", Colors.GREEN)
            print(f"  {_c(key, Colors.CYAN)}: {display_val}")
        print()
        _info(f"配置文件: {DATA_DIR / 'config.json'}")

    elif args.action == "set":
        if not args.key or not args.value:
            _error("请提供 key 和 value 参数")
            return
        
        # 支持从文件读取配置值 (@path/to/file)
        if len(args.value) == 1 and args.value[0].startswith("@"):
            file_path = Path(args.value[0][1:])
            if file_path.exists():
                try:
                    value_str = file_path.read_text(encoding='utf-8')
                    _info(f"从文件读取配置值: {file_path}")
                except Exception as e:
                    _error(f"读取文件失败: {e}")
                    return
            else:
                _error(f"文件不存在: {file_path}")
                return
        else:
            value_str = " ".join(args.value) if isinstance(args.value, list) else args.value
        
        if args.key not in _ALL_KEYS:
            _error(f"未知配置项: {args.key}")
            _info(f"支持的配置项: {', '.join(_ALL_KEYS)}")
            return
        set_config(args.key, value_str)
        _success(f"已设置 {args.key}")

    elif args.action == "get":
        if not args.key:
            _error("请提供 key 参数")
            return
        val = get_config(args.key)
        if val:
            print(f"  {_c(args.key, Colors.CYAN)}: {val}")
        else:
            _warn(f"{args.key} 未配置")


# ── 导出命令 ──────────────────────────────────────────────────────

async def _do_export(platform: Optional[str], output: str, fmt: str):
    await init_db()
    from sqlalchemy import select

    _header("导出内容")

    async with async_session() as session:
        q = select(Content).order_by(Content.created_at.desc())
        if platform:
            q = q.where(Content.platform == platform)

        result = await session.execute(q)
        contents = result.scalars().all()

        if not contents:
            _warn("暂无可导出的内容")
            return

        items = []
        for c in contents:
            r = await session.execute(
                select(ScrapeRecord)
                .where(ScrapeRecord.content_id == c.id)
                .order_by(ScrapeRecord.scrape_time.desc())
                .limit(1)
            )
            latest = r.scalar_one_or_none()

            item = {
                "id": c.id,
                "platform": c.platform,
                "title": c.title,
                "author": c.author,
                "url": c.url,
                "content_type": c.content_type,
                "publish_time": c.publish_time.isoformat() if c.publish_time else None,
                "description": c.description,
                "subtitle_text": c.subtitle_text,
                "subtitle_source": c.subtitle_source,
                "views": latest.views if latest else 0,
                "likes": latest.likes if latest else 0,
                "coins": latest.coins if latest else 0,
                "shares": latest.shares if latest else 0,
                "favorites": latest.favorites if latest else 0,
                "comments_count": latest.comments_count if latest else 0,
            }
            items.append(item)

        if fmt == "json":
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        elif fmt == "csv":
            import csv
            with open(output, 'w', encoding='utf-8-sig', newline='') as f:
                if items:
                    writer = csv.DictWriter(f, fieldnames=items[0].keys())
                    writer.writeheader()
                    writer.writerows(items)

        _success(f"已导出 {len(items)} 条记录到 {output}")


def cmd_export(args):
    _run(_do_export(args.platform, args.output, args.format))


# ── 音频文件管理命令 ──────────────────────────────────────────────

def cmd_audio(args):
    from config import AUDIO_DIR

    if args.action == "list":
        _header("音频文件列表")
        if not AUDIO_DIR.exists():
            _warn("音频目录不存在")
            return

        files = sorted(AUDIO_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        files = [f for f in files if f.is_file() and not f.name.startswith('.')]

        if not files:
            _warn("暂无音频文件")
            return

        total_size = 0
        for f in files:
            stat = f.stat()
            size_mb = stat.st_size / 1024 / 1024
            total_size += stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  {_c(f.name, Colors.BOLD)}  {_c(f'{size_mb:.1f} MB', Colors.DIM)}  {_c(mtime, Colors.DIM)}")

        print()
        _success(f"共 {len(files)} 个文件, 总计 {total_size / 1024 / 1024:.1f} MB")

    elif args.action == "delete":
        if not args.filename:
            _error("请提供文件名")
            return
        file_path = AUDIO_DIR / args.filename
        if not file_path.exists():
            _error(f"文件不存在: {args.filename}")
            return
        file_path.unlink()
        _success(f"已删除: {args.filename}")


# ── 字幕提取命令 ──────────────────────────────────────────────────

async def _do_subtitle(content_id: int, output: Optional[str]):
    await init_db()
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Content).where(Content.id == content_id))
        content = result.scalar_one_or_none()
        if not content:
            _error(f"内容 #{content_id} 不存在")
            return

        if not content.subtitle_text:
            _warn(f"内容 #{content_id} 没有字幕")
            return

        if output:
            with open(output, 'w', encoding='utf-8') as f:
                f.write(content.subtitle_text)
            _success(f"字幕已保存到 {output}")
        else:
            print(content.subtitle_text)


def cmd_subtitle(args):
    _run(_do_subtitle(args.id, args.output))


# ── 主入口 ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="content-hub",
        description="Content Hub — 多平台内容聚合抓取工具 (YouTube / Bilibili / 小红书)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  content-hub search youtube Python 教程
  content-hub search bilibili 机器学习 --page 2
  content-hub scrape https://www.youtube.com/watch?v=xxx
  content-hub scrape --file urls.txt
  content-hub list --platform youtube
  content-hub show 1 --subtitle
  content-hub refresh 1 2 3
  content-hub export --format json --output data.json
  content-hub config list
  content-hub config set DASHSCOPE_API_KEY sk-xxxxx
  content-hub subtitle 1 --output sub.txt
  content-hub audio list
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # search 搜索
    p_search = subparsers.add_parser("search", help="搜索内容")
    p_search.add_argument("platform", choices=["youtube", "bilibili", "xiaohongshu"], help="搜索平台")
    p_search.add_argument("query", nargs="+", help="搜索关键词")
    p_search.add_argument("--page", type=int, default=1, help="页码 (默认: 1)")
    p_search.add_argument("--page-size", type=int, default=20, help="每页条数 (默认: 20)")
    p_search.add_argument("--format", "-F", choices=["json", "csv"], default="json", help="导出格式 (默认: json，仅搭配 --output 时有效)")
    p_search.add_argument("--output", "-o", help="输出文件路径 (将搜索结果导出到指定文件)")
    p_search.set_defaults(func=cmd_search)

    # scrape 抓取
    p_scrape = subparsers.add_parser("scrape", help="抓取内容 (支持多个URL)")
    p_scrape.add_argument("urls", nargs="*", default=[], help="要抓取的 URL 列表")
    p_scrape.add_argument("--file", "-f", help="从文件读取 URL 列表 (每行一个)")
    p_scrape.add_argument("--no-transcribe", action="store_true", help="不进行语音转写")
    p_scrape.add_argument("--no-tag", action="store_true", help="不进行图片 AI 打标")
    p_scrape.set_defaults(func=cmd_scrape)

    # list 列表
    p_list = subparsers.add_parser("list", help="查看已抓取的内容列表")
    p_list.add_argument("--platform", "-p", choices=["youtube", "bilibili", "xiaohongshu"], help="按平台筛选")
    p_list.add_argument("--page", type=int, default=1, help="页码 (默认: 1)")
    p_list.add_argument("--page-size", type=int, default=20, help="每页条数 (默认: 20)")
    p_list.set_defaults(func=cmd_list)

    # show 详情
    p_show = subparsers.add_parser("show", help="查看内容详情")
    p_show.add_argument("id", type=int, help="内容 ID")
    p_show.add_argument("--subtitle", "-s", action="store_true", help="显示完整字幕")
    p_show.set_defaults(func=cmd_show)

    # delete 删除
    p_delete = subparsers.add_parser("delete", help="删除内容")
    p_delete.add_argument("ids", nargs="+", type=int, help="要删除的内容 ID 列表")
    p_delete.set_defaults(func=cmd_delete)

    # refresh 刷新
    p_refresh = subparsers.add_parser("refresh", help="刷新内容数据指标")
    p_refresh.add_argument("ids", nargs="+", type=int, help="要刷新的内容 ID 列表")
    p_refresh.set_defaults(func=cmd_refresh)

    # config 配置
    p_config = subparsers.add_parser("config", help="管理配置")
    p_config.add_argument("action", choices=["list", "set", "get"], help="操作: list/set/get")
    p_config.add_argument("key", nargs="?", help="配置项名称")
    p_config.add_argument("value", nargs="*", help="配置项值 (set 时需要)")
    p_config.set_defaults(func=cmd_config)

    # export 导出
    p_export = subparsers.add_parser("export", help="导出内容数据")
    p_export.add_argument("--platform", "-p", choices=["youtube", "bilibili", "xiaohongshu"], help="按平台筛选")
    p_export.add_argument("--format", "-F", choices=["json", "csv"], default="json", help="导出格式 (默认: json)")
    p_export.add_argument("--output", "-o", default="export.json", help="输出文件路径 (默认: export.json)")
    p_export.set_defaults(func=cmd_export)

    # subtitle 字幕
    p_subtitle = subparsers.add_parser("subtitle", help="导出字幕文本")
    p_subtitle.add_argument("id", type=int, help="内容 ID")
    p_subtitle.add_argument("--output", "-o", help="输出文件路径 (不指定则打印到终端)")
    p_subtitle.set_defaults(func=cmd_subtitle)

    # audio 音频
    p_audio = subparsers.add_parser("audio", help="管理音频文件")
    p_audio.add_argument("action", choices=["list", "delete"], help="操作: list/delete")
    p_audio.add_argument("filename", nargs="?", help="文件名 (delete 时需要)")
    p_audio.set_defaults(func=cmd_audio)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
    os._exit(0)
