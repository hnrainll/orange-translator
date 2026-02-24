"""翻译引擎抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class TranslationMode(str, Enum):
    SPEED = "speed"
    QUALITY = "quality"


@dataclass
class TranslatorConfig:
    src_lang: str = "en"
    tgt_lang: str = "zh"
    mode: TranslationMode = TranslationMode.SPEED
    model: str = ""             # 空字符串表示使用引擎默认值
    temperature: float = -1.0   # -1 表示使用模式默认值
    extra: dict = field(default_factory=dict)

    def effective_temperature(self) -> float:
        if self.temperature >= 0:
            return self.temperature
        return 0.3 if self.mode == TranslationMode.SPEED else 0.7


class TranslatorBase(ABC):
    """翻译引擎基类，子类实现 translate() 方法。"""

    def __init__(self, config: TranslatorConfig) -> None:
        self.config = config

    @abstractmethod
    async def translate(self, text: str) -> str:
        """翻译一段文本（可包含内联 HTML 标签）。

        Args:
            text: 原始文本或含内联标签的 HTML 片段

        Returns:
            译文（保留内联 HTML 结构）
        """

    @abstractmethod
    async def translate_batch(self, texts: list[str]) -> list[str]:
        """批量翻译，默认实现逐条调用 translate()。"""

    async def health_check(self) -> bool:
        """检查服务是否可用，默认返回 True。"""
        return True

    def _build_system_prompt(self) -> str:
        src = self.config.src_lang
        tgt = self.config.tgt_lang
        mode = self.config.mode

        if mode == TranslationMode.SPEED:
            return (
                f"You are a professional translator. "
                f"Translate the following text from {src} to {tgt}. "
                f"Preserve any HTML inline tags (like <em>, <strong>, <a>, etc.) exactly as-is. "
                f"Output only the translated text, no explanations."
            )
        else:
            return (
                f"You are a professional literary translator specializing in {src} to {tgt} translation. "
                f"Produce a natural, fluent translation that reads well in {tgt}. "
                f"Preserve any HTML inline tags (like <em>, <strong>, <a>, etc.) exactly as-is. "
                f"Maintain the author's tone and style. "
                f"Output only the translated text, no explanations or notes."
            )
