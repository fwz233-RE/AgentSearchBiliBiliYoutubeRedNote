from __future__ import annotations
import asyncio
import json
from http import HTTPStatus
from pathlib import Path

import dashscope
import httpx
from dashscope.audio.asr import Transcription

from config import get_config, AUDIO_DIR

dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"


def _get_audio_public_url(audio_path: str) -> str:
    """Convert local audio path to a public URL served by our FastAPI."""
    filename = Path(audio_path).name
    base = get_config("SERVER_BASE_URL", "https://www.fwz233.com")
    return f"{base}/api/audio/{filename}"


async def transcribe_audio(audio_path: str, language: str = "zh") -> str:
    api_key = get_config("DASHSCOPE_API_KEY")
    if not api_key:
        return "[DASHSCOPE_API_KEY 未配置，无法转写]"

    path = Path(audio_path)
    if not path.exists():
        return f"[音频文件不存在: {audio_path}]"

    file_url = _get_audio_public_url(audio_path)

    def _run_transcription():
        dashscope.api_key = api_key

        task_response = Transcription.async_call(
            model="fun-asr",
            file_urls=[file_url],
            language_hints=[language, "en"] if language != "en" else ["en", "zh"],
        )

        if task_response.status_code != HTTPStatus.OK:
            return f"[提交转写任务失败: {task_response.status_code} {task_response.message}]"

        result = Transcription.wait(task=task_response.output.task_id)

        if result.status_code != HTTPStatus.OK:
            return f"[转写任务失败: {result.status_code} {result.message}]"

        output = result.output
        if output.task_status != "SUCCEEDED":
            return f"[转写任务状态: {output.task_status}]"

        results = output.get("results", [])
        if not results:
            return "[转写无结果]"

        all_text = []
        for item in results:
            if item.get("subtask_status") != "SUCCEEDED":
                continue
            transcription_url = item.get("transcription_url", "")
            if not transcription_url:
                continue
            try:
                resp = httpx.get(transcription_url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    for transcript in data.get("transcripts", []):
                        sentences = transcript.get("sentences", [])
                        for s in sentences:
                            text = s.get("text", "").strip()
                            if text:
                                all_text.append(text)
            except Exception:
                pass

        return "\n".join(all_text) if all_text else "[转写完成但无文本结果]"

    return await asyncio.to_thread(_run_transcription)
