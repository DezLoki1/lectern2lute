from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
import wave
from pathlib import Path
from typing import Any


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "untitled"


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def estimate_minutes(text: str, words_per_minute: int = 165, speed: float = 1.0) -> float:
    return estimate_minutes_from_word_count(word_count(text), words_per_minute=words_per_minute, speed=speed)


def estimate_minutes_from_word_count(word_total: int, words_per_minute: int = 165, speed: float = 1.0) -> float:
    if word_total <= 0:
        return 0.0
    adjusted_wpm = max(1.0, words_per_minute * max(speed, 0.1))
    return round(word_total / adjusted_wpm, 2)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_audio_duration_seconds(path: Path) -> float | None:
    if not path.exists():
        return None

    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wav_file:
                frames = wav_file.getnframes()
                framerate = wav_file.getframerate()
                if framerate <= 0:
                    return None
                return frames / framerate
        except (wave.Error, OSError):
            return None

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def unique_directory(root: Path, slug: str, overwrite: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / slug
    if overwrite or not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        return target

    counter = 2
    while True:
        candidate = root / f"{slug}-{counter}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        counter += 1
