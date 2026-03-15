from __future__ import annotations

from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from book2audio.models import ParsedDocument, SourceSection
from book2audio.parsers.base import DocumentParser


class EpubParser(DocumentParser):
    source_format = "epub"

    def parse(self, input_path: Path) -> ParsedDocument:
        book = epub.read_epub(str(input_path))
        title = self._read_title(book) or input_path.stem
        sections: list[SourceSection] = []

        for item in book.get_items():
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            soup = BeautifulSoup(item.get_body_content(), "html.parser")
            for tag_name in ("script", "style", "nav"):
                for tag in soup.find_all(tag_name):
                    tag.decompose()

            text = soup.get_text("\n").strip()
            if not text:
                continue

            heading = None
            for tag_name in ("h1", "h2", "h3"):
                heading_tag = soup.find(tag_name)
                if heading_tag and heading_tag.get_text(strip=True):
                    heading = heading_tag.get_text(" ", strip=True)
                    break

            sections.append(
                SourceSection(
                    title=heading,
                    text=text,
                    source_hint=item.get_name(),
                )
            )

        if not sections:
            raise ValueError("EPUB contained no readable document sections.")

        return ParsedDocument(
            title=title,
            source_format=self.source_format,
            parser_name=self.__class__.__name__,
            sections=sections,
        )

    @staticmethod
    def _read_title(book: epub.EpubBook) -> str | None:
        metadata = book.get_metadata("DC", "title")
        if metadata:
            return str(metadata[0][0]).strip()
        return None
