"""全局配置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = ""


@dataclass
class OpenAIConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@dataclass
class TranslateConfig:
    src_lang: str = "en"
    tgt_lang: str = "zh"
    engine: str = "ollama"          # "ollama" | "openai"
    chapter_concurrency: int = 1
    batch_size: int = 10

    # 引擎配置
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)


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
