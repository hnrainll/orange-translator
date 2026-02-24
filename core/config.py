"""全局配置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.translator.base import TranslationMode


@dataclass
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = ""  # 空表示按 mode 自动选择


@dataclass
class OpenAIConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@dataclass
class TranslateConfig:
    src_lang: str = "en"
    tgt_lang: str = "zh"
    mode: TranslationMode = TranslationMode.SPEED
    engine: str = "ollama"          # "ollama" | "openai"

    # 并发控制
    chapter_concurrency: int = -1   # -1 表示按 mode 自动选择
    batch_size: int = -1            # -1 表示按 mode 自动选择

    # 引擎配置
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)

    def effective_chapter_concurrency(self) -> int:
        if self.chapter_concurrency > 0:
            return self.chapter_concurrency
        return 4 if self.mode == TranslationMode.SPEED else 1

    def effective_batch_size(self) -> int:
        if self.batch_size > 0:
            return self.batch_size
        return 10 if self.mode == TranslationMode.SPEED else 3


# 常用语言对照表（用于 CLI 提示）
LANGUAGE_MAP: dict[str, str] = {
    "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
}
