from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from book2audio.cleanup import normalize_title
from book2audio.models import ChapterDraft, ChapterRecord, ParsedDocument, ProjectManifest
from book2audio.utils import estimate_minutes, read_json, sha256_file, slugify, unique_directory, word_count, write_json

MANIFEST_NAME = "manifest.json"


def create_project(
    input_path: Path,
    output_root: Path,
    document: ParsedDocument,
    chapters: list[ChapterDraft],
    overwrite: bool = False,
) -> tuple[Path, ProjectManifest]:
    slug = slugify(document.title or input_path.stem)
    project_dir = unique_directory(output_root, slug, overwrite=overwrite)
    if overwrite:
        _clear_generated_project_files(project_dir)
    chapters_dir = project_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    chapter_records: list[ChapterRecord] = []
    total_word_count = 0
    total_estimated_minutes = 0.0

    for draft in chapters:
        file_stem = f"{draft.index:03d}-{draft.slug}"
        raw_path = chapters_dir / f"{file_stem}.raw.txt"
        clean_path = chapters_dir / f"{file_stem}.clean.txt"

        raw_path.write_text(draft.raw_text.strip() + "\n", encoding="utf-8")
        clean_path.write_text(draft.clean_text.strip() + "\n", encoding="utf-8")

        chapter_word_count = word_count(draft.clean_text)
        chapter_minutes = estimate_minutes(draft.clean_text)
        total_word_count += chapter_word_count
        total_estimated_minutes += chapter_minutes

        chapter_records.append(
            ChapterRecord(
                index=draft.index,
                title=draft.title,
                slug=draft.slug,
                source_hint=draft.source_hint,
                raw_text_path=str(raw_path.relative_to(project_dir).as_posix()),
                clean_text_path=str(clean_path.relative_to(project_dir).as_posix()),
                word_count=chapter_word_count,
                estimated_minutes=chapter_minutes,
            )
        )

    manifest = ProjectManifest(
        version="0.1.0",
        title=document.title,
        slug=project_dir.name,
        created_at=datetime.now(timezone.utc),
        source_file=str(input_path.resolve()),
        source_format=document.source_format,
        source_sha256=sha256_file(input_path),
        parser_name=document.parser_name,
        total_word_count=total_word_count,
        total_estimated_minutes=round(total_estimated_minutes, 2),
        chapters=chapter_records,
    )

    save_manifest(project_dir, manifest)
    return project_dir, manifest


def save_manifest(project_dir: Path, manifest: ProjectManifest) -> None:
    write_json(project_dir / MANIFEST_NAME, manifest.to_dict())


def load_manifest(project_dir: Path) -> ProjectManifest:
    payload = read_json(project_dir / MANIFEST_NAME)
    return ProjectManifest.from_dict(payload)


def update_chapter_clean_text(project_dir: Path, chapter_index: int, clean_text: str) -> ProjectManifest:
    manifest = load_manifest(project_dir)
    chapter = next((item for item in manifest.chapters if item.index == chapter_index), None)
    if chapter is None:
        raise ValueError(f"Chapter {chapter_index} was not found in the manifest.")

    normalized_text = clean_text.strip()
    target_path = project_dir / chapter.clean_text_path
    target_path.write_text(normalized_text + "\n", encoding="utf-8")

    chapter.word_count = word_count(normalized_text)
    chapter.estimated_minutes = estimate_minutes(normalized_text)

    manifest.total_word_count = sum(item.word_count for item in manifest.chapters)
    manifest.total_estimated_minutes = round(sum(item.estimated_minutes for item in manifest.chapters), 2)
    save_manifest(project_dir, manifest)
    return manifest


def rename_chapter_title(project_dir: Path, chapter_index: int, new_title: str) -> ProjectManifest:
    manifest, drafts = _load_chapter_drafts(project_dir)
    draft_index = _chapter_list_index(drafts, chapter_index)
    if draft_index is None:
        raise ValueError(f"Chapter {chapter_index} was not found in the manifest.")

    drafts[draft_index].title = normalize_title(new_title, drafts[draft_index].title)
    return _rewrite_chapter_structure(project_dir, manifest, drafts)


def delete_chapter(project_dir: Path, chapter_index: int) -> ProjectManifest:
    manifest, drafts = _load_chapter_drafts(project_dir)
    if len(drafts) <= 1:
        raise ValueError("You cannot delete the only chapter in the project.")

    draft_index = _chapter_list_index(drafts, chapter_index)
    if draft_index is None:
        raise ValueError(f"Chapter {chapter_index} was not found in the manifest.")

    del drafts[draft_index]
    return _rewrite_chapter_structure(project_dir, manifest, drafts)


def merge_chapters(project_dir: Path, chapter_index: int, *, direction: str) -> ProjectManifest:
    manifest, drafts = _load_chapter_drafts(project_dir)
    draft_index = _chapter_list_index(drafts, chapter_index)
    if draft_index is None:
        raise ValueError(f"Chapter {chapter_index} was not found in the manifest.")

    if direction == "previous":
        if draft_index == 0:
            raise ValueError("The first chapter cannot be merged upward.")
        anchor = drafts[draft_index - 1]
        target = drafts[draft_index]
        drafts[draft_index - 1] = ChapterDraft(
            index=0,
            title=anchor.title,
            slug="",
            raw_text=_join_chapter_text(anchor.raw_text, target.raw_text),
            clean_text=_join_chapter_text(anchor.clean_text, target.clean_text),
            source_hint=anchor.source_hint or target.source_hint,
        )
        del drafts[draft_index]
    elif direction == "next":
        if draft_index >= len(drafts) - 1:
            raise ValueError("The last chapter cannot be merged downward.")
        anchor = drafts[draft_index]
        target = drafts[draft_index + 1]
        drafts[draft_index] = ChapterDraft(
            index=0,
            title=anchor.title,
            slug="",
            raw_text=_join_chapter_text(anchor.raw_text, target.raw_text),
            clean_text=_join_chapter_text(anchor.clean_text, target.clean_text),
            source_hint=anchor.source_hint or target.source_hint,
        )
        del drafts[draft_index + 1]
    else:
        raise ValueError("direction must be 'previous' or 'next'.")

    return _rewrite_chapter_structure(project_dir, manifest, drafts)


def split_chapter(
    project_dir: Path,
    chapter_index: int,
    cursor_offset: int,
    *,
    new_title: str | None = None,
) -> ProjectManifest:
    manifest, drafts = _load_chapter_drafts(project_dir)
    draft_index = _chapter_list_index(drafts, chapter_index)
    if draft_index is None:
        raise ValueError(f"Chapter {chapter_index} was not found in the manifest.")

    draft = drafts[draft_index]
    split_offset = _normalize_split_offset(draft.clean_text, cursor_offset)
    first_clean = draft.clean_text[:split_offset].strip()
    second_clean = draft.clean_text[split_offset:].strip()

    if not first_clean or not second_clean:
        raise ValueError("Move the cursor deeper into the chapter before splitting it.")

    suggested_title = _suggest_split_title(second_clean, f"{draft.title} (Part 2)")
    second_title = normalize_title(new_title, suggested_title) if new_title else suggested_title

    drafts[draft_index : draft_index + 1] = [
        ChapterDraft(
            index=0,
            title=normalize_title(draft.title, draft.title),
            slug="",
            raw_text=first_clean,
            clean_text=first_clean,
            source_hint=draft.source_hint,
        ),
        ChapterDraft(
            index=0,
            title=second_title,
            slug="",
            raw_text=second_clean,
            clean_text=second_clean,
            source_hint=draft.source_hint,
        ),
    ]
    return _rewrite_chapter_structure(project_dir, manifest, drafts)


def find_existing_project(output_root: Path, source_file: Path) -> Path | None:
    if not output_root.exists():
        return None

    resolved_source = source_file.resolve()
    for candidate in output_root.iterdir():
        if not candidate.is_dir():
            continue
        manifest_path = candidate / MANIFEST_NAME
        if not manifest_path.exists():
            continue
        try:
            manifest = load_manifest(candidate)
        except (OSError, ValueError, KeyError):
            continue
        if Path(manifest.source_file).resolve() == resolved_source:
            return candidate

    return None


def _load_chapter_drafts(project_dir: Path) -> tuple[ProjectManifest, list[ChapterDraft]]:
    manifest = load_manifest(project_dir)
    drafts: list[ChapterDraft] = []

    for chapter in manifest.chapters:
        raw_path = project_dir / chapter.raw_text_path
        clean_path = project_dir / chapter.clean_text_path
        raw_text = raw_path.read_text(encoding="utf-8").rstrip() if raw_path.exists() else ""
        clean_text = clean_path.read_text(encoding="utf-8").rstrip() if clean_path.exists() else raw_text
        if not raw_text:
            raw_text = clean_text
        if not clean_text:
            clean_text = raw_text

        drafts.append(
            ChapterDraft(
                index=chapter.index,
                title=chapter.title,
                slug=chapter.slug,
                raw_text=raw_text,
                clean_text=clean_text,
                source_hint=chapter.source_hint,
            )
        )

    return manifest, drafts


def _rewrite_chapter_structure(
    project_dir: Path,
    manifest: ProjectManifest,
    drafts: list[ChapterDraft],
) -> ProjectManifest:
    if not drafts:
        raise ValueError("The project must contain at least one chapter.")

    _clear_project_output_directories(project_dir, "chapters", "renders", "samples")
    chapters_dir = project_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    chapter_records: list[ChapterRecord] = []
    total_word_count = 0
    total_estimated_minutes = 0.0

    for index, draft in enumerate(drafts, start=1):
        title = normalize_title(draft.title, f"Chapter {index}")
        slug = slugify(title or f"chapter-{index}")
        file_stem = f"{index:03d}-{slug}"
        raw_path = chapters_dir / f"{file_stem}.raw.txt"
        clean_path = chapters_dir / f"{file_stem}.clean.txt"

        raw_text = draft.raw_text.strip() or draft.clean_text.strip()
        clean_text = draft.clean_text.strip() or raw_text

        raw_path.write_text(raw_text + "\n", encoding="utf-8")
        clean_path.write_text(clean_text + "\n", encoding="utf-8")

        chapter_word_count = word_count(clean_text)
        chapter_minutes = estimate_minutes(clean_text)
        total_word_count += chapter_word_count
        total_estimated_minutes += chapter_minutes

        chapter_records.append(
            ChapterRecord(
                index=index,
                title=title,
                slug=slug,
                source_hint=draft.source_hint,
                raw_text_path=str(raw_path.relative_to(project_dir).as_posix()),
                clean_text_path=str(clean_path.relative_to(project_dir).as_posix()),
                audio_path=None,
                word_count=chapter_word_count,
                estimated_minutes=chapter_minutes,
            )
        )

    manifest.chapters = chapter_records
    manifest.total_word_count = total_word_count
    manifest.total_estimated_minutes = round(total_estimated_minutes, 2)
    save_manifest(project_dir, manifest)
    return manifest


def _chapter_list_index(drafts: list[ChapterDraft], chapter_index: int) -> int | None:
    for index, draft in enumerate(drafts):
        if draft.index == chapter_index:
            return index
    return None


def _join_chapter_text(first: str, second: str) -> str:
    left = first.strip()
    right = second.strip()
    if not left:
        return right
    if not right:
        return left
    return f"{left}\n\n{right}"


def _normalize_split_offset(text: str, cursor_offset: int) -> int:
    bounded = max(0, min(cursor_offset, len(text)))
    if bounded <= 0 or bounded >= len(text):
        raise ValueError("Place the cursor inside the chapter before splitting it.")

    if text[bounded - 1].isalnum() and text[bounded].isalnum():
        while bounded < len(text) and text[bounded].isalnum():
            bounded += 1
        if bounded >= len(text):
            raise ValueError("Move the cursor earlier in the chapter before splitting it.")

    left = text[:bounded].rstrip()
    if not left:
        raise ValueError("The split point cannot be at the beginning of the chapter.")
    return len(left)


def _suggest_split_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) <= 80 and word_count(stripped) <= 8 and stripped[-1:] not in ".!?;:":
            return normalize_title(stripped, fallback)
        break
    return normalize_title(fallback, fallback)


def _clear_generated_project_files(project_dir: Path) -> None:
    _clear_project_output_directories(project_dir, "chapters", "renders", "samples")

    manifest_path = project_dir / MANIFEST_NAME
    if manifest_path.exists():
        manifest_path.unlink()


def _clear_project_output_directories(project_dir: Path, *directory_names: str) -> None:
    for directory_name in directory_names:
        target = project_dir / directory_name
        if target.exists():
            shutil.rmtree(target)
