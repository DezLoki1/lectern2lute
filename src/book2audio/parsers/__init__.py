from __future__ import annotations

from pathlib import Path

from book2audio.parsers.base import DocumentParser


def get_parser(input_path: Path) -> DocumentParser:
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        from book2audio.parsers.pdf import PdfParser

        return PdfParser()
    if suffix == ".epub":
        from book2audio.parsers.epub import EpubParser

        return EpubParser()
    if suffix == ".md":
        from book2audio.parsers.markdown import MarkdownParser

        return MarkdownParser()
    if suffix == ".txt":
        from book2audio.parsers.txt import TextParser

        return TextParser()

    raise ValueError(f"Unsupported input type: {suffix or '<no extension>'}")
