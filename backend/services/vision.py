from __future__ import annotations
import base64
import json
from pathlib import Path

import httpx

from config import get_config

DASHSCOPE_OPENAI_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
VISION_MODEL = "qwen-vl-plus"


async def tag_image(image_path: str) -> dict:
    """
    Use Qwen VL via DashScope OpenAI-compatible API to tag and describe an image.
    Returns {"tags": [...], "description": "..."}.
    """
    api_key = get_config("DASHSCOPE_API_KEY")
    if not api_key:
        return {"tags": [], "description": "[DASHSCOPE_API_KEY 未配置]"}

    path = Path(image_path)
    if not path.exists():
        return {"tags": [], "description": f"[文件不存在: {image_path}]"}

    img_data = base64.b64encode(path.read_bytes()).decode("utf-8")
    ext = path.suffix.lower().lstrip(".")
    mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}
    mime = mime_map.get(ext, "jpeg")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请分析这张图片，返回 JSON 格式：\n"
                            '{"tags": ["标签1", "标签2", ...], "description": "一句话描述图片内容"}\n'
                            "标签用中文，5-10个关键词。只返回 JSON，不要其他内容。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{mime};base64,{img_data}",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 300,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(DASHSCOPE_OPENAI_URL, headers=headers, json=payload)

    if resp.status_code != 200:
        return {"tags": [], "description": f"[API 错误 {resp.status_code}: {resp.text[:100]}]"}

    try:
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(content)
    except Exception as e:
        return {"tags": [], "description": f"[解析失败: {str(e)[:100]}]"}


async def tag_images_batch(image_paths: list[str]) -> list[dict]:
    import asyncio
    tasks = [tag_image(p) for p in image_paths]
    return await asyncio.gather(*tasks)
