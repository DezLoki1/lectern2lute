from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from book2audio.models import ParsedDocument


class DocumentParser(ABC):
    source_format: str

    @abstractmethod
    def parse(self, input_path: Path) -> ParsedDocument:
        raise NotImplementedError
