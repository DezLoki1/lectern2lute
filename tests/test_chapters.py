import unittest

from book2audio.chapters import build_chapters
from book2audio.models import ParsedDocument, SourceSection


class ChapterTests(unittest.TestCase):
    def test_chapter_detection_from_plain_text(self) -> None:
        document = ParsedDocument(
            title="Sample Book",
            source_format="txt",
            parser_name="TextParser",
            sections=[
                SourceSection(
                    text=(
                        "Chapter 1\n\nOnce upon a time there were enough words to form a chapter. "
                        "This sentence keeps going so the chapter survives filtering.\n\n"
                        "Chapter 2\n\nThis next chapter also has enough content to count. "
                        "It keeps moving with another line of narrative so it remains substantial."
                    )
                )
            ],
        )

        chapters = build_chapters(document)

        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].title, "Chapter 1")
        self.assertEqual(chapters[1].title, "Chapter 2")


if __name__ == "__main__":
    unittest.main()
