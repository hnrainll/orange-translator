"""Ollama 翻译引擎实现。

默认模型：translategemma:4b
API：POST http://localhost:11434/api/chat
"""

from __future__ import annotations

import asyncio
import json

import httpx

from core.translator.base import TranslationMode, TranslatorBase, TranslatorConfig

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
        self._client = httpx.AsyncClient(timeout=300.0)
        self._sem = asyncio.Semaphore(max_concurrent)

    def _effective_model(self) -> str:
        return self.config.model or DEFAULT_MODEL

    async def translate(self, text: str) -> str:
        async with self._sem:
            return await self._do_translate(text)

    async def _do_translate(self, text: str) -> str:
        payload = {
            "model": self._effective_model(),
            "messages": [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "options": {
                "temperature": self.config.effective_temperature(),
            },
        }
        resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()

    async def translate_batch(self, texts: list[str]) -> list[str]:
        """并发翻译（受 semaphore 限制），Quality 模式串行保持上下文连贯。"""
        if self.config.mode == TranslationMode.SPEED:
            tasks = [self.translate(t) for t in texts]
            return list(await asyncio.gather(*tasks))
        else:
            results = []
            for text in texts:
                results.append(await self.translate(text))
            return results

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """列出本地可用模型。"""
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
