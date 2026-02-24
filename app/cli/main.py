"""orange-translator CLI 入口。

命令：
  ot translate <epub>   翻译 EPUB 文件
  ot models             列出本地 Ollama 可用模型
  ot languages          列出支持的语言代码
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from core.config import LANGUAGE_MAP, OllamaConfig, OpenAIConfig, TranslateConfig
from core.pipeline import ProgressEvent, TranslationPipeline
from core.translator.base import TranslationMode, TranslatorConfig
from core.translator.ollama import OllamaTranslator
from core.translator.openai_compat import OpenAICompatTranslator

app = typer.Typer(
    name="ot",
    help="orange-translator: EPUB 双语翻译工具",
    add_completion=False,
)
console = Console()


@app.command()
def translate(
    epub: Path = typer.Argument(..., help="输入 EPUB 文件路径", exists=True, dir_okay=False),
    src: str = typer.Option("en", "--from", "-f", help="源语言代码（如 en, ja, fr）"),
    tgt: str = typer.Option("zh", "--to", "-t", help="目标语言代码（如 zh, en, de）"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出路径（默认：原文件名_bilingual.epub）"),
    mode: TranslationMode = typer.Option(TranslationMode.SPEED, "--mode", "-m", help="翻译模式：speed / quality"),
    model: str = typer.Option("", "--model", help="指定模型（如 qwen2.5:72b），空表示按模式自动选择"),
    engine: str = typer.Option("ollama", "--engine", "-e", help="翻译引擎：ollama / openai"),
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url", help="Ollama 服务地址"),
    api_key: str = typer.Option("", "--api-key", help="OpenAI 兼容引擎的 API Key", envvar="OT_API_KEY"),
    api_base: str = typer.Option("https://api.openai.com/v1", "--api-base", help="OpenAI 兼容引擎的 Base URL"),
) -> None:
    """翻译 EPUB 文件，生成双语版本。"""

    # 确定输出路径
    if output is None:
        output = epub.parent / f"{epub.stem}_bilingual.epub"

    config = TranslateConfig(
        src_lang=src,
        tgt_lang=tgt,
        mode=mode,
        engine=engine,
        ollama=OllamaConfig(base_url=ollama_url, model=model),
        openai=OpenAIConfig(api_key=api_key, base_url=api_base, model=model or "gpt-4o-mini"),
    )

    # 构建翻译器
    translator_config = TranslatorConfig(
        src_lang=src,
        tgt_lang=tgt,
        mode=mode,
        model=model,
    )

    console.print(f"\n[bold]orange-translator[/bold]")
    console.print(f"  输入：{epub}")
    console.print(f"  输出：{output}")
    console.print(f"  语言：{src} → {tgt}")
    console.print(f"  模式：{mode.value}  引擎：{engine}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        chapter_task = progress.add_task("章节进度", total=None)
        block_task = progress.add_task("  段落翻译", total=None, visible=False)

        def on_progress(event: ProgressEvent) -> None:
            # 更新章节进度
            progress.update(
                chapter_task,
                total=event.chapter_total,
                completed=event.chapter_index + (1 if event.status in ("done", "skipped") else 0),
                description=f"章节 [{event.chapter_index + 1}/{event.chapter_total}] {_short_name(event.chapter_title)}",
            )
            # 更新段落进度
            if event.block_total > 0:
                progress.update(
                    block_task,
                    visible=True,
                    total=event.block_total,
                    completed=event.block_index,
                    description=f"  段落翻译 {event.block_index}/{event.block_total}",
                )
            if event.status in ("done", "skipped"):
                progress.update(block_task, visible=False)
            if event.status == "error":
                console.print(f"[red]错误[/red] {event.chapter_title}: {event.message}")

        async def run() -> None:
            if engine == "ollama":
                translator = OllamaTranslator(translator_config, base_url=ollama_url)
                ok = await translator.health_check()
                if not ok:
                    console.print(f"[red]无法连接 Ollama 服务：{ollama_url}[/red]")
                    console.print("请确认 Ollama 已启动：[dim]ollama serve[/dim]")
                    raise typer.Exit(1)
            else:
                if not api_key:
                    console.print("[red]使用 openai 引擎需要提供 --api-key 或设置环境变量 OT_API_KEY[/red]")
                    raise typer.Exit(1)
                translator = OpenAICompatTranslator(translator_config, api_key=api_key, base_url=api_base)

            async with translator:
                pipeline = TranslationPipeline(
                    epub_path=epub,
                    output_path=output,
                    translator=translator,
                    config=config,
                    on_progress=on_progress,
                )
                await pipeline.run()

        try:
            asyncio.run(run())
            console.print(f"\n[green]✓ 翻译完成[/green] → {output}")
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"\n[red]翻译失败：{e}[/red]")
            raise typer.Exit(1)


@app.command()
def models(
    ollama_url: str = typer.Option("http://localhost:11434", "--ollama-url", help="Ollama 服务地址"),
) -> None:
    """列出本地 Ollama 可用模型。"""
    from core.translator.ollama import OllamaTranslator

    async def _list() -> list[str]:
        cfg = TranslatorConfig()
        t = OllamaTranslator(cfg, base_url=ollama_url)
        return await t.list_models()

    result = asyncio.run(_list())
    if not result:
        console.print(f"[yellow]未找到模型，或无法连接 Ollama（{ollama_url}）[/yellow]")
        return

    table = Table(title="本地 Ollama 模型", show_header=True)
    table.add_column("模型名称", style="cyan")
    for name in result:
        table.add_row(name)
    console.print(table)


@app.command()
def languages() -> None:
    """列出常用语言代码。"""
    table = Table(title="常用语言代码", show_header=True)
    table.add_column("代码", style="cyan", width=10)
    table.add_column("语言", style="white")
    for code, name in LANGUAGE_MAP.items():
        table.add_row(code, name)
    console.print(table)


def _short_name(path: str) -> str:
    """取文件名部分，限制长度。"""
    name = Path(path).name
    return name[:40] + "…" if len(name) > 40 else name
