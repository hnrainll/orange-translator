"""从 XHTML 章节中提取可翻译的文本块。

策略：
- 以块级元素（p, h1-h6, li, td, th, blockquote, figcaption）为翻译单元
- 内联标签（em, strong, a, span 等）保留在文本中，翻译时整体传入 LLM
- 跳过 pre/code 块（代码不翻译）
- 跳过已存在 class="ot-translation" 的节点（续翻时避免重复）
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

# 作为翻译单元的块级标签
BLOCK_TAGS = frozenset(
    ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote", "figcaption", "dt", "dd"]
)

# 不翻译的块级标签
SKIP_TAGS = frozenset(["pre", "code", "script", "style"])


@dataclass
class TextBlock:
    """一个可翻译的文本块。"""
    tag: Tag                # BeautifulSoup Tag 对象（直接引用，可修改）
    inner_html: str         # 原始内部 HTML（含内联标签）
    text_content: str       # 纯文本内容（用于判断是否需要翻译）


def extract_blocks(html_content: bytes | str) -> tuple[BeautifulSoup, list[TextBlock]]:
    """解析 HTML，提取所有可翻译文本块。

    Returns:
        (soup, blocks)
        soup: 可直接修改并序列化回 HTML 的 BeautifulSoup 对象
        blocks: 按文档顺序排列的文本块列表
    """
    soup = BeautifulSoup(html_content, "lxml-xml")
    blocks: list[TextBlock] = []

    for tag in soup.find_all(BLOCK_TAGS):
        # 跳过已翻译节点
        if "ot-translation" in tag.get("class", []):
            continue

        # 跳过在 pre/code 内的标签
        if _has_ancestor(tag, SKIP_TAGS):
            continue

        # 跳过嵌套块（只取最外层，避免重复翻译）
        if _has_ancestor(tag, BLOCK_TAGS):
            continue

        inner_html = tag.decode_contents()
        text = tag.get_text(separator=" ", strip=True)

        # 跳过纯空白或只有标点的块
        if not text.strip():
            continue

        blocks.append(TextBlock(tag=tag, inner_html=inner_html, text_content=text))

    return soup, blocks


def _has_ancestor(tag: Tag, tag_names: frozenset[str]) -> bool:
    """检查 tag 是否有指定名称的祖先节点。"""
    for parent in tag.parents:
        if isinstance(parent, NavigableString):
            continue
        if getattr(parent, "name", None) in tag_names:
            return True
    return False
