from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "untitled"


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def estimate_minutes(text: str, words_per_minute: int = 165) -> float:
    words = word_count(text)
    if words == 0:
        return 0.0
    return round(words / words_per_minute, 2)


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
