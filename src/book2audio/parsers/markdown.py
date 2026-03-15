from __future__ import annotations

import re
from pathlib import Path

from book2audio.models import ParsedDocument, SourceSection
from book2audio.parsers.base import DocumentParser

HEADING_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$")


class MarkdownParser(DocumentParser):
    source_format = "md"

    def parse(self, input_path: Path) -> ParsedDocument:
        text = input_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        sections: list[SourceSection] = []
        current_title: str | None = None
        current_lines: list[str] = []
        document_title = input_path.stem

        for line in lines:
            match = HEADING_RE.match(line.strip())
            if match:
                if current_lines:
                    sections.append(
                        SourceSection(
                            title=current_title,
                            text="\n".join(current_lines).strip(),
                            source_hint=current_title,
                        )
                    )
                    current_lines = []
                current_title = match.group(2).strip()
                if match.group(1) == "#" and document_title == input_path.stem:
                    document_title = current_title
                continue
            current_lines.append(line)

        if current_lines:
            sections.append(
                SourceSection(
                    title=current_title,
                    text="\n".join(current_lines).strip(),
                    source_hint=current_title or "body",
                )
            )

        if not sections:
            sections = [SourceSection(text=text, source_hint="full-text")]

        return ParsedDocument(
            title=document_title,
            source_format=self.source_format,
            parser_name=self.__class__.__name__,
            sections=sections,
        )
