from __future__ import annotations

import re

from book2audio.cleanup import clean_text_for_tts, normalize_text, normalize_title
from book2audio.models import ChapterDraft, ParsedDocument, SourceSection
from book2audio.utils import slugify, word_count

NUMBER_DESIGNATOR_PATTERN = (
    r"(?:\d+|[ivxlcdm]+|[a-z]|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|"
    r"seventeenth|eighteenth|nineteenth|twentieth)"
)
CHAPTER_HEADING_RE = re.compile(
    rf"^chapter\b(?:[\s:.-]+{NUMBER_DESIGNATOR_PATTERN})?(?:[\s:.-]+.*)?$",
    re.IGNORECASE,
)
PART_HEADING_RE = re.compile(
    rf"^(?:part|book|section)\b(?:[\s:.-]+{NUMBER_DESIGNATOR_PATTERN})(?:[\s:.-]+.*)?$",
    re.IGNORECASE,
)
SPECIAL_HEADING_RE = re.compile(
    r"^(?:prologue|epilogue|foreword|afterword|interlude)\b(?:[\s:.-]+.*)?$",
    re.IGNORECASE,
)
APPENDIX_HEADING_RE = re.compile(
    rf"^appendix\b(?:[\s:.-]+{NUMBER_DESIGNATOR_PATTERN})?(?:[\s:.-]+.*)?$",
    re.IGNORECASE,
)
MONTH_PATTERN = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
WEEKDAY_PATTERN = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
NUMBER_WORD_PATTERN = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|few|several)"
)
DATE_HEADING_RE = re.compile(
    rf"^(?:"
    rf"{MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?|"
    rf"\d{{1,2}}\s+{MONTH_PATTERN}(?:\s+\d{{4}})?|"
    rf"{MONTH_PATTERN}\s+\d{{4}}|"
    rf"{WEEKDAY_PATTERN}(?:,\s+{MONTH_PATTERN}\s+\d{{1,2}}(?:,\s*\d{{4}})?)?|"
    rf"(?:18|19|20)\d{{2}}"
    rf")$",
    re.IGNORECASE,
)
TIMELINE_HEADING_RE = re.compile(
    rf"^(?:"
    rf"present\s+day|"
    rf"(?:the\s+)?(?:next|following|same|that|this)\s+"
    rf"(?:day|week|month|year|morning|afternoon|evening|night)|"
    rf"(?:{NUMBER_WORD_PATTERN}|\d+)\s+"
    rf"(?:day|days|week|weeks|month|months|year|years|hour|hours|minute|minutes)\s+"
    rf"(?:earlier|later|before|after)|"
    rf"(?:earlier|later)\s+(?:that|this|the)\s+"
    rf"(?:day|week|month|year|morning|afternoon|evening|night)"
    rf")$",
    re.IGNORECASE,
)
ROMAN_NUMERAL_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
SKIP_SECTION_TITLES = {"contents", "table of contents"}
DATE_OR_TIMELINE_MIN_FOLLOWING_WORDS = 8
CONTEXTUAL_HEADING_MIN_FOLLOWING_WORDS = 12


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

    drafts = _trim_trailing_part_heading_artifacts(drafts)

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
    if _matches_explicit_heading(stripped):
        return True
    return _looks_like_contextual_heading(stripped)


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

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue

        if _is_heading_at_line(lines, index):
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


def _is_heading_at_line(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    if not stripped:
        return False
    if _matches_explicit_heading(stripped):
        return True
    return _looks_like_contextual_heading(
        stripped,
        previous_line=lines[index - 1] if index > 0 else None,
        next_line=lines[index + 1] if index + 1 < len(lines) else None,
        following_lines=lines[index + 1 :],
    )


def _looks_like_contextual_heading(
    line: str,
    previous_line: str | None = None,
    next_line: str | None = None,
    following_lines: list[str] | None = None,
) -> bool:
    stripped = line.strip()
    following_word_count = _lookahead_word_count(following_lines or [])

    if DATE_HEADING_RE.match(stripped):
        return following_word_count >= DATE_OR_TIMELINE_MIN_FOLLOWING_WORDS
    if TIMELINE_HEADING_RE.match(stripped):
        return following_word_count >= DATE_OR_TIMELINE_MIN_FOLLOWING_WORDS

    if following_word_count < CONTEXTUAL_HEADING_MIN_FOLLOWING_WORDS:
        return False
    if not _has_heading_spacing_context(previous_line, next_line):
        return False
    return _looks_like_short_heading_with_date_or_time_cues(stripped)


def _trim_trailing_part_heading_artifacts(drafts: list[ChapterDraft]) -> list[ChapterDraft]:
    trim_index = len(drafts)
    while trim_index > 0 and _is_trailing_part_heading_artifact(drafts[trim_index - 1]):
        trim_index -= 1

    if len(drafts) - trim_index >= 2:
        return drafts[:trim_index]

    return drafts


def _is_trailing_part_heading_artifact(draft: ChapterDraft) -> bool:
    stripped = draft.raw_text.strip()
    title = draft.title.strip()
    return bool(
        stripped == title
        and PART_HEADING_RE.match(title)
        and word_count(stripped) <= 4
    )


def _matches_explicit_heading(line: str) -> bool:
    return bool(
        CHAPTER_HEADING_RE.match(line)
        or PART_HEADING_RE.match(line)
        or SPECIAL_HEADING_RE.match(line)
        or APPENDIX_HEADING_RE.match(line)
    )


def _has_heading_spacing_context(previous_line: str | None, next_line: str | None) -> bool:
    previous_blank = previous_line is None or not previous_line.strip()
    next_blank = next_line is not None and not next_line.strip()
    return previous_blank and next_blank


def _lookahead_word_count(following_lines: list[str], max_nonempty_lines: int = 3) -> int:
    collected: list[str] = []
    for line in following_lines:
        stripped = line.strip()
        if not stripped:
            continue
        collected.append(stripped)
        if len(collected) >= max_nonempty_lines:
            break
    return word_count(" ".join(collected))


def _looks_like_short_heading_with_date_or_time_cues(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) > 60 or word_count(stripped) > 6:
        return False
    if stripped[-1:] in ".!?;:":
        return False

    tokens = [token.strip(",") for token in re.split(r"[\s/-]+", stripped) if token.strip(",")]
    if not tokens:
        return False

    cue_tokens = {
        "present",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "morning",
        "afternoon",
        "evening",
        "night",
        "earlier",
        "later",
        "today",
        "yesterday",
        "tomorrow",
        "next",
        "following",
        "same",
        "this",
        "that",
    }
    month_tokens = {
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
    }
    weekday_tokens = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }

    lowered = [token.lower() for token in tokens]
    has_cue_token = bool(set(lowered) & (cue_tokens | month_tokens | weekday_tokens))
    has_year_or_roman = any(token.isdigit() or ROMAN_NUMERAL_RE.match(token) for token in tokens)
    if not has_cue_token and not has_year_or_roman:
        return False

    for token in tokens:
        if token.isdigit() or ROMAN_NUMERAL_RE.match(token):
            continue
        alpha = re.sub(r"[^A-Za-z]", "", token)
        if not alpha:
            continue
        if not (alpha.istitle() or alpha.isupper()):
            return False

    return True


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
