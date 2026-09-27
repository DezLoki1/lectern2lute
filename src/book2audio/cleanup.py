from __future__ import annotations

import re

_NUMBER_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    r"|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty"
    r"|seventy|eighty|ninety|hundred)"
)
# After a heading label: nothing, or a separator and a subtitle ("Chapter IV: The Storm").
_HEADING_END = r"(?:\s*[.:-]?\s*$|\s*[.:-]\s*\S.*$)"

# A keyword alone isn't enough, or prose lines like "Part of me wanted..." would split
# chapters. Require a number or a bare keyword. A subtitle with no separator is only
# allowed after digits and must not start lowercase, which excludes "Chapter 3 explains...".
CHAPTER_HEADING_RE = re.compile(
    rf"""
    ^(?:
        (?:chapter|part|book)[\s.:-]+
        (?:
            \d+(?:{_HEADING_END}|\s+(?-i:[^\sa-z]).*$)
          | (?:[ivxlcdm]+|{_NUMBER_WORD}(?:[\s-]{_NUMBER_WORD})*){_HEADING_END}
        )
      | appendix[\s.:-]+(?:\d+|[a-z]|[ivxlcdm]+){_HEADING_END}
      | (?:prologue|epilogue|foreword|afterword){_HEADING_END}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
MAX_HEADING_CHARS = 120
PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s+)?\d+\s*$", re.IGNORECASE)
CAPTION_RE = re.compile(r"^\s*(?:figure|table|illustration|image)\s+\w+.*$", re.IGNORECASE)
TOC_LINE_RE = re.compile(r"^\s*.+\.{4,}\s*\d+\s*$")

UNICODE_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u00a0": " ",
}


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    for old, new in UNICODE_REPLACEMENTS.items():
        normalized = normalized.replace(old, new)

    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)
    normalized = re.sub(r"(\w)-\n(\w)", r"\1\2", normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    return normalized.strip()


def is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_CHARS or stripped.endswith(","):
        return False
    return bool(CHAPTER_HEADING_RE.match(stripped))


def normalize_title(title: str | None, fallback: str) -> str:
    value = title or fallback
    value = strip_markdown(value)
    value = normalize_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip() or fallback


def clean_text_for_tts(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = strip_noise_lines(cleaned)
    cleaned = strip_markdown(cleaned)
    cleaned = merge_wrapped_lines(cleaned)
    cleaned = remove_inline_references(cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([(\[{])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([)\]}])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_noise_lines(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if PAGE_NUMBER_RE.match(stripped):
            continue
        if CAPTION_RE.match(stripped):
            continue
        if TOC_LINE_RE.match(stripped):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines)


def strip_markdown(text: str) -> str:
    cleaned = re.sub(r"(?m)^#{1,6}\s+", "", text)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"`{1,3}", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"(?<!\*)\*\*(?!\*)(.+?)(?<!\*)\*\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!_)__(?!_)(.+?)(?<!_)__(?!_)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", cleaned)
    return cleaned


def merge_wrapped_lines(text: str) -> str:
    paragraphs: list[str] = []
    current = ""

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current.strip())
                current = ""
            continue

        if is_chapter_heading(stripped):
            if current:
                paragraphs.append(current.strip())
                current = ""
            paragraphs.append(stripped)
            continue

        if not current:
            current = stripped
            continue

        if current.endswith("-") and stripped[:1].islower():
            current = f"{current[:-1]}{stripped}"
            continue

        current = f"{current} {stripped}"

    if current:
        paragraphs.append(current.strip())

    return "\n\n".join(paragraphs)


def remove_inline_references(text: str) -> str:
    cleaned = re.sub(r"(?<=\w)\[(\d{1,3})\]", "", text)
    cleaned = re.sub(r"(?<=\w)\s+\[(\d{1,3})\]", "", cleaned)
    cleaned = re.sub(r"(?<=\w)\{(\d{1,3})\}", "", cleaned)
    return cleaned
