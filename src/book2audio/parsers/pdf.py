from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import fitz

from book2audio.models import ParsedDocument, SourceSection
from book2audio.parsers.base import DocumentParser

PAGE_NUMBER_RE = re.compile(r"^(?:page\s+)?\d+$", re.IGNORECASE)


class PdfParser(DocumentParser):
    source_format = "pdf"

    def parse(self, input_path: Path) -> ParsedDocument:
        with fitz.open(input_path) as document:
            title = (document.metadata or {}).get("title") or input_path.stem

            page_lines: list[list[str]] = []
            first_line_counts: Counter[str] = Counter()
            last_line_counts: Counter[str] = Counter()

            for page in document:
                lines = [line.strip() for line in page.get_text("text").splitlines() if line.strip()]
                if not lines:
                    page_lines.append([])
                    continue
                page_lines.append(lines)
                first_line_counts.update([lines[0]])
                last_line_counts.update([lines[-1]])

            repeated_headers = {
                line
                for line, count in first_line_counts.items()
                if count >= 3 and 3 <= len(line) <= 120 and not PAGE_NUMBER_RE.match(line)
            }
            repeated_footers = {
                line
                for line, count in last_line_counts.items()
                if count >= 3 and 3 <= len(line) <= 120 and not PAGE_NUMBER_RE.match(line)
            }

            sections: list[SourceSection] = []
            for page_number, lines in enumerate(page_lines, start=1):
                if not lines:
                    continue

                if lines and lines[0] in repeated_headers:
                    lines = lines[1:]
                if lines and lines[-1] in repeated_footers:
                    lines = lines[:-1]

                cleaned_lines = [line for line in lines if not PAGE_NUMBER_RE.match(line)]
                text = "\n".join(cleaned_lines).strip()
                if not text:
                    continue

                sections.append(SourceSection(text=text, source_hint=f"page {page_number}"))

        if not sections:
            raise ValueError("PDF contained no selectable text.")

        return ParsedDocument(
            title=title.strip(),
            source_format=self.source_format,
            parser_name=self.__class__.__name__,
            sections=sections,
        )
