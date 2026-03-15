from __future__ import annotations

from pathlib import Path

from book2audio.models import ParsedDocument, SourceSection
from book2audio.parsers.base import DocumentParser


class TextParser(DocumentParser):
    source_format = "txt"

    def parse(self, input_path: Path) -> ParsedDocument:
        text = input_path.read_text(encoding="utf-8", errors="ignore")
        return ParsedDocument(
            title=input_path.stem,
            source_format=self.source_format,
            parser_name=self.__class__.__name__,
            sections=[SourceSection(text=text, source_hint="full-text")],
        )
