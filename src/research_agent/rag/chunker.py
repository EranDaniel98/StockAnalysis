"""Chunking + HTML stripping for SEC filings.

EDGAR filings are typically HTML with lots of boilerplate (page numbers,
footers, repeating headers). We strip down to readable text, normalize
whitespace, then split into character-bounded chunks with overlap.

The chunker is intentionally simple — recursive-by-separator splitters
add complexity that doesn't pay off until 10s of millions of chunks.
For ~30K chunks per company-year, fixed-window with overlap is enough.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


# Approximate: 4 chars/token for English prose. 500 chars ≈ 125 tokens —
# well under MiniLM's 256-token context, leaves headroom for special chars.
DEFAULT_CHUNK_CHARS = 500
DEFAULT_OVERLAP_CHARS = 75


# Regex tag-stripper — cheap and good enough for EDGAR filings, which
# are mostly well-formed XHTML. A full BS4 parse is 10x slower and we
# don't need DOM semantics here.
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_PAGE_NUM_RE = re.compile(r"\n\s*\d{1,3}\s*\n")
_ENTITY_RE = re.compile(r"&(?:nbsp|amp|lt|gt|quot|#\d+);")
_ENTITY_MAP = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
}


def strip_html(html: str) -> str:
    """Best-effort HTML → plain text. Removes scripts, styles, tags,
    entities, then collapses whitespace. Doesn't try to preserve
    structure — chunks are searched semantically, not by section."""
    if not html:
        return ""
    text = _SCRIPT_RE.sub(" ", html)
    text = _STYLE_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)

    def _replace_entity(m: re.Match) -> str:
        token = m.group(0)
        if token in _ENTITY_MAP:
            return _ENTITY_MAP[token]
        if token.startswith("&#"):
            try:
                return chr(int(token[2:-1]))
            except ValueError:
                return " "
        return " "

    text = _ENTITY_RE.sub(_replace_entity, text)
    text = _PAGE_NUM_RE.sub("\n", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


@dataclass
class Chunk:
    text: str
    char_start: int
    char_end: int

    @property
    def approx_tokens(self) -> int:
        # 4 chars/token is a reasonable English-prose estimate.
        return max(1, len(self.text) // 4)


def chunk_text(
    text: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Split ``text`` into overlapping fixed-character windows.

    Windows respect word boundaries when possible — we walk back to the
    last space within the last 50 chars of each window. Tiny price to
    pay vs splitting mid-word and confusing the embedder.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [Chunk(text=text, char_start=0, char_end=len(text))]

    chunks: list[Chunk] = []
    step = chunk_chars - overlap_chars
    if step <= 0:
        raise ValueError("overlap must be smaller than chunk size")
    pos = 0
    while pos < len(text):
        end = min(pos + chunk_chars, len(text))
        # Back up to the nearest space if we're cutting mid-word and
        # there's a space within 50 chars of the boundary.
        if end < len(text):
            space = text.rfind(" ", max(end - 50, pos), end)
            if space > pos:
                end = space
        chunk_str = text[pos:end].strip()
        if chunk_str:
            chunks.append(Chunk(text=chunk_str, char_start=pos, char_end=end))
        if end == len(text):
            break
        pos = max(end - overlap_chars, pos + 1)
    return chunks


def iter_chunks(filings_text: Iterable[str], **kwargs) -> list[Chunk]:
    """Convenience: chunk multiple filings sequentially. Caller wants
    one flat list of Chunks regardless of provenance."""
    out: list[Chunk] = []
    for filing in filings_text:
        out.extend(chunk_text(filing, **kwargs))
    return out
