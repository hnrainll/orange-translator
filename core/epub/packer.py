"""EPUB 打包：将翻译后的章节内容重组为双语 EPUB。

双语插入格式：
    <p>Original text.</p>
    <p class="ot-translation" lang="zh">译文。</p>

同时注入翻译样式 CSS，并更新书名元数据。
"""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup, Tag

from core.epub.parser import ParsedEpub

# 注入到每个章节的翻译样式
TRANSLATION_CSS = """\
/* orange-translator bilingual styles */
.ot-translation {
    color: #2563eb;
    font-size: 0.95em;
    font-weight: normal;
    margin-top: 0.1em;
    margin-bottom: 0.6em;
    text-indent: 0;
    opacity: 0.9;
}
"""

CSS_FILENAME = "ot-translation.css"


def insert_translation(soup: BeautifulSoup, original_tag: Tag, translated_html: str, target_lang: str) -> None:
    """在 original_tag 之后插入译文节点，克隆原节点全部属性。"""
    # 克隆原节点所有属性，避免逐一枚举可能遗漏的属性
    attrs = dict(original_tag.attrs)

    # id 不复制（避免文档内重复 id）
    attrs.pop("id", None)

    # class：追加 ot-translation
    raw_class = attrs.get("class") or []
    classes = raw_class.split() if isinstance(raw_class, str) else list(raw_class)
    attrs["class"] = " ".join(classes + ["ot-translation"])

    # 语言标记
    attrs["lang"] = target_lang

    new_tag = soup.new_tag(original_tag.name, **attrs)

    # 解析译文内容并填充
    frag = BeautifulSoup(f"<div>{translated_html}</div>", "lxml")
    inner_div = frag.find("div")
    if inner_div:
        for child in inner_div.children:
            new_tag.append(child.__copy__())
    original_tag.insert_after(new_tag)


def pack(
    parsed: ParsedEpub,
    chapter_contents: dict[str, bytes],  # abs_path -> 新的 XHTML 内容
    output_path: str | Path,
    target_lang: str,
) -> None:
    """将翻译后的章节内容重新打包为 EPUB。

    Args:
        parsed: 原始 ParsedEpub 对象
        chapter_contents: 已翻译章节的新 XHTML 内容（key 为 abs_path）
        output_path: 输出 EPUB 路径
        target_lang: 目标语言代码（用于更新元数据）
    """
    output_path = Path(output_path)
    opf_dir = parsed.meta.opf_dir

    # CSS 文件在 ZIP 内的路径
    css_abs_path = _join_path(opf_dir, CSS_FILENAME) if opf_dir else CSS_FILENAME

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. mimetype 必须是第一个文件且不压缩
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
        )

        # 2. 写入所有 assets（跳过 mimetype，已处理；修改 OPF）
        chapter_paths = {ch.abs_path for ch in parsed.chapters}
        opf_path: str | None = None

        for path, content in parsed.assets.items():
            if path == "mimetype":
                continue
            # 找到 OPF 文件并修改
            if path.endswith(".opf"):
                opf_path = path
                content = _patch_opf(content, parsed.meta.title, target_lang, opf_dir, CSS_FILENAME)
            zf.writestr(path, content)

        # 3. 写入翻译 CSS
        zf.writestr(css_abs_path, TRANSLATION_CSS.encode())

        # 4. 写入章节（使用新内容或原内容）
        for chapter in parsed.chapters:
            new_content = chapter_contents.get(chapter.abs_path, chapter.content)
            zf.writestr(chapter.abs_path, new_content)

    return output_path


def _patch_opf(
    opf_content: bytes, original_title: str, target_lang: str, opf_dir: str, css_filename: str
) -> bytes:
    """修改 OPF：更新书名、添加 CSS manifest 项。"""
    from lxml import etree

    root = etree.fromstring(opf_content)
    opf_ns = "http://www.idpf.org/2007/opf"
    dc_ns = "http://purl.org/dc/elements/1.1/"

    # 更新书名
    title_el = root.find(f".//{{{dc_ns}}}title")
    if title_el is not None and title_el.text:
        if "[双语]" not in title_el.text and "[Bilingual]" not in title_el.text:
            title_el.text = f"{title_el.text} [双语]"

    # 在 manifest 中添加 CSS 项
    manifest_el = root.find(f".//{{{opf_ns}}}manifest")
    if manifest_el is not None:
        # 检查是否已存在
        existing = manifest_el.find(f".//{{{opf_ns}}}item[@id='ot-translation-css']")
        if existing is None:
            css_item = etree.SubElement(manifest_el, f"{{{opf_ns}}}item")
            css_item.set("id", "ot-translation-css")
            css_item.set("href", css_filename)
            css_item.set("media-type", "text/css")

    return etree.tostring(root, xml_declaration=True, encoding="utf-8", pretty_print=True)


def inject_css_link(soup: BeautifulSoup, css_path_relative: str) -> None:
    """在 XHTML head 中注入 CSS link 标签。"""
    head = soup.find("head")
    if head is None:
        return
    # 检查是否已注入
    for link in head.find_all("link", rel="stylesheet"):
        if css_path_relative in link.get("href", ""):
            return
    link_tag = soup.new_tag("link")
    link_tag["rel"] = "stylesheet"
    link_tag["type"] = "text/css"
    link_tag["href"] = css_path_relative
    head.append(link_tag)


def _join_path(base_dir: str, filename: str) -> str:
    if not base_dir:
        return filename
    return str(PurePosixPath(base_dir) / filename)
