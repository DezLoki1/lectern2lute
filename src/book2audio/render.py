from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from book2audio.models import ProjectManifest, RenderSegment
from book2audio.project import load_manifest, save_manifest
from book2audio.tts.base import TTSBackend
from book2audio.utils import estimate_minutes, write_json, word_count

SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class RenderProgress:
    phase: str
    chapter_index: int | None
    chapter_title: str | None
    chapter_position: int
    total_chapters: int
    segment_index: int
    total_segments_in_chapter: int
    completed_units: int
    total_units: int
    percent: float
    message: str


ProgressCallback = Callable[[RenderProgress], None]


def split_text_into_segments(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    segments: list[str] = []
    current_parts: list[str] = []

    for paragraph in paragraphs:
        units = [paragraph]
        if len(paragraph) > max_chars:
            units = [unit.strip() for unit in SENTENCE_BOUNDARY_RE.split(paragraph) if unit.strip()]
        if not units:
            continue

        for unit in units:
            if len(unit) > max_chars:
                if current_parts:
                    segments.append("\n\n".join(current_parts))
                    current_parts = []
                for chunk in _split_long_unit(unit, max_chars):
                    segments.append(chunk)
                continue

            candidate_parts = current_parts + [unit]
            candidate = "\n\n".join(candidate_parts)
            if len(candidate) <= max_chars:
                current_parts = candidate_parts
            else:
                if current_parts:
                    segments.append("\n\n".join(current_parts))
                current_parts = [unit]

    if current_parts:
        segments.append("\n\n".join(current_parts))

    return segments


def render_project(
    project_dir: Path,
    backend: TTSBackend,
    *,
    voice: str,
    chapter_indexes: list[int] | None = None,
    max_segment_chars: int = 900,
    sample_rate: int = 24000,
    overwrite: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> ProjectManifest:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required on PATH to render chapter MP3 files.")

    manifest = load_manifest(project_dir)
    render_root = project_dir / "renders"
    render_root.mkdir(parents=True, exist_ok=True)

    requested = set(chapter_indexes or [])
    chapter_plans: list[dict[str, object]] = []
    for chapter in manifest.chapters:
        if requested and chapter.index not in requested:
            continue

        chapter_dir = render_root / f"{chapter.index:03d}-{chapter.slug}"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        output_mp3 = chapter_dir / "chapter.mp3"
        if output_mp3.exists() and not overwrite:
            chapter.audio_path = str(output_mp3.relative_to(project_dir).as_posix())
            continue

        text = (project_dir / chapter.clean_text_path).read_text(encoding="utf-8")
        segments = split_text_into_segments(text, max_chars=max_segment_chars)
        chapter_plans.append(
            {
                "chapter": chapter,
                "chapter_dir": chapter_dir,
                "output_mp3": output_mp3,
                "segments": segments,
            }
        )

    total_chapters = len(chapter_plans)
    total_units = sum(len(plan["segments"]) + 1 for plan in chapter_plans)
    completed_units = 0

    if total_units == 0:
        _emit_progress(
            progress_callback,
            phase="complete",
            chapter_index=None,
            chapter_title=None,
            chapter_position=0,
            total_chapters=0,
            segment_index=0,
            total_segments_in_chapter=0,
            completed_units=0,
            total_units=0,
            message="Nothing to render. Existing chapter audio is already up to date.",
        )
        save_manifest(project_dir, manifest)
        return manifest

    for chapter_position, plan in enumerate(chapter_plans, start=1):
        chapter = plan["chapter"]
        chapter_dir = plan["chapter_dir"]
        output_mp3 = plan["output_mp3"]
        segments = plan["segments"]

        _emit_progress(
            progress_callback,
            phase="chapter_start",
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segment_index=0,
            total_segments_in_chapter=len(segments),
            completed_units=completed_units,
            total_units=total_units,
            message=f"Starting chapter {chapter_position}/{total_chapters}: {chapter.title}",
        )

        segment_records = _render_segments(
            chapter_dir=chapter_dir,
            backend=backend,
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segments=segments,
            voice=voice,
            sample_rate=sample_rate,
            progress_callback=progress_callback,
            completed_units=completed_units,
            total_units=total_units,
        )
        completed_units += len(segment_records)
        _write_render_plan(chapter_dir, chapter.index, chapter.title, segments)

        _emit_progress(
            progress_callback,
            phase="stitching",
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segment_index=len(segments),
            total_segments_in_chapter=len(segments),
            completed_units=completed_units,
            total_units=total_units,
            message=f"Stitching chapter {chapter_position}/{total_chapters}: {chapter.title}",
        )
        _concat_segments(segment_records, output_mp3)
        completed_units += 1
        _emit_progress(
            progress_callback,
            phase="chapter_complete",
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segment_index=len(segments),
            total_segments_in_chapter=len(segments),
            completed_units=completed_units,
            total_units=total_units,
            message=f"Finished chapter {chapter_position}/{total_chapters}: {chapter.title}",
        )
        chapter.audio_path = str(output_mp3.relative_to(project_dir).as_posix())

    save_manifest(project_dir, manifest)
    _emit_progress(
        progress_callback,
        phase="complete",
        chapter_index=None,
        chapter_title=None,
        chapter_position=total_chapters,
        total_chapters=total_chapters,
        segment_index=0,
        total_segments_in_chapter=0,
        completed_units=completed_units,
        total_units=total_units,
        message=f"Finished rendering {total_chapters} chapters.",
    )
    return manifest


def render_sample(
    project_dir: Path,
    backend: TTSBackend,
    *,
    voice: str,
    chapter_index: int = 1,
    sample_chars: int = 650,
    sample_rate: int = 24000,
    overwrite: bool = False,
    progress_callback: ProgressCallback | None = None,
    sample_metadata: dict[str, Any] | None = None,
) -> Path:
    manifest = load_manifest(project_dir)
    chapter = next((item for item in manifest.chapters if item.index == chapter_index), None)
    if chapter is None:
        raise ValueError(f"Chapter {chapter_index} was not found in the manifest.")

    text = (project_dir / chapter.clean_text_path).read_text(encoding="utf-8").strip()
    sample_text = extract_sample_text(text, max_chars=sample_chars)
    if not sample_text:
        raise ValueError("Sample text was empty after cleanup and segmentation.")

    samples_dir = project_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    sample_stem = f"{chapter.index:03d}-{chapter.slug}-{voice}"
    text_path = samples_dir / f"{sample_stem}.txt"
    wav_path = samples_dir / f"{sample_stem}.wav"
    mp3_path = samples_dir / f"{sample_stem}.mp3"
    metadata_path = samples_dir / f"{sample_stem}.json"

    if mp3_path.exists() and not overwrite:
        _emit_progress(
            progress_callback,
            phase="complete",
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_position=1,
            total_chapters=1,
            segment_index=1,
            total_segments_in_chapter=1,
            completed_units=2,
            total_units=2,
            message=f"Sample already exists for {chapter.title}.",
        )
        return mp3_path

    text_path.write_text(sample_text + "\n", encoding="utf-8")
    _emit_progress(
        progress_callback,
        phase="segment_start",
        chapter_index=chapter.index,
        chapter_title=chapter.title,
        chapter_position=1,
        total_chapters=1,
        segment_index=1,
        total_segments_in_chapter=1,
        completed_units=0,
        total_units=2,
        message=f"Generating sample from {chapter.title}",
    )
    backend.synthesize(
        sample_text,
        text_path,
        wav_path,
        voice=voice,
        sample_rate=sample_rate,
    )
    _emit_progress(
        progress_callback,
        phase="segment_complete",
        chapter_index=chapter.index,
        chapter_title=chapter.title,
        chapter_position=1,
        total_chapters=1,
        segment_index=1,
        total_segments_in_chapter=1,
        completed_units=1,
        total_units=2,
        message=f"Encoding sample for {chapter.title}",
    )
    _encode_wav_to_mp3(wav_path, mp3_path)
    wav_path.unlink(missing_ok=True)
    metadata_payload = {
        "voice": voice,
        "chapter_index": chapter.index,
        "chapter_title": chapter.title,
        "sample_chars": sample_chars,
        "sample_rate": sample_rate,
        "word_count": word_count(sample_text),
    }
    if sample_metadata:
        metadata_payload.update(sample_metadata)
    write_json(metadata_path, metadata_payload)
    _emit_progress(
        progress_callback,
        phase="complete",
        chapter_index=chapter.index,
        chapter_title=chapter.title,
        chapter_position=1,
        total_chapters=1,
        segment_index=1,
        total_segments_in_chapter=1,
        completed_units=2,
        total_units=2,
        message=f"Finished sample for {chapter.title}",
    )
    return mp3_path


def _render_segments(
    *,
    chapter_dir: Path,
    backend: TTSBackend,
    chapter_index: int,
    chapter_title: str,
    chapter_position: int,
    total_chapters: int,
    segments: list[str],
    voice: str,
    sample_rate: int,
    progress_callback: ProgressCallback | None,
    completed_units: int,
    total_units: int,
) -> list[RenderSegment]:
    records: list[RenderSegment] = []
    for segment_index, segment_text in enumerate(segments, start=1):
        text_path = chapter_dir / f"segment-{segment_index:03d}.txt"
        audio_path = chapter_dir / f"segment-{segment_index:03d}.wav"
        text_path.write_text(segment_text.strip() + "\n", encoding="utf-8")
        _emit_progress(
            progress_callback,
            phase="segment_start",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segment_index=segment_index,
            total_segments_in_chapter=len(segments),
            completed_units=completed_units + len(records),
            total_units=total_units,
            message=(
                f"Rendering chapter {chapter_position}/{total_chapters} "
                f"segment {segment_index}/{len(segments)}: {chapter_title}"
            ),
        )
        backend.synthesize(
            segment_text,
            text_path,
            audio_path,
            voice=voice,
            sample_rate=sample_rate,
        )
        records.append(
            RenderSegment(
                chapter_index=chapter_index,
                segment_index=segment_index,
                text=segment_text,
                text_path=str(text_path),
                audio_path=str(audio_path),
            )
        )
        _emit_progress(
            progress_callback,
            phase="segment_complete",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segment_index=segment_index,
            total_segments_in_chapter=len(segments),
            completed_units=completed_units + len(records),
            total_units=total_units,
            message=(
                f"Finished segment {segment_index}/{len(segments)} "
                f"for chapter {chapter_position}/{total_chapters}: {chapter_title}"
            ),
        )
    return records


def _write_render_plan(chapter_dir: Path, chapter_index: int, title: str, segments: list[str]) -> None:
    payload = {
        "chapter_index": chapter_index,
        "title": title,
        "segment_count": len(segments),
        "estimated_minutes": estimate_minutes("\n\n".join(segments)),
        "segments": [
            {
                "segment_index": index,
                "char_count": len(segment),
                "word_count": word_count(segment),
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }
    write_json(chapter_dir / "render-plan.json", payload)


def extract_sample_text(text: str, max_chars: int = 650) -> str:
    segments = split_text_into_segments(text, max_chars=max_chars)
    if segments:
        return segments[0].strip()
    return text[:max_chars].strip()


def _concat_segments(segments: list[RenderSegment], output_mp3: Path) -> None:
    list_file = output_mp3.parent / "concat.txt"
    concat_payload = "\n".join(
        f"file '{Path(segment.audio_path).resolve().as_posix()}'" for segment in segments
    )
    list_file.write_text(concat_payload + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_mp3),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed while stitching chapter audio:\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _encode_wav_to_mp3(wav_path: Path, output_mp3: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_mp3),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed while encoding sample audio:\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _split_long_unit(unit: str, max_chars: int) -> list[str]:
    words = unit.split()
    chunks: list[str] = []
    current_words: list[str] = []

    for word in words:
        candidate = " ".join(current_words + [word]).strip()
        if current_words and len(candidate) > max_chars:
            chunks.append(" ".join(current_words))
            current_words = [word]
            continue
        current_words.append(word)

    if current_words:
        chunks.append(" ".join(current_words))
    return chunks


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    phase: str,
    chapter_index: int | None,
    chapter_title: str | None,
    chapter_position: int,
    total_chapters: int,
    segment_index: int,
    total_segments_in_chapter: int,
    completed_units: int,
    total_units: int,
    message: str,
) -> None:
    if callback is None:
        return

    if total_units <= 0:
        percent = 100.0
    else:
        percent = round((completed_units / total_units) * 100, 2)

    callback(
        RenderProgress(
            phase=phase,
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            chapter_position=chapter_position,
            total_chapters=total_chapters,
            segment_index=segment_index,
            total_segments_in_chapter=total_segments_in_chapter,
            completed_units=completed_units,
            total_units=total_units,
            percent=percent,
            message=message,
        )
    )
