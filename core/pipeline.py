"""翻译流水线：调度章节翻译、进度持久化、双语重组。

流程：
  1. 解析 EPUB
  2. 加载进度文件（如存在，跳过已完成章节）
  3. 逐章提取文本块 → 分批翻译 → 插入译文节点
  4. 将修改后的章节 XHTML 传给 packer 重新打包
  5. 翻译完成后删除进度文件
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from bs4 import BeautifulSoup

from core.config import TranslateConfig
from core.epub.extractor import extract_blocks
from core.epub.packer import inject_css_link, insert_translation, pack
from core.epub.parser import Chapter, ParsedEpub, parse
from core.translator.base import TranslationMode, TranslatorBase, TranslatorConfig


@dataclass
class ProgressEvent:
    """进度事件，供 CLI / Web UI 消费。"""
    chapter_index: int
    chapter_total: int
    chapter_title: str
    block_index: int
    block_total: int
    status: str  # "translating" | "done" | "skipped" | "error"
    message: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


class TranslationPipeline:
    def __init__(
        self,
        epub_path: Path,
        output_path: Path,
        translator: TranslatorBase,
        config: TranslateConfig,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.epub_path = epub_path
        self.output_path = output_path
        self.translator = translator
        self.config = config
        self.on_progress = on_progress or (lambda e: None)
        self.progress_file = epub_path.with_suffix(".ot-progress.json")

    async def run(self) -> Path:
        """执行完整翻译流程，返回输出文件路径。"""
        # 1. 解析 EPUB
        parsed = parse(self.epub_path)

        # 2. 加载已完成章节（续翻支持）
        completed_entries, completed_paths = self._load_progress()

        # 3. 翻译所有章节
        chapter_contents: dict[str, bytes] = {}
        total = len(parsed.chapters)
        entries_lock = asyncio.Lock()

        semaphore = asyncio.Semaphore(self.config.effective_chapter_concurrency())

        async def translate_chapter(idx: int, chapter: Chapter) -> None:
            async with semaphore:
                if chapter.abs_path in completed_paths:
                    self.on_progress(ProgressEvent(
                        chapter_index=idx, chapter_total=total,
                        chapter_title=chapter.href,
                        block_index=0, block_total=0,
                        status="skipped",
                    ))
                    return

                start = time.monotonic()
                try:
                    new_content = await self._translate_chapter(idx, total, chapter)
                    duration = round(time.monotonic() - start, 1)
                    chapter_contents[chapter.abs_path] = new_content
                    async with entries_lock:
                        completed_entries.append({"path": chapter.abs_path, "duration_sec": duration})
                        completed_paths.add(chapter.abs_path)
                        self._save_progress(completed_entries)
                except Exception as e:
                    import traceback
                    self.on_progress(ProgressEvent(
                        chapter_index=idx, chapter_total=total,
                        chapter_title=chapter.href,
                        block_index=0, block_total=0,
                        status="error", message=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                    ))
                    # 不再 raise，让其他章节继续执行

        tasks = [translate_chapter(i, ch) for i, ch in enumerate(parsed.chapters)]
        await asyncio.gather(*tasks)

        # 4. 打包（即使部分章节失败，已翻译的章节仍正常输出）
        pack(parsed, chapter_contents, self.output_path, self.config.tgt_lang)

        # 5. 清理进度文件
        if self.progress_file.exists():
            self.progress_file.unlink()

        return self.output_path

    async def _translate_chapter(self, idx: int, total: int, chapter: Chapter) -> bytes:
        """翻译单章，返回修改后的 XHTML bytes。"""
        soup, blocks = extract_blocks(chapter.content)
        n = len(blocks)

        if n == 0:
            return chapter.content

        # 注入 CSS link（计算相对路径）
        css_rel_path = _relative_css_path(chapter.abs_path)
        inject_css_link(soup, css_rel_path)

        # 按批次翻译
        batch_size = self.config.effective_batch_size()
        translated_count = 0

        for batch_start in range(0, n, batch_size):
            batch = blocks[batch_start: batch_start + batch_size]
            texts = [b.inner_html for b in batch]

            self.on_progress(ProgressEvent(
                chapter_index=idx, chapter_total=total,
                chapter_title=chapter.href,
                block_index=translated_count, block_total=n,
                status="translating",
            ))

            translations = await self.translator.translate_batch(texts)

            for block, translation in zip(batch, translations):
                insert_translation(soup, block.tag, translation, self.config.tgt_lang)
                translated_count += 1

        self.on_progress(ProgressEvent(
            chapter_index=idx, chapter_total=total,
            chapter_title=chapter.href,
            block_index=n, block_total=n,
            status="done",
        ))

        return str(soup).encode("utf-8")

    def _load_progress(self) -> tuple[list[dict], set[str]]:
        """返回 (有序条目列表, 路径集合)。"""
        if not self.progress_file.exists():
            return [], set()
        try:
            data = json.loads(self.progress_file.read_text())
            entries = data.get("completed", [])
            paths = {e["path"] for e in entries}
            return entries, paths
        except Exception:
            return [], set()

    def _save_progress(self, entries: list[dict]) -> None:
        self.progress_file.write_text(
            json.dumps({"completed": entries}, ensure_ascii=False, indent=2)
        )


def _relative_css_path(chapter_abs_path: str) -> str:
    """计算从章节到 ot-translation.css 的相对路径。"""
    chapter_dir = PurePosixPath(chapter_abs_path).parent
    # CSS 文件和 OPF 同级，即 opf_dir/ot-translation.css
    # 简单策略：在章节同目录放 CSS（packer 负责实际写入位置）
    depth = len(chapter_dir.parts)
    if depth <= 1:
        return "ot-translation.css"
    return "../" * (depth - 1) + "ot-translation.css"
