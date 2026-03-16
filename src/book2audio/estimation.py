from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from book2audio.models import ProjectManifest
from book2audio.utils import estimate_minutes_from_word_count, probe_audio_duration_seconds, read_json

DEFAULT_WPM = 165


@dataclass(slots=True)
class ProjectRuntimeEstimate:
    minutes: float
    hours: float
    source: str
    label: str


def estimate_project_runtime(
    project_dir: Path,
    manifest: ProjectManifest,
    *,
    voice: str,
    speed: float,
) -> ProjectRuntimeEstimate:
    total_words = sum(chapter.word_count for chapter in manifest.chapters)
    base_minutes = estimate_minutes_from_word_count(total_words, words_per_minute=DEFAULT_WPM, speed=speed)

    sample_minutes = _sample_calibrated_minutes(project_dir, manifest, voice=voice, speed=speed)
    if sample_minutes is not None:
        return _build_estimate(sample_minutes, source="sample")

    return _build_estimate(base_minutes, source="word_count")


def _sample_calibrated_minutes(
    project_dir: Path,
    manifest: ProjectManifest,
    *,
    voice: str,
    speed: float,
) -> float | None:
    samples_dir = project_dir / "samples"
    if not samples_dir.exists():
        return None

    matched_words = 0
    matched_seconds = 0.0
    speed_key = round(speed, 3)

    for metadata_path in samples_dir.glob(f"*-{voice}.json"):
        try:
            metadata = read_json(metadata_path)
        except (OSError, ValueError, KeyError):
            continue

        if metadata.get("voice") != voice:
            continue
        if round(float(metadata.get("speed", 0.0)), 3) != speed_key:
            continue

        sample_word_count = int(metadata.get("word_count", 0))
        if sample_word_count <= 0:
            continue

        audio_path = metadata_path.with_suffix(".mp3")
        duration_seconds = probe_audio_duration_seconds(audio_path)
        if duration_seconds is None or duration_seconds <= 0:
            continue

        matched_words += sample_word_count
        matched_seconds += duration_seconds

    if matched_words <= 0 or matched_seconds <= 0:
        return None

    total_words = sum(chapter.word_count for chapter in manifest.chapters)
    total_seconds = matched_seconds * total_words / matched_words
    return round(total_seconds / 60.0, 2)


def _build_estimate(minutes: float, *, source: str) -> ProjectRuntimeEstimate:
    hours = round(minutes / 60.0, 2)
    if source == "sample":
        label = f"{minutes:.2f} min ({hours:.2f} hr, sample-calibrated)"
    else:
        label = f"{minutes:.2f} min ({hours:.2f} hr)"
    return ProjectRuntimeEstimate(minutes=minutes, hours=hours, source=source, label=label)
