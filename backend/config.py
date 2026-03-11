import os
import sys
import json
from pathlib import Path

if getattr(sys, 'frozen', False):
    # Running as compiled PyInstaller executable
    BASE_DIR = Path(sys.executable).parent
else:
    # Running as python script
    BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
AUDIO_DIR = DATA_DIR / "audio"
SUBTITLES_DIR = DATA_DIR / "subtitles"
DB_PATH = DATA_DIR / "content_hub.db"
CONFIG_PATH = DATA_DIR / "config.json"

for d in [IMAGES_DIR, AUDIO_DIR, SUBTITLES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

_runtime_config: dict = {}

# Keys that contain secrets — never send raw values to frontend
_SECRET_KEYS = {"DASHSCOPE_API_KEY", "XHS_COOKIE", "BILIBILI_COOKIE", "YOUTUBE_COOKIES_TXT"}

# All known config keys
_ALL_KEYS = [
    "DASHSCOPE_API_KEY",
    "XHS_COOKIE", "BILIBILI_COOKIE", "YOUTUBE_COOKIES_TXT",
]


def _load_config():
    global _runtime_config
    if CONFIG_PATH.exists():
        try:
            _runtime_config = json.loads(CONFIG_PATH.read_text())
        except Exception:
            _runtime_config = {}


def _save_config():
    CONFIG_PATH.write_text(json.dumps(_runtime_config, indent=2, ensure_ascii=False))


def get_config(key: str, default: str = "") -> str:
    return _runtime_config.get(key, "") or os.getenv(key, default)


def set_config(key: str, value: str):
    _runtime_config[key] = value
    _save_config()


def get_all_config() -> dict:
    result = {}
    for k in _ALL_KEYS:
        val = get_config(k)
        if k in _SECRET_KEYS:
            result[k] = "configured" if val else ""
        else:
            result[k] = val
    return result


_load_config()

YOUTUBE_COOKIES_FILE = DATA_DIR / "youtube_cookies.txt"


def get_youtube_cookies_path() -> str | None:
    content = get_config("YOUTUBE_COOKIES_TXT")
    if not content:
        return None
    YOUTUBE_COOKIES_FILE.write_text(content, encoding="utf-8")
    return str(YOUTUBE_COOKIES_FILE)
