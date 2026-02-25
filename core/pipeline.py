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
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from bs4 import BeautifulSoup
from loguru import logger

from core.config import TranslateConfig
from core.epub.extractor import extract_blocks, restore_inline_attrs, strip_inline_attrs
from core.epub.packer import inject_css_link, insert_translation, pack
from core.epub.parser import Chapter, ParsedEpub, parse
from core.translator.base import TranslatorBase, TranslatorConfig


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
        self.cache_dir = epub_path.with_suffix(".ot-cache")
        self.progress_file = self.cache_dir / "progress.json"

    async def run(self) -> Path:
        """执行完整翻译流程，返回输出文件路径。"""
        log_fmt = "{time:HH:mm:ss.SSS} | {level:<7} | {message}"

        # 日志 1：随缓存目录存放，成功后随缓存一起删除
        self.cache_dir.mkdir(exist_ok=True)
        cache_log_id = logger.add(
            self.cache_dir / "translate.log",
            level="DEBUG", encoding="utf-8", format=log_fmt,
        )

        # 日志 2：持久化到 log/ 目录，自动轮转，永久保留
        log_dir = Path("log")
        log_dir.mkdir(exist_ok=True)
        persist_log_id = logger.add(
            log_dir / "ot-translate.log",
            level="DEBUG", encoding="utf-8", format=log_fmt,
            rotation="10 MB", retention=10,
        )

        logger.info("=== 开始翻译 {} ===", self.epub_path.name)
        logger.info(
            "config  engine={} model={} concurrency={} batch_size={} batch_char_limit={}",
            "ollama", getattr(self.config, "model", "default"),
            self.config.chapter_concurrency, self.config.batch_size, self.config.batch_char_limit,
        )

        # 1. 解析 EPUB
        parsed = parse(self.epub_path)

        # 2. 加载已完成章节（续翻支持）
        completed_entries, completed_paths = self._load_progress()

        # 3. 从磁盘缓存恢复已翻译章节内容
        chapter_contents: dict[str, bytes] = {}
        for entry in completed_entries:
            cache_file = self._cache_path(entry["path"])
            if cache_file.exists():
                chapter_contents[entry["path"]] = cache_file.read_bytes()

        total = len(parsed.chapters)
        entries_lock = asyncio.Lock()
        error_count = 0
        error_count_lock = asyncio.Lock()
        session_start = time.monotonic()

        semaphore = asyncio.Semaphore(self.config.chapter_concurrency)

        async def translate_chapter(idx: int, chapter: Chapter) -> None:
            async with semaphore:
                if chapter.abs_path in completed_paths:
                    logger.info("skip   [{}/{}] {}", idx + 1, total, chapter.href)
                    self.on_progress(ProgressEvent(
                        chapter_index=idx, chapter_total=total,
                        chapter_title=chapter.href,
                        block_index=0, block_total=0,
                        status="skipped",
                    ))
                    return

                logger.info("start  [{}/{}] {}", idx + 1, total, chapter.href)
                start = time.monotonic()
                try:
                    new_content = await self._translate_chapter(idx, total, chapter)
                    duration = round(time.monotonic() - start, 1)
                    logger.info("done   [{}/{}] {}  {:.1f}s", idx + 1, total, chapter.href, duration)
                    async with entries_lock:
                        self.cache_dir.mkdir(exist_ok=True)
                        self._cache_path(chapter.abs_path).write_bytes(new_content)
                        chapter_contents[chapter.abs_path] = new_content
                        completed_entries.append({"path": chapter.abs_path, "duration_sec": duration})
                        completed_paths.add(chapter.abs_path)
                        self._save_progress(completed_entries)
                except Exception as e:
                    import traceback
                    nonlocal error_count
                    async with error_count_lock:
                        error_count += 1
                    logger.error("error  [{}/{}] {}  {}", idx + 1, total, chapter.href, e)
                    self.on_progress(ProgressEvent(
                        chapter_index=idx, chapter_total=total,
                        chapter_title=chapter.href,
                        block_index=0, block_total=0,
                        status="error", message=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                    ))
                    # 不再 raise，让其他章节继续执行

        tasks = [translate_chapter(i, ch) for i, ch in enumerate(parsed.chapters)]
        await asyncio.gather(*tasks)

        session_elapsed = time.monotonic() - session_start
        translated_count = len(completed_entries) - len([e for e in completed_entries
                                                          if e.get("duration_sec") == 0])
        logger.info(
            "=== 会话结束  章节={}/{} 错误={} 耗时={:.1f}s ===",
            len(completed_entries), total, error_count, session_elapsed,
        )

        # 4. 打包（即使部分章节失败，已翻译的章节仍正常输出）
        pack(parsed, chapter_contents, self.output_path, self.config.tgt_lang)

        # 5. 清理缓存目录（含进度文件，仅全部成功时清理，有失败时保留供续翻）
        if error_count == 0 and self.cache_dir.exists():
            import shutil
            logger.info("=== 翻译完成，清理缓存 ===")
            logger.remove(cache_log_id)
            shutil.rmtree(self.cache_dir)
        else:
            logger.info("=== 翻译结束（errors={}），缓存日志保留于 {} ===",
                        error_count, self.cache_dir / "translate.log")
            logger.remove(cache_log_id)

        logger.remove(persist_log_id)
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

        # 预先剥离所有内联标签属性
        stripped_texts: list[str] = []
        tag_maps: list[list] = []
        for b in blocks:
            stripped, tag_map = strip_inline_attrs(b.inner_html)
            stripped_texts.append(stripped)
            tag_maps.append(tag_map)

        # 按段数 + 字符数双重限制构建批次（避免超长 prompt 导致模型推理变慢）
        batch_size = self.config.batch_size
        char_limit = self.config.batch_char_limit
        batches: list[list[int]] = []
        split_reasons: list[str] = []  # 记录每次截断的原因，便于日志分析
        cur: list[int] = []
        cur_chars = 0

        for i, text in enumerate(stripped_texts):
            chars = len(text)
            if cur:
                if len(cur) >= batch_size:
                    batches.append(cur)
                    split_reasons.append("count")
                    cur = []
                    cur_chars = 0
                elif cur_chars + chars > char_limit:
                    batches.append(cur)
                    split_reasons.append("chars")
                    cur = []
                    cur_chars = 0
            cur.append(i)
            cur_chars += chars
        if cur:
            batches.append(cur)

        batch_total = len(batches)
        total_orig_chars = sum(len(b.inner_html) for b in blocks)
        total_stripped_chars = sum(len(t) for t in stripped_texts)
        chars_saved_pct = (1 - total_stripped_chars / total_orig_chars) * 100 if total_orig_chars else 0
        chars_splits = split_reasons.count("chars")

        logger.info(
            "  chapter  segs={} batches={} chars={} stripped={} saved={:.0f}%{}",
            n, batch_total, total_orig_chars, total_stripped_chars, chars_saved_pct,
            f" char_splits={chars_splits}" if chars_splits else "",
        )

        translated_count = 0
        chapter_t_start = time.monotonic()

        for batch_num, indices in enumerate(batches, 1):
            batch_stripped = [stripped_texts[i] for i in indices]
            batch_chars_orig = sum(len(blocks[i].inner_html) for i in indices)
            batch_chars_stripped = sum(len(t) for t in batch_stripped)

            logger.debug("  batch {}/{} segs={} chars={} stripped={}",
                         batch_num, batch_total, len(indices), batch_chars_orig, batch_chars_stripped)

            self.on_progress(ProgressEvent(
                chapter_index=idx, chapter_total=total,
                chapter_title=chapter.href,
                block_index=translated_count, block_total=n,
                status="translating",
            ))

            t_batch = time.monotonic()
            translations = await self.translator.translate_batch(batch_stripped)
            logger.debug("  batch {}/{} done  {:.2f}s", batch_num, batch_total, time.monotonic() - t_batch)

            translations = [restore_inline_attrs(t, tag_maps[i]) for t, i in zip(translations, indices)]

            for i, translation in zip(indices, translations):
                insert_translation(soup, blocks[i].tag, translation, self.config.tgt_lang)
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

    def _cache_path(self, abs_path: str) -> Path:
        key = hashlib.md5(abs_path.encode()).hexdigest()
        return self.cache_dir / f"{key}.xhtml"


def _relative_css_path(chapter_abs_path: str) -> str:
    """计算从章节到 ot-translation.css 的相对路径。"""
    chapter_dir = PurePosixPath(chapter_abs_path).parent
    # CSS 文件和 OPF 同级，即 opf_dir/ot-translation.css
    # 简单策略：在章节同目录放 CSS（packer 负责实际写入位置）
    depth = len(chapter_dir.parts)
    if depth <= 1:
        return "ot-translation.css"
    return "../" * (depth - 1) + "ot-translation.css"
