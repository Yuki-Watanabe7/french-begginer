"""HTML / plain text からタイトルと本文段落を取り出す（Issue #190）。

抽出は標準ライブラリの html.parser に閉じる。JavaScript は実行しない。
nav / footer / script / style などのノイズは本文に残さない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

_NOISE_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "iframe",
        "canvas",
        "nav",
        "footer",
    }
)
_LANDMARK_TAGS = frozenset({"article", "main"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "blockquote",
        "pre",
        "tr",
        "figcaption",
        "dd",
        "dt",
        "address",
        "figure",
        "table",
    }
)
_CHARSET_RE = re.compile(r"charset=\s*['\"]?\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(
    rb"""<meta\b[^>]*charset=['"]?\s*([A-Za-z0-9._-]+)""",
    re.IGNORECASE,
)
_META_HTTP_EQUIV_RE = re.compile(
    rb"""<meta\b[^>]*charset=([A-Za-z0-9._-]+)""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedHtml:
    title: str | None
    paragraphs: tuple[str, ...]
    canonical_href: str | None


def decode_page_text(body: bytes, *, media_type: str, content_type_header: str) -> str:
    """Content-Type の charset を優先し、HTML だけ meta charset を見る。"""

    charset = _charset_from_header(content_type_header)
    if charset is None and media_type in {"text/html", "application/xhtml+xml"}:
        charset = _charset_from_meta(body[:8192])
    encoding = "utf-8-sig" if charset is None or _is_utf8(charset) else charset
    try:
        return body.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace")


def extract_html(html: str) -> ExtractedHtml:
    """本文段落を文書順に返す。article / main があるときはその中だけを使う。"""

    parser = _HtmlExtractor()
    parser.feed(html)
    parser.close()
    return ExtractedHtml(
        title=parser.title(),
        paragraphs=parser.paragraphs(),
        canonical_href=parser.canonical_href,
    )


def plain_text_paragraphs(text: str) -> tuple[str, ...]:
    """空行で区切った plain text を、段落順のまま返す。"""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    for part in re.split(r"\n\s*\n", normalized):
        lines = [" ".join(line.split()) for line in part.split("\n") if line.strip()]
        if lines:
            paragraphs.append("\n".join(lines))
    return tuple(paragraphs)


class _HtmlExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_href: str | None = None
        self._title_parts: list[str] = []
        self._h1_parts: list[str] = []
        self._buffer: list[str] = []
        self._body: list[str] = []
        self._landmark: list[str] = []
        self._in_title = False
        self._in_head = False
        self._in_h1 = False
        self._saw_h1 = False
        self._skip_depth = 0
        self._landmark_depth = 0
        self._seen_landmark = False

    def title(self) -> str | None:
        title = _collapse_inline("".join(self._title_parts))
        if title:
            return title
        heading = _collapse_inline("".join(self._h1_parts))
        return heading or None

    def paragraphs(self) -> tuple[str, ...]:
        self._flush()
        chosen = self._landmark if self._seen_landmark else self._body
        return tuple(chosen)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        self._capture_head_metadata(name, attributes)
        if name == "head":
            self._in_head = True
            return
        if name == "title":
            self._in_title = True
            return
        if self._skip_depth:
            if name in _NOISE_TAGS:
                self._skip_depth += 1
            return
        if self._in_head:
            return
        if name in _LANDMARK_TAGS:
            self._flush()
            self._landmark_depth += 1
            self._seen_landmark = True
            return
        if name in _NOISE_TAGS:
            self._flush()
            self._skip_depth += 1
            return
        if name == "h1" and not self._saw_h1:
            self._in_h1 = True
        if name in _BLOCK_TAGS:
            self._flush()
            return
        if name == "br":
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "head":
            self._in_head = False
            self._in_title = False
            return
        if name == "title":
            self._in_title = False
            return
        if self._skip_depth:
            if name in _NOISE_TAGS:
                self._skip_depth -= 1
            return
        if self._in_head:
            return
        if name == "h1":
            self._in_h1 = False
            self._saw_h1 = True
        if name in _LANDMARK_TAGS and self._landmark_depth:
            self._flush()
            self._landmark_depth -= 1
            return
        if name in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip_depth or self._in_head:
            return
        if self._in_h1:
            self._h1_parts.append(data)
        self._buffer.append(data)

    def _capture_head_metadata(self, tag: str, attributes: dict[str, str]) -> None:
        if tag != "link" or self.canonical_href is not None:
            return
        rel = attributes.get("rel", "").lower().split()
        href = attributes.get("href", "").strip()
        if "canonical" in rel and href:
            self.canonical_href = href

    def _flush(self) -> None:
        text = _collapse_block("".join(self._buffer))
        self._buffer.clear()
        if not text:
            return
        if self._landmark_depth > 0:
            self._landmark.append(text)
        else:
            self._body.append(text)


def _collapse_inline(text: str) -> str:
    return " ".join(text.split())


def _collapse_block(text: str) -> str:
    lines = [
        " ".join(line.split())
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    kept = [line for line in lines if line]
    return "\n".join(kept)


def _charset_from_header(content_type: str) -> str | None:
    match = _CHARSET_RE.search(content_type)
    if match is None:
        return None
    return match.group(1)


def _charset_from_meta(prefix: bytes) -> str | None:
    match = _META_CHARSET_RE.search(prefix)
    if match is None:
        match = _META_HTTP_EQUIV_RE.search(prefix)
    if match is None:
        return None
    return match.group(1).decode("ascii", errors="ignore")


def _is_utf8(charset: str) -> bool:
    return charset.lower().replace("_", "-") in {"utf-8", "utf8", "utf-8-sig"}
