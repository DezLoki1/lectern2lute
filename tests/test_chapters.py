import unittest

from book2audio.chapters import build_chapters, is_chapter_heading
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

    def test_prose_lines_starting_with_heading_words_do_not_split_chapters(self) -> None:
        document = ParsedDocument(
            title="Sample Book",
            source_format="txt",
            parser_name="TextParser",
            sections=[
                SourceSection(
                    text=(
                        "Chapter 1\n\nIt began badly and got worse from there.\n"
                        "Part of me wanted to leave, but\nI stayed anyway.\n"
                        "Book reviews were harsh that year,\nand nobody read them.\n\n"
                        "Chapter 2\n\nThis next chapter also has enough content to count."
                    )
                )
            ],
        )

        chapters = build_chapters(document)

        self.assertEqual([chapter.title for chapter in chapters], ["Chapter 1", "Chapter 2"])
        self.assertIn("Part of me wanted to leave, but I stayed anyway.", chapters[0].clean_text)

    def test_heading_detection(self) -> None:
        headings = [
            "Chapter 1",
            "CHAPTER ONE",
            "Chapter 12.",
            "Chapter 1: The Beginning",
            "Chapter 1 The Beginning",
            "Chapter Twenty-One",
            "Part IV",
            "Book 3 - The Return",
            "Prologue",
            "Appendix A",
        ]
        prose = [
            "Part of me wanted to leave.",
            "Book reviews were harsh that year,",
            "Chapter 3 explains how the",
            "Part One of the story",
            "Part I wanted to go",
            "Prologue to the tale",
            "Parting words",
        ]
        for line in headings:
            self.assertTrue(is_chapter_heading(line), line)
        for line in prose:
            self.assertFalse(is_chapter_heading(line), line)


if __name__ == "__main__":
    unittest.main()
