"""翻译相关 API 路由。"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from core.config import OllamaConfig, OpenAIConfig, TranslateConfig
from core.pipeline import ProgressEvent, TranslationPipeline
from core.translator.base import TranslatorConfig
from core.translator.ollama import OllamaTranslator
from core.translator.openai_compat import OpenAICompatTranslator

router = APIRouter(prefix="/api", tags=["translate"])

WORK_DIR = Path("/tmp/orange-translator")
WORK_DIR.mkdir(parents=True, exist_ok=True)

_tasks: dict[str, dict] = {}


@router.post("/translate")
async def start_translate(
    file: UploadFile,
    src: str = Form("en"),
    tgt: str = Form("zh"),
    engine: str = Form("ollama"),
    model: str = Form(""),
    temperature: float = Form(0.3),
    ollama_url: str = Form("http://localhost:11434"),
    api_key: str = Form(""),
    api_base: str = Form("https://api.openai.com/v1"),
) -> dict:
    """上传 EPUB 并启动翻译任务，返回 task_id。"""
    task_id = str(uuid.uuid4())
    task_dir = WORK_DIR / task_id
    task_dir.mkdir()

    epub_path = task_dir / (file.filename or "input.epub")
    epub_path.write_bytes(await file.read())
    output_path = task_dir / f"{epub_path.stem}_bilingual.epub"

    config = TranslateConfig(
        src_lang=src,
        tgt_lang=tgt,
        engine=engine,
        ollama=OllamaConfig(base_url=ollama_url, model=model),
        openai=OpenAIConfig(api_key=api_key, base_url=api_base, model=model or "gpt-4o-mini"),
    )
    translator_config = TranslatorConfig(src_lang=src, tgt_lang=tgt, model=model, temperature=temperature)

    _tasks[task_id] = {
        "status": "pending",
        "events": [],
        "output_path": str(output_path),
        "filename": f"{epub_path.stem}_bilingual.epub",
    }

    asyncio.create_task(_run_translation(
        task_id, epub_path, output_path, translator_config, config, engine,
        ollama_url, api_key, api_base,
    ))

    return {"task_id": task_id}


@router.get("/translate/{task_id}/progress")
async def get_progress(task_id: str):
    """SSE 流：推送翻译进度事件。"""
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator() -> AsyncIterator[dict]:
        sent = 0
        while True:
            task = _tasks.get(task_id, {})
            events = task.get("events", [])
            while sent < len(events):
                yield {"data": json.dumps(events[sent], ensure_ascii=False)}
                sent += 1
            if task.get("status") in ("done", "error"):
                break
            await asyncio.sleep(0.3)

    return EventSourceResponse(event_generator())


@router.get("/translate/{task_id}/download")
async def download_result(task_id: str):
    """下载翻译完成的 EPUB 文件。"""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "done":
        raise HTTPException(status_code=400, detail="Translation not completed yet")
    output_path = Path(task["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(path=output_path, filename=task["filename"], media_type="application/epub+zip")


@router.get("/translate/{task_id}/status")
async def get_status(task_id: str) -> dict:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "status": task["status"]}


@router.get("/models")
async def list_models(ollama_url: str = "http://localhost:11434") -> dict:
    t = OllamaTranslator(TranslatorConfig(), base_url=ollama_url)
    models = await t.list_models()
    return {"models": models}


async def _run_translation(
    task_id: str,
    epub_path: Path,
    output_path: Path,
    translator_config: TranslatorConfig,
    config: TranslateConfig,
    engine: str,
    ollama_url: str,
    api_key: str,
    api_base: str,
) -> None:
    _tasks[task_id]["status"] = "running"

    def on_progress(event: ProgressEvent) -> None:
        _tasks[task_id]["events"].append({
            "chapter_index": event.chapter_index,
            "chapter_total": event.chapter_total,
            "chapter_title": event.chapter_title,
            "block_index": event.block_index,
            "block_total": event.block_total,
            "status": event.status,
            "message": event.message,
        })

    try:
        if engine == "ollama":
            translator = OllamaTranslator(translator_config, base_url=ollama_url)
        else:
            translator = OpenAICompatTranslator(translator_config, api_key=api_key, base_url=api_base)

        async with translator:
            pipeline = TranslationPipeline(
                epub_path=epub_path,
                output_path=output_path,
                translator=translator,
                config=config,
                on_progress=on_progress,
            )
            await pipeline.run()

        _tasks[task_id]["status"] = "done"
    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = str(e)
