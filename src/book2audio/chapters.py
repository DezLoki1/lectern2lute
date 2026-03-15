from __future__ import annotations

import re

from book2audio.cleanup import clean_text_for_tts, normalize_text, normalize_title
from book2audio.models import ChapterDraft, ParsedDocument, SourceSection
from book2audio.utils import slugify, word_count

CHAPTER_HEADING_RE = re.compile(
    r"^(?:"
    r"chapter|part|book|prologue|epilogue|foreword|afterword|appendix"
    r")\b(?:[\s:.-]+[a-z0-9ivxlcdm-]+.*)?$",
    re.IGNORECASE,
)
SKIP_SECTION_TITLES = {"contents", "table of contents"}


def build_chapters(document: ParsedDocument) -> list[ChapterDraft]:
    normalized_sections = [
        SourceSection(
            title=normalize_title(section.title, "") if section.title else None,
            text=normalize_text(section.text),
            source_hint=section.source_hint,
        )
        for section in document.sections
        if section.text and section.text.strip()
    ]

    if _looks_structured(document, normalized_sections):
        drafts = _chapters_from_sections(normalized_sections)
    else:
        combined = "\n\n".join(section.text for section in normalized_sections).strip()
        drafts = _chapters_from_combined_text(combined)

    if not drafts:
        combined = "\n\n".join(section.text for section in normalized_sections).strip()
        drafts = _fallback_chunks(combined)

    return [
        ChapterDraft(
            index=index,
            title=normalize_title(draft.title, f"Chapter {index}"),
            slug=slugify(draft.title or f"chapter-{index}"),
            raw_text=draft.raw_text.strip(),
            clean_text=clean_text_for_tts(draft.raw_text),
            source_hint=draft.source_hint,
        )
        for index, draft in enumerate(drafts, start=1)
        if draft.raw_text.strip()
    ]


def is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(CHAPTER_HEADING_RE.match(stripped))


def _looks_structured(document: ParsedDocument, sections: list[SourceSection]) -> bool:
    if document.source_format not in {"epub", "md"}:
        return False

    substantial_sections = [section for section in sections if word_count(section.text) >= 60]
    titled_sections = [section for section in substantial_sections if section.title]
    if len(substantial_sections) < 2:
        return False
    return len(titled_sections) / len(substantial_sections) >= 0.6


def _chapters_from_sections(sections: list[SourceSection]) -> list[ChapterDraft]:
    drafts: list[ChapterDraft] = []
    buffered_untitled: list[str] = []

    for section in sections:
        title = (section.title or "").strip()
        lowered = title.lower()
        section_words = word_count(section.text)
        if lowered in SKIP_SECTION_TITLES and section_words < 250:
            continue

        if not title and drafts:
            buffered_untitled.append(section.text.strip())
            continue

        if section_words < 30 and lowered in SKIP_SECTION_TITLES:
            continue

        raw_body = section.text.strip()
        if buffered_untitled and drafts:
            merged = "\n\n".join(buffered_untitled + [raw_body]).strip()
            buffered_untitled = []
            raw_body = merged

        chapter_title = title or f"Section {len(drafts) + 1}"
        raw_text = raw_body
        if title and not raw_body.lower().startswith(title.lower()):
            raw_text = f"{chapter_title}\n\n{raw_body}"

        drafts.append(
            ChapterDraft(
                index=0,
                title=chapter_title,
                slug="",
                raw_text=raw_text,
                source_hint=section.source_hint,
                clean_text="",
            )
        )

    if buffered_untitled and drafts:
        drafts[-1].raw_text = f"{drafts[-1].raw_text}\n\n" + "\n\n".join(buffered_untitled)

    return drafts


def _chapters_from_combined_text(text: str) -> list[ChapterDraft]:
    lines = text.splitlines()
    drafts: list[ChapterDraft] = []
    current_lines: list[str] = []
    current_title: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue

        if is_chapter_heading(stripped):
            if current_lines:
                _flush_chapter(drafts, current_lines, current_title)
                current_lines = []
            current_title = stripped
            current_lines = [stripped, ""]
            continue

        current_lines.append(stripped)

    if current_lines:
        _flush_chapter(drafts, current_lines, current_title)

    return [draft for draft in drafts if draft.raw_text.strip()]


def _flush_chapter(
    drafts: list[ChapterDraft], current_lines: list[str], current_title: str | None
) -> None:
    raw_text = "\n".join(current_lines).strip()
    if not raw_text:
        return

    if not current_title:
        title = "Front Matter" if not drafts else f"Section {len(drafts) + 1}"
    else:
        title = current_title

    drafts.append(
        ChapterDraft(
            index=0,
            title=title,
            slug="",
            raw_text=raw_text,
            source_hint=None,
            clean_text="",
        )
    )


def _fallback_chunks(text: str, target_words: int = 5000) -> list[ChapterDraft]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    drafts: list[ChapterDraft] = []
    current: list[str] = []
    current_words = 0

    for paragraph in paragraphs:
        paragraph_words = word_count(paragraph)
        if current and current_words + paragraph_words > target_words:
            chunk_text = "\n\n".join(current)
            drafts.append(
                ChapterDraft(
                    index=0,
                    title=f"Section {len(drafts) + 1}",
                    slug="",
                    raw_text=chunk_text,
                    source_hint=None,
                    clean_text="",
                )
            )
            current = []
            current_words = 0

        current.append(paragraph)
        current_words += paragraph_words

    if current:
        drafts.append(
            ChapterDraft(
                index=0,
                title=f"Section {len(drafts) + 1}",
                slug="",
                raw_text="\n\n".join(current),
                source_hint=None,
                clean_text="",
            )
        )

    return drafts
