from __future__ import annotations

from pathlib import Path

from book2audio.chapters import build_chapters
from book2audio.parsers import get_parser
from book2audio.project import create_project, find_existing_project, load_manifest


def ingest_book(input_path: Path, output_root: Path, overwrite: bool = False):
    parser = get_parser(input_path)
    document = parser.parse(input_path)
    chapters = build_chapters(document)
    if not chapters:
        raise ValueError("No chapters were produced from the parsed text.")
    return create_project(input_path, output_root, document, chapters, overwrite=overwrite)


def ensure_project(input_path: Path, output_root: Path, overwrite: bool = False):
    existing_project = None if overwrite else find_existing_project(output_root, input_path)
    if existing_project is not None:
        return existing_project, load_manifest(existing_project)
    return ingest_book(input_path, output_root, overwrite=overwrite)
