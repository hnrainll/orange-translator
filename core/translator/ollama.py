"""Ollama 翻译引擎实现。

默认模型：translategemma:4b
API：POST http://localhost:11434/api/chat
"""

from __future__ import annotations

import asyncio
import json

import httpx

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
        payload = {
            "model": self._effective_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": True,
            "options": {"temperature": self.config.temperature},
        }
        parts: list[str] = []
        async with self._client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if content := data.get("message", {}).get("content"):
                    parts.append(content)
                if data.get("done"):
                    break
        return "".join(parts).strip()

    async def _do_translate(self, text: str) -> str:
        return await self._stream_chat(self._build_system_prompt(), text)

    async def translate_batch(self, texts: list[str]) -> list[str]:
        """将多段文本合并成一次请求批量翻译，解析失败时逐段回退。"""
        async with self._sem:
            if len(texts) == 1:
                return [await self._do_translate(texts[0])]
            try:
                user_content = "\n\n".join(f"[{i + 1}]\n{t}" for i, t in enumerate(texts))
                raw = await self._stream_chat(self._build_batch_system_prompt(), user_content)
                return self._parse_batch_response(raw, len(texts))
            except Exception:
                # 解析失败或请求失败，逐段翻译（复用已持有的信号量）
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
