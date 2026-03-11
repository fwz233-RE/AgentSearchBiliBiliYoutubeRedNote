from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, JSON,
    create_engine, event,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class Content(Base):
    __tablename__ = "contents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False, index=True)  # youtube / bilibili / xiaohongshu
    platform_id = Column(String(128), nullable=False, index=True)
    url = Column(Text, nullable=False)
    title = Column(Text, default="")
    author = Column(String(256), default="")
    author_id = Column(String(128), default="")
    description = Column(Text, default="")
    publish_time = Column(DateTime, nullable=True)
    content_type = Column(String(20), default="video")  # video / image_text
    text_content = Column(Text, default="")
    subtitle_text = Column(Text, default="")
    subtitle_source = Column(String(20), default="")  # external / transcribed / none
    thumbnail_url = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    scrape_records = relationship("ScrapeRecord", back_populates="content", cascade="all, delete-orphan")
    images = relationship("ContentImage", back_populates="content", cascade="all, delete-orphan")


class ScrapeRecord(Base):
    """Each scrape creates a record to track metric changes over time."""
    __tablename__ = "scrape_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, ForeignKey("contents.id"), nullable=False, index=True)
    scrape_time = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    coins = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    favorites = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)

    content = relationship("Content", back_populates="scrape_records")


class ContentImage(Base):
    __tablename__ = "content_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, ForeignKey("contents.id"), nullable=False, index=True)
    image_url = Column(Text, default="")
    local_path = Column(Text, default="")
    ai_tags = Column(JSON, default=list)
    ai_description = Column(Text, default="")

    content = relationship("Content", back_populates="images")


class Task(Base):
    """Background task queue for batch scrape/refresh operations."""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_type = Column(String(20), default="scrape")  # scrape / refresh
    url = Column(Text, default="")
    platform = Column(String(20), default="")
    content_id = Column(Integer, nullable=True)
    status = Column(String(20), default="pending", index=True)  # pending/running/succeeded/failed
    progress = Column(String(100), default="")
    error = Column(Text, default="")
    auto_transcribe = Column(Boolean, default=True)
    auto_tag_images = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def close_db():
    await engine.dispose()
