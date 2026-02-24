"""OpenAI 兼容接口翻译引擎。

兼容任何支持 OpenAI Chat Completions API 的服务：
- OpenAI (https://api.openai.com)
- DeepSeek (https://api.deepseek.com)
- 硅基流动 (https://api.siliconflow.cn)
- 本地 vLLM / LM Studio 等
"""

from __future__ import annotations

import asyncio

import httpx

from core.translator.base import TranslatorBase, TranslatorConfig

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAICompatTranslator(TranslatorBase):
    def __init__(
        self,
        config: TranslatorConfig,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        super().__init__(config)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def _effective_model(self) -> str:
        return self.config.model or DEFAULT_MODEL

    async def translate(self, text: str) -> str:
        payload = {
            "model": self._effective_model(),
            "messages": [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": text},
            ],
            "temperature": self.config.temperature,
        }
        resp = await self._client.post(f"{self.base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    async def translate_batch(self, texts: list[str]) -> list[str]:
        tasks = [self.translate(t) for t in texts]
        return list(await asyncio.gather(*tasks))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()
