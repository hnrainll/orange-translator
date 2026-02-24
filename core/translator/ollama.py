"""Ollama 翻译引擎实现。

默认模型：translategemma:4b
API：POST http://localhost:11434/api/chat
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
from loguru import logger

from core.translator.base import TranslatorBase, TranslatorConfig

DEFAULT_MODEL = "translategemma:4b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MAX_CONCURRENT = 1  # Ollama 本地单线程推理，串行请求最稳定


class OllamaTranslator(TranslatorBase):
    def __init__(
        self,
        config: TranslatorConfig,
        base_url: str = DEFAULT_BASE_URL,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        super().__init__(config)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
        )
        self._sem = asyncio.Semaphore(max_concurrent)

    def _effective_model(self) -> str:
        return self.config.model or DEFAULT_MODEL

    async def translate(self, text: str) -> str:
        async with self._sem:
            return await self._do_translate(text)

    async def _stream_chat(self, system_prompt: str, user_content: str) -> str:
        """向 Ollama 发送一次流式请求，返回完整响应文本。"""
        model = self._effective_model()
        input_chars = len(user_content)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": True,
            "options": {"temperature": self.config.temperature},
        }
        parts: list[str] = []
        token_count = 0
        t_start = time.monotonic()
        t_first_token: float | None = None

        logger.debug("request  model={} input={}chars", model, input_chars)
        async with self._client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if content := data.get("message", {}).get("content"):
                    if t_first_token is None:
                        t_first_token = time.monotonic()
                        logger.debug("  TTFT={:.2f}s", t_first_token - t_start)
                    parts.append(content)
                    token_count += 1
                if data.get("done"):
                    break

        t_total = time.monotonic() - t_start
        output_chars = sum(len(p) for p in parts)
        t_gen = t_total - (t_first_token - t_start if t_first_token else t_total)
        tok_per_sec = token_count / t_gen if t_gen > 0 else 0
        logger.info(
            "done  model={} input={}chars output={}chars tokens={} TTFT={:.2f}s gen={:.2f}s speed={:.1f}tok/s total={:.2f}s",
            model, input_chars, output_chars, token_count,
            (t_first_token - t_start) if t_first_token else 0,
            t_gen, tok_per_sec, t_total,
        )
        return "".join(parts).strip()

    async def _do_translate(self, text: str) -> str:
        return await self._stream_chat(self._build_system_prompt(), text)

    async def translate_batch(self, texts: list[str]) -> list[str]:
        """将多段文本合并成一次请求批量翻译，解析失败时逐段回退。"""
        async with self._sem:
            if len(texts) == 1:
                return [await self._do_translate(texts[0])]
            total_chars = sum(len(t) for t in texts)
            logger.debug("batch  segs={} total={}chars", len(texts), total_chars)
            try:
                user_content = "\n\n".join(f"[{i + 1}]\n{t}" for i, t in enumerate(texts))
                raw = await self._stream_chat(self._build_batch_system_prompt(), user_content)
                results = self._parse_batch_response(raw, len(texts))
                logger.debug("batch parsed ok  segs={}", len(results))
                return results
            except Exception as e:
                logger.warning("batch parse failed ({}), falling back to per-segment", e)
                results = []
                for t in texts:
                    results.append(await self._do_translate(t))
                return results

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()
