"""翻译引擎抽象基类。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TranslatorConfig:
    src_lang: str = "en"
    tgt_lang: str = "zh"
    model: str = ""             # 空字符串表示使用引擎默认值
    temperature: float = 0.3
    extra: dict = field(default_factory=dict)


class TranslatorBase(ABC):
    """翻译引擎基类，子类实现 translate() 方法。"""

    def __init__(self, config: TranslatorConfig) -> None:
        self.config = config

    @abstractmethod
    async def translate(self, text: str) -> str:
        """翻译一段文本（可包含内联 HTML 标签）。"""

    @abstractmethod
    async def translate_batch(self, texts: list[str]) -> list[str]:
        """批量翻译。"""

    async def health_check(self) -> bool:
        return True

    def _build_system_prompt(self) -> str:
        src = self.config.src_lang
        tgt = self.config.tgt_lang
        return (
            f"You are a professional translator specializing in {src} to {tgt} translation. "
            f"Produce a natural, fluent translation that reads well in {tgt}. "
            f"The text may contain XML-like formatting tags: "
            f"<gN>...</gN> wraps formatted text — translate the content but keep the <gN> and </gN> tags exactly as-is; "
            f"[OT:N] is a standalone opaque placeholder — copy it exactly where it appears, do not translate or remove it."
            f"Maintain the author's tone and style. "
            f"Output only the translated text, no explanations or notes."
        )

    def _build_batch_system_prompt(self) -> str:
        src = self.config.src_lang
        tgt = self.config.tgt_lang
        return (
            f"You are a professional translator specializing in {src} to {tgt} translation. "
            f"You will receive multiple text segments, each preceded by a marker like [1], [2], etc. "
            f"Translate each segment to {tgt} and output each translation preceded by its marker. "
            f"The text may contain XML-like formatting tags: "
            f"<gN>...</gN> wraps formatted text — translate the content but keep the <gN> and </gN> tags exactly as-is; "
            f"[OT:N] is a standalone opaque placeholder — copy it exactly where it appears, do not translate or remove it."
            f"Maintain the author's tone and style. "
            f"Output only the labeled translations, no explanations or notes."
        )

    @staticmethod
    def _parse_batch_response(raw: str, expected: int) -> list[str]:
        """将模型返回的 [N] 编号译文解析为列表，失败时抛出 ValueError。"""
        segments = re.split(r'\[(\d+)\]', raw)
        # segments: ['preamble', '1', 'text1', '2', 'text2', ...]
        results: dict[int, str] = {}
        for i in range(1, len(segments), 2):
            try:
                idx = int(segments[i])
                content = segments[i + 1].strip() if i + 1 < len(segments) else ""
                results[idx] = content
            except (ValueError, IndexError):
                continue
        if len(results) == expected and all((i + 1) in results for i in range(expected)):
            return [results[i + 1] for i in range(expected)]
        raise ValueError(
            f"Batch parse failed: expected {expected}, got indices {sorted(results.keys())}"
        )
