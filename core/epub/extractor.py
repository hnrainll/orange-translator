"""从 XHTML 章节中提取可翻译的文本块。

策略（最小干预）：
- 以块级元素（p, h1-h6, li, td, th, blockquote, figcaption）为翻译单元
- 剥离装饰性内联标签（em/strong/span/a 等），仅保留文字内容
- <br/> → \n（LLM 自然保留换行，翻译后还原为 <br/>）
- <sup>/<sub> → 保留原始 HTML（LLM 能处理短数字标签）
- <a id="N"/> 空锚点 → 剥离（页码标记，不可见）
- 跳过 pre/code 块（代码不翻译）
- 跳过已存在 class="ot-translation" 的节点（续翻时避免重复）

设计原则：LLM 看到的越接近纯文本，翻译质量越高。
在双语 EPUB 中，原文紧邻译文，读者可直接看到原文格式，
译文不必保留 em/strong 等装饰性格式。
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

# 需剥离的装饰性内联标签（移除标签、保留文字内容）
_STRIP_INLINE = frozenset({
    "em", "strong", "b", "i", "u", "span", "a", "small", "big",
    "abbr", "cite", "q", "s", "del", "ins",
})


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


def preprocess_for_translation(inner_html: str) -> tuple[str, str]:
    """最小干预预处理：剥离装饰标签，保留关键结构。

    处理规则：
    1. 文本节点中已有的 \\n → 空格（HTML 本来就当空白处理，避免与 <br/> 混淆）
    2. <br/> → \\n（LLM 自然保留换行）
    3. 空锚点 <a id="N"/> → 剥离（页码标记，不可见）
    4. 装饰性标签（em/strong/span 等）→ 剥离标签，保留文字
    5. <sup>/<sub>/<img/> → 保留原始 HTML 不动

    Returns:
        (text_for_llm, br_html)
        text_for_llm: 近纯文本，LLM 翻译质量最高
        br_html: 用于还原 \\n → <br/> 的原始 HTML 字符串
    """
    soup = BeautifulSoup(f"<div>{inner_html}</div>", "html.parser")
    div = soup.find("div")

    # 记录第一个 <br/> 的原始 HTML（含 class 等属性），用于还原
    first_br = div.find("br")
    br_html = str(first_br) if first_br else "<br/>"

    # 1. 规范化文本节点中已有的 \n 为空格（HTML 本来就当空白处理）
    #    这样之后所有 \n 都是来自 <br/> 转换，还原时无歧义
    for text_node in list(div.find_all(string=True)):
        s = str(text_node)
        if "\n" in s:
            text_node.replace_with(NavigableString(s.replace("\n", " ")))

    # 2. <br/> → \n
    for br in list(div.find_all("br")):
        br.replace_with(NavigableString("\n"))

    # 3. 空锚点 <a id="N"/> 剥离（页码标记，不可见）
    #    有文字的 <a> 留给下面的 unwrap 处理
    for a in list(div.find_all("a")):
        if not a.get_text(strip=True):
            a.decompose()

    # 4. 剥离所有装饰性内联标签（保留文字内容和子元素）
    for tag_name in _STRIP_INLINE:
        for tag in list(div.find_all(tag_name)):
            tag.unwrap()

    # 5. sup/sub/img/wbr 保留原始 HTML 不动（已在 DOM 中）

    return div.decode_contents(), br_html


def postprocess_translation(translated: str, br_html: str) -> str:
    """还原翻译文本中的 \\n 为 <br/> 标签。

    预处理阶段已确保所有 \\n 都来自 <br/> 转换，
    这里安全地将它们全部还原。
    """
    return translated.replace("\n", br_html) if "\n" in translated else translated


def _has_ancestor(tag: Tag, tag_names: frozenset[str]) -> bool:
    """检查 tag 是否有指定名称的祖先节点。"""
    for parent in tag.parents:
        if isinstance(parent, NavigableString):
            continue
        if getattr(parent, "name", None) in tag_names:
            return True
    return False
