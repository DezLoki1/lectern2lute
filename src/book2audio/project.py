from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

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


def _clear_generated_project_files(project_dir: Path) -> None:
    for directory_name in ("chapters", "renders", "samples"):
        target = project_dir / directory_name
        if target.exists():
            shutil.rmtree(target)

    manifest_path = project_dir / MANIFEST_NAME
    if manifest_path.exists():
        manifest_path.unlink()
