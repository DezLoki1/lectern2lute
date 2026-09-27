import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

from book2audio.parsers.epub import EpubParser


def _chapter(file_name: str, heading: str) -> epub.EpubHtml:
    item = epub.EpubHtml(title=heading, file_name=file_name, lang="en")
    item.content = f"<html><body><h1>{heading}</h1><p>Text for {heading}.</p></body></html>"
    return item


class EpubParserTests(unittest.TestCase):
    def test_sections_follow_spine_not_manifest_order(self) -> None:
        book = epub.EpubBook()
        book.set_identifier("spine-order")
        book.set_title("Spine Order")
        book.set_language("en")
        first = _chapter("first.xhtml", "First")
        second = _chapter("second.xhtml", "Second")
        # Manifest lists the second chapter first; the spine has the real reading order.
        book.add_item(second)
        book.add_item(first)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [first, second]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "book.epub"
            epub.write_epub(str(path), book)
            document = EpubParser().parse(path)

        self.assertEqual([section.title for section in document.sections], ["First", "Second"])


if __name__ == "__main__":
    unittest.main()
