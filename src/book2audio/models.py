from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SourceSection:
    text: str
    title: str | None = None
    source_hint: str | None = None


@dataclass(slots=True)
class ParsedDocument:
    title: str
    source_format: str
    parser_name: str
    sections: list[SourceSection]


@dataclass(slots=True)
class ChapterDraft:
    index: int
    title: str
    slug: str
    raw_text: str
    clean_text: str
    source_hint: str | None = None


@dataclass(slots=True)
class ChapterRecord:
    index: int
    title: str
    slug: str
    source_hint: str | None = None
    raw_text_path: str = ""
    clean_text_path: str = ""
    audio_path: str | None = None
    word_count: int = 0
    estimated_minutes: float = 0.0


@dataclass(slots=True)
class ProjectManifest:
    version: str
    title: str
    slug: str
    created_at: datetime
    source_file: str
    source_format: str
    source_sha256: str
    parser_name: str
    total_word_count: int
    total_estimated_minutes: float
    chapters: list[ChapterRecord]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectManifest":
        chapters = [ChapterRecord(**chapter) for chapter in payload["chapters"]]
        return cls(
            version=payload["version"],
            title=payload["title"],
            slug=payload["slug"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            source_file=payload["source_file"],
            source_format=payload["source_format"],
            source_sha256=payload["source_sha256"],
            parser_name=payload["parser_name"],
            total_word_count=payload["total_word_count"],
            total_estimated_minutes=payload["total_estimated_minutes"],
            chapters=chapters,
        )


@dataclass(slots=True)
class RenderSegment:
    chapter_index: int
    segment_index: int
    text: str
    text_path: str
    audio_path: str
