"""EPUB 解析：解包、读取 spine/manifest，返回章节列表。"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


@dataclass
class ManifestItem:
    id: str
    href: str          # 相对于 OPF 文件的路径
    media_type: str


@dataclass
class Chapter:
    id: str
    href: str          # 相对于 OPF 文件的路径
    abs_path: str      # ZIP 内绝对路径
    media_type: str
    content: bytes = field(default=b"", repr=False)


@dataclass
class EpubMeta:
    title: str
    language: str
    opf_dir: str       # OPF 文件所在目录（ZIP 内），用于解析相对路径


@dataclass
class ParsedEpub:
    meta: EpubMeta
    chapters: list[Chapter]
    manifest: dict[str, ManifestItem]  # id -> item
    # 非内容资源（CSS、图片等）原样保留
    assets: dict[str, bytes]           # ZIP 内绝对路径 -> 内容


def parse(epub_path: str | Path) -> ParsedEpub:
    """解析 EPUB 文件，返回结构化数据。"""
    epub_path = Path(epub_path)
    with zipfile.ZipFile(epub_path, "r") as zf:
        # 1. 读取 container.xml 找到 OPF 路径
        container_xml = zf.read("META-INF/container.xml")
        opf_path = _find_opf_path(container_xml)

        # 2. 解析 OPF
        opf_content = zf.read(opf_path)
        opf_dir = str(PurePosixPath(opf_path).parent)
        if opf_dir == ".":
            opf_dir = ""

        meta, manifest, spine_ids = _parse_opf(opf_content, opf_dir)

        # 3. 按 spine 顺序构建章节列表，并读取内容
        chapters: list[Chapter] = []
        chapter_paths: set[str] = set()
        for item_id in spine_ids:
            item = manifest.get(item_id)
            if item is None:
                continue
            if item.media_type not in ("application/xhtml+xml", "text/html"):
                continue
            abs_path = _join_path(opf_dir, item.href)
            chapter_paths.add(abs_path)
            try:
                content = zf.read(abs_path)
            except KeyError:
                content = b""
            chapters.append(Chapter(
                id=item.id,
                href=item.href,
                abs_path=abs_path,
                media_type=item.media_type,
                content=content,
            ))

        # 4. 读取其他资源（CSS、图片等）
        assets: dict[str, bytes] = {}
        for name in zf.namelist():
            if name in chapter_paths:
                continue
            if name.startswith("META-INF/"):
                assets[name] = zf.read(name)
                continue
            # 保留所有非章节文件
            assets[name] = zf.read(name)

    return ParsedEpub(meta=meta, chapters=chapters, manifest=manifest, assets=assets)


# ── 内部工具函数 ────────────────────────────────────────────────────────────


def _find_opf_path(container_xml: bytes) -> str:
    from lxml import etree
    root = etree.fromstring(container_xml)
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = root.find(".//c:rootfile", ns)
    if rootfile is None:
        raise ValueError("container.xml 中未找到 rootfile 元素")
    return rootfile.get("full-path", "")


def _parse_opf(
    opf_content: bytes, opf_dir: str
) -> tuple[EpubMeta, dict[str, ManifestItem], list[str]]:
    from lxml import etree

    root = etree.fromstring(opf_content)
    # OPF 命名空间
    opf_ns = "http://www.idpf.org/2007/opf"
    dc_ns = "http://purl.org/dc/elements/1.1/"

    # 元数据
    title = root.findtext(f".//{{{dc_ns}}}title") or ""
    language = root.findtext(f".//{{{dc_ns}}}language") or ""
    meta = EpubMeta(title=title, language=language, opf_dir=opf_dir)

    # manifest
    manifest: dict[str, ManifestItem] = {}
    for item in root.findall(f".//{{{opf_ns}}}item"):
        item_id = item.get("id", "")
        href = item.get("href", "")
        media_type = item.get("media-type", "")
        manifest[item_id] = ManifestItem(id=item_id, href=href, media_type=media_type)

    # spine
    spine_ids: list[str] = []
    for itemref in root.findall(f".//{{{opf_ns}}}itemref"):
        idref = itemref.get("idref", "")
        if idref:
            spine_ids.append(idref)

    return meta, manifest, spine_ids


def _join_path(base_dir: str, href: str) -> str:
    """将 OPF 目录和相对 href 拼成 ZIP 内绝对路径。"""
    if not base_dir:
        return href
    return str(PurePosixPath(base_dir) / href)
