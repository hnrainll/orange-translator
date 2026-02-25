"""从 XHTML 章节中提取可翻译的文本块。

策略：
- 以块级元素（p, h1-h6, li, td, th, blockquote, figcaption）为翻译单元
- 内联标签（em, strong, a, span 等）保留在文本中，翻译时整体传入 LLM
- 跳过 pre/code 块（代码不翻译）
- 跳过已存在 class="ot-translation" 的节点（续翻时避免重复）
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
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


# 发送给 LLM 时去除属性的内联标签集合
_INLINE_TAGS_STRIP_ATTRS = frozenset({
    "em", "strong", "b", "i", "u", "span", "a", "small", "big",
    "sub", "sup", "abbr", "cite", "q", "s", "del", "ins",
})

# 匹配带属性的开标签或自闭合标签
_TAG_WITH_ATTRS_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)(\s[^>]*)>")


def strip_inline_attrs(html: str) -> tuple[str, list[tuple[str, str]]]:
    """剥离内联标签上的属性，减少送入 LLM 的 token 数。

    Returns:
        (stripped_html, originals)
        originals: list of (original_tag, stripped_tag) pairs，供 restore 使用
    """
    originals: list[tuple[str, str]] = []

    def replacer(m: re.Match) -> str:
        tag_name = m.group(1).lower()
        if tag_name not in _INLINE_TAGS_STRIP_ATTRS:
            return m.group(0)
        full_tag = m.group(0)
        stripped = f"<{tag_name}>"
        if full_tag == stripped:
            return full_tag
        originals.append((full_tag, stripped))
        return stripped

    result = _TAG_WITH_ATTRS_RE.sub(replacer, html)
    return result, originals


def restore_inline_attrs(translated: str, originals: list[tuple[str, str]]) -> str:
    """将剥离的属性按顺序还原到翻译结果中。

    策略：对每种标签名维护一个 FIFO 队列，翻译结果中遇到同名无属性标签时取队头还原。
    LLM 可能省略某些标签，剩余队列项直接丢弃（不影响正确性）。
    """
    if not originals:
        return translated

    # 按标签名分组，保持原顺序
    queue: dict[str, deque[str]] = defaultdict(deque)
    for orig, stripped in originals:
        m = re.match(r"<([a-zA-Z]+)", stripped)
        if m:
            queue[m.group(1).lower()].append(orig)

    def replacer(m: re.Match) -> str:
        tag_name = m.group(1).lower()
        if tag_name in queue and queue[tag_name]:
            return queue[tag_name].popleft()
        return m.group(0)

    # 匹配无属性的开标签（含自闭合）
    return re.sub(r"<([a-zA-Z][a-zA-Z0-9]*)\s*/?>", replacer, translated)


def _has_ancestor(tag: Tag, tag_names: frozenset[str]) -> bool:
    """检查 tag 是否有指定名称的祖先节点。"""
    for parent in tag.parents:
        if isinstance(parent, NavigableString):
            continue
        if getattr(parent, "name", None) in tag_names:
            return True
    return False
