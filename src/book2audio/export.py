from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from book2audio.models import ProjectManifest
from book2audio.project import load_manifest
from book2audio.utils import probe_audio_duration_seconds, write_json


def export_project_m4b(
    project_dir: Path,
    *,
    output_path: Path | None = None,
    title: str | None = None,
    author: str | None = None,
    narrator: str | None = None,
    overwrite: bool = False,
) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required on PATH to export an M4B audiobook.")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is required on PATH to export an M4B audiobook.")

    manifest = load_manifest(project_dir)
    chapter_files = _chapter_audio_files(project_dir, manifest)
    export_root = project_dir / "exports"
    export_root.mkdir(parents=True, exist_ok=True)

    target_path = output_path.resolve() if output_path is not None else export_root / f"{manifest.slug}.m4b"
    if target_path.exists() and not overwrite:
        raise RuntimeError(
            f"M4B output already exists: {target_path}. Use overwrite=True to regenerate it."
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    metadata_payload = {
        "title": title or manifest.title,
        "author": author or "",
        "narrator": narrator or "",
        "chapter_count": len(chapter_files),
        "source_project": str(project_dir),
    }

    with tempfile.TemporaryDirectory(prefix="m4b-export-", dir=str(export_root)) as temp_dir:
        temp_root = Path(temp_dir)
        concat_path = temp_root / "concat.txt"
        ffmetadata_path = temp_root / "chapters.ffmeta"
        metadata_json_path = target_path.with_suffix(".json")

        concat_path.write_text(_build_concat_manifest(chapter_files) + "\n", encoding="utf-8")
        ffmetadata_path.write_text(
            _build_ffmetadata(
                manifest,
                chapter_files,
                title=metadata_payload["title"],
                author=author,
                narrator=narrator,
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-i",
                str(ffmetadata_path),
                "-map",
                "0:a:0",
                "-map_metadata",
                "1",
                "-map_chapters",
                "1",
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "ffmpeg failed while exporting the M4B audiobook:\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        write_json(metadata_json_path, metadata_payload)
    return target_path


def _chapter_audio_files(project_dir: Path, manifest: ProjectManifest) -> list[tuple[Path, str]]:
    chapter_files: list[tuple[Path, str]] = []
    missing_titles: list[str] = []

    for chapter in manifest.chapters:
        if not chapter.audio_path:
            missing_titles.append(f"{chapter.index:03d} {chapter.title}")
            continue

        audio_path = project_dir / chapter.audio_path
        if not audio_path.exists():
            missing_titles.append(f"{chapter.index:03d} {chapter.title}")
            continue
        chapter_files.append((audio_path.resolve(), chapter.title))

    if missing_titles:
        preview = ", ".join(missing_titles[:5])
        extra = "" if len(missing_titles) <= 5 else f" and {len(missing_titles) - 5} more"
        raise ValueError(
            "M4B export requires rendered audio for every chapter. Missing audio for: "
            f"{preview}{extra}."
        )

    if not chapter_files:
        raise ValueError("M4B export requires at least one rendered chapter.")
    return chapter_files


def _build_concat_manifest(chapter_files: list[tuple[Path, str]]) -> str:
    return "\n".join(f"file '{audio_path.as_posix()}'" for audio_path, _title in chapter_files)


def _build_ffmetadata(
    manifest: ProjectManifest,
    chapter_files: list[tuple[Path, str]],
    *,
    title: str,
    author: str | None,
    narrator: str | None,
) -> str:
    lines = [";FFMETADATA1"]
    lines.append(f"title={_escape_ffmetadata(title)}")
    lines.append(f"album={_escape_ffmetadata(title)}")
    if author:
        lines.append(f"artist={_escape_ffmetadata(author)}")
    if narrator:
        lines.append(f"composer={_escape_ffmetadata(narrator)}")
    lines.append(f"comment={_escape_ffmetadata(f'Exported by lectern2lute from {manifest.title}')}")

    current_start_ms = 0
    for audio_path, chapter_title in chapter_files:
        duration_seconds = probe_audio_duration_seconds(audio_path)
        if duration_seconds is None:
            raise RuntimeError(f"Could not read audio duration for chapter file: {audio_path}")
        duration_ms = max(1, int(round(duration_seconds * 1000)))
        current_end_ms = current_start_ms + duration_ms

        lines.extend(
            [
                "",
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={current_start_ms}",
                f"END={current_end_ms}",
                f"title={_escape_ffmetadata(chapter_title)}",
            ]
        )
        current_start_ms = current_end_ms

    return "\n".join(lines) + "\n"


def _escape_ffmetadata(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("=", ";", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped.replace("\n", " ").strip()
