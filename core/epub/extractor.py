"""从 XHTML 章节中提取可翻译的文本块。

策略：
- 以块级元素（p, h1-h6, li, td, th, blockquote, figcaption）为翻译单元
- 内联标签用 <gN>content</gN>（透明标签）或 <xN/>（不透明标签）占位，翻译后还原
  - 透明标签：LLM 翻译内容，标签结构由 restore 重建
  - 不透明标签：LLM 不接触，整体还原（sup/sub/br/img 等）
  - 无文字内容的透明标签也降级为不透明（如 <a id="anchor"/>）
- 跳过 pre/code 块（代码不翻译）
- 跳过已存在 class="ot-translation" 的节点（续翻时避免重复）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

# 作为翻译单元的块级标签
BLOCK_TAGS = frozenset(
    ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "blockquote", "figcaption", "dt", "dd"]
)

# 不翻译的块级标签
SKIP_TAGS = frozenset(["pre", "code", "script", "style"])

# 不透明内联标签：整体替换为 ⟦N⟧，内容不送入 LLM（脚注、上下标、图片等）
_OPAQUE_INLINE = frozenset({"sup", "sub", "br", "img", "wbr"})

# 透明内联标签：替换为 ⟦N⟧content⟦/N⟧，内容仍送入 LLM 翻译，标签结构由 restore 重建
_TRANSPARENT_INLINE = frozenset({
    "em", "strong", "b", "i", "u", "span", "a", "small", "big",
    "abbr", "cite", "q", "s", "del", "ins",
})

# 清理残留占位符的正则：匹配 <gN>、</gN>、[OT:N]
_PH_RE = re.compile(r"</?g\d+>|\[OT:\d+\]")


@dataclass
class _SavedTag:
    """序列化时保存的内联标签信息。"""
    tag_name: str
    attrs: dict
    opaque: bool
    original_html: str = ""   # 仅不透明标签使用：完整 HTML 供还原


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


def serialize_to_placeholders(inner_html: str) -> tuple[str, dict[int, _SavedTag]]:
    """将 inner_html 中的内联标签替换为 XML 风格占位符。

    - 透明标签（em/strong/a/span 等）有文字内容时 → <gN>content</gN>
      LLM 翻译内容，XML 标签随词移动；restore 重建原始 HTML 标签
    - 透明标签无文字内容（如 <a id="anchor"/>）→ 降级为 <xN/>（不透明）
    - 不透明标签（sup/sub/br/img 等）→ <xN/>
      LLM 完整保留，restore 恢复原始 HTML

    使用 XML 风格（而非 ⟦⟧）是因为翻译模型会把数学括号 ⟦⟧ 转译为 《》。

    Returns:
        (marked_text, saved)
        marked_text: 送入 LLM 的文本（含占位符）
        saved: 按 idx 保存的标签信息，供 restore_from_placeholders 还原
    """
    saved: dict[int, _SavedTag] = {}
    counter = [0]

    def _has_text(node) -> bool:
        """判断节点是否包含可翻译的文字内容。"""
        return any(
            isinstance(c, NavigableString) and str(c).strip()
            or (hasattr(c, "children") and _has_text(c))
            for c in node.children
        )

    def walk(node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        tag_name = getattr(node, "name", None)
        if not tag_name:
            return ""
        tag_name = tag_name.lower()

        if tag_name in _OPAQUE_INLINE:
            idx = counter[0]
            counter[0] += 1
            saved[idx] = _SavedTag(
                tag_name=tag_name,
                attrs=dict(node.attrs),
                opaque=True,
                original_html=str(node),
            )
            return f"[OT:{idx}]"

        if tag_name in _TRANSPARENT_INLINE:
            inner = "".join(walk(c) for c in node.children)
            idx = counter[0]
            counter[0] += 1
            # 无文字内容的透明标签（如空 anchor）降级为不透明
            if not inner.strip():
                saved[idx] = _SavedTag(
                    tag_name=tag_name,
                    attrs=dict(node.attrs),
                    opaque=True,
                    original_html=str(node),
                )
                return f"[OT:{idx}]"
            saved[idx] = _SavedTag(tag_name=tag_name, attrs=dict(node.attrs), opaque=False)
            return f"<g{idx}>{inner}</g{idx}>"

        # 其他标签（block 内嵌套的未知标签）：透传，递归处理子节点
        return "".join(walk(c) for c in node.children)

    soup = BeautifulSoup(f"<div>{inner_html}</div>", "html.parser")
    div = soup.find("div")
    result = "".join(walk(c) for c in div.children)
    return result, saved


def restore_from_placeholders(translated: str, saved: dict[int, _SavedTag]) -> str:
    """将 XML 风格占位符还原为原始 HTML 标签。

    按索引从大到小处理，确保内层标签先还原（避免嵌套字符串替换歧义）。
    LLM 如果丢弃了某个占位符，该标签直接丢失，不影响其他内容正确性。
    """
    if not saved:
        return translated

    result = translated
    for idx in sorted(saved.keys(), reverse=True):
        tag = saved[idx]

        if tag.opaque:
            # [OT:N] → original_html
            result = result.replace(f"[OT:{idx}]", tag.original_html, 1)
        else:
            # <gN>content</gN> → <original_tag attrs>content</original_tag>
            open_ph = f"<g{idx}>"
            close_ph = f"</g{idx}>"
            if open_ph in result and close_ph in result:
                start = result.index(open_ph)
                end = result.index(close_ph)
                if start < end:
                    content = result[start + len(open_ph):end]
                    rebuilt = _build_open_tag(tag.tag_name, tag.attrs) + content + f"</{tag.tag_name}>"
                    result = result[:start] + rebuilt + result[end + len(close_ph):]
                else:
                    # 开闭顺序错乱，丢弃标签保留内容
                    result = result.replace(open_ph, "", 1).replace(close_ph, "", 1)
            else:
                # LLM 丢弃了部分占位符，清理残留
                result = result.replace(open_ph, "", 1).replace(close_ph, "", 1)

    # 清理所有残留的孤立占位符
    return _PH_RE.sub("", result)


def _build_open_tag(tag_name: str, attrs: dict) -> str:
    """用标签名和属性字典重建开标签字符串。"""
    if not attrs:
        return f"<{tag_name}>"
    parts = [tag_name]
    for k, v in attrs.items():
        if isinstance(v, list):
            v = " ".join(str(x) for x in v)
        v = str(v).replace("&", "&amp;").replace('"', "&quot;")
        parts.append(f'{k}="{v}"')
    return "<" + " ".join(parts) + ">"


def _has_ancestor(tag: Tag, tag_names: frozenset[str]) -> bool:
    """检查 tag 是否有指定名称的祖先节点。"""
    for parent in tag.parents:
        if isinstance(parent, NavigableString):
            continue
        if getattr(parent, "name", None) in tag_names:
            return True
    return False
