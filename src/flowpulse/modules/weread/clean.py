"""公众号正文清洗：按 class/id 关键词移除噪音子树。

内置默认规则去除公众号文章常见尾部噪音（PC 二维码、赞赏区、功能条、投票块），
订阅可叠加自定义关键词（逗号分隔，子串匹配，命中即移除整个子树）。
标准库 HTMLParser 实现，输出保持原始标签/实体写法。
"""

from __future__ import annotations

from html.parser import HTMLParser

# 自闭合标签：无子树可跳过，不计深度
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# 内置噪音规则（子串匹配 class/id，如 qr_code 命中 qr_code_pc_outer）
DEFAULT_STRIP_KEYWORDS = ("qr_code", "reward", "function_mod", "vote_class")


class _Stripper(HTMLParser):
    def __init__(self, keywords: list[str]):
        super().__init__(convert_charrefs=False)
        self._keywords = keywords
        self._out: list[str] = []
        self._skip_depth = 0

    def _hit(self, attrs: list[tuple[str, str | None]]) -> bool:
        for name, value in attrs:
            if name in ("class", "id") and value:
                lowered = value.lower()
                if any(k in lowered for k in self._keywords):
                    return True
        return False

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if self._hit(attrs):
            if tag not in _VOID_TAGS:
                self._skip_depth = 1
            return
        self._out.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        # 自闭合标签命中时直接丢弃，不影响深度
        if self._skip_depth or self._hit(attrs):
            return
        self._out.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag not in _VOID_TAGS:
                self._skip_depth -= 1
            return
        self._out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._skip_depth:
            self._out.append(data)

    def handle_entityref(self, name):
        if not self._skip_depth:
            self._out.append(f"&{name};")

    def handle_charref(self, name):
        if not self._skip_depth:
            self._out.append(f"&#{name};")

    def handle_comment(self, data):
        pass  # 注释一律丢弃


def _parse_keywords(extra: str | list[str]) -> list[str]:
    if isinstance(extra, str):
        raw = extra.replace("，", ",").split(",")
        items = [k.strip().lower() for k in raw]
    else:
        items = [k.strip().lower() for k in extra]
    return list(dict.fromkeys([*DEFAULT_STRIP_KEYWORDS, *[k for k in items if k]]))


def clean_html(html: str, extra_keywords: str | list[str] = "") -> str:
    """移除命中关键词的元素子树后返回剩余 HTML；空输入原样返回空串。"""
    if not html:
        return ""
    parser = _Stripper(_parse_keywords(extra_keywords))
    parser.feed(html)
    parser.close()
    return "".join(parser._out)
