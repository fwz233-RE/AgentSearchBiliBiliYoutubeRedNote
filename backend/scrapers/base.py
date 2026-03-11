from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScrapedMetrics:
    views: int = 0
    likes: int = 0
    coins: int = 0
    shares: int = 0
    favorites: int = 0
    comments_count: int = 0


@dataclass
class ScrapedImage:
    image_url: str = ""
    local_path: str = ""


@dataclass
class ScrapedContent:
    platform: str = ""
    platform_id: str = ""
    url: str = ""
    title: str = ""
    author: str = ""
    author_id: str = ""
    description: str = ""
    publish_time: Optional[datetime] = None
    content_type: str = "video"  # video | image_text
    text_content: str = ""
    subtitle_text: str = ""
    subtitle_source: str = "none"  # external | transcribed | none
    thumbnail_url: str = ""
    metrics: ScrapedMetrics = field(default_factory=ScrapedMetrics)
    images: list[ScrapedImage] = field(default_factory=list)
    audio_path: str = ""


@dataclass
class SearchResult:
    platform: str = ""
    platform_id: str = ""
    url: str = ""
    title: str = ""
    author: str = ""
    thumbnail_url: str = ""
    duration: str = ""
    views: int = 0
    publish_time: str = ""
