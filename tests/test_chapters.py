import unittest

from book2audio.chapters import build_chapters, is_chapter_heading
from book2audio.models import ParsedDocument, SourceSection


class ChapterTests(unittest.TestCase):
    def _build_plain_text_document(self, text: str) -> ParsedDocument:
        return ParsedDocument(
            title="Sample Book",
            source_format="txt",
            parser_name="TextParser",
            sections=[SourceSection(text=text)],
        )

    def test_chapter_detection_from_plain_text(self) -> None:
        document = self._build_plain_text_document(
            (
                "Chapter 1\n\nOnce upon a time there were enough words to form a chapter. "
                "This sentence keeps going so the chapter survives filtering.\n\n"
                "Chapter 2\n\nThis next chapter also has enough content to count. "
                "It keeps moving with another line of narrative so it remains substantial."
            )
        )

        chapters = build_chapters(document)

        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].title, "Chapter 1")
        self.assertEqual(chapters[1].title, "Chapter 2")

    def test_chapter_detection_from_timeline_headings(self) -> None:
        document = self._build_plain_text_document(
            (
                "Present Day\n\nThe opening section has enough content to count as a real chapter and "
                "keeps narrating so the detector has meaningful body text to work with.\n\n"
                "Three Weeks Earlier\n\nThe earlier timeline section also includes enough words to be "
                "treated as a substantial chapter rather than a stray heading."
            )
        )

        chapters = build_chapters(document)

        self.assertEqual([chapter.title for chapter in chapters], ["Present Day", "Three Weeks Earlier"])

    def test_timeline_heading_without_blank_line_after_is_detected(self) -> None:
        document = self._build_plain_text_document(
            (
                "Foreword\n\nThis introductory section has enough body text to be treated as a real section for the detector.\n"
                "Present Day\nThe story begins immediately on the next line because the PDF did not preserve a blank line after the heading.\n"
                "It still needs to become its own chapter when the heading stands alone.\n\n"
                "Three Weeks Earlier\nThe next timeline marker should also split cleanly."
            )
        )

        chapters = build_chapters(document)

        self.assertEqual(
            [chapter.title for chapter in chapters],
            ["Foreword", "Present Day", "Three Weeks Earlier"],
        )

    def test_chapter_detection_from_date_headings(self) -> None:
        document = self._build_plain_text_document(
            (
                "June 14, 1998\n\nThe first dated section should become its own chapter because the "
                "book uses standalone dates rather than numbered chapters.\n\n"
                "October 3, 2001\n\nThe second dated section should also stand on its own and hold "
                "together as a separate chapter in the parsed output."
            )
        )

        chapters = build_chapters(document)

        self.assertEqual([chapter.title for chapter in chapters], ["June 14, 1998", "October 3, 2001"])

    def test_chapter_detection_from_date_headings_without_blank_line_before(self) -> None:
        document = self._build_plain_text_document(
            (
                "Part One\n\nA short opening scene ends here.\n"
                "June 2, 1942\n\nThe next scene starts with a standalone date even though the PDF "
                "extraction did not preserve a blank line before it.\n\n"
                "June 9, 1942\nThe following scene also starts with a bare date line."
            )
        )

        chapters = build_chapters(document)

        self.assertEqual([chapter.title for chapter in chapters], ["Part One", "June 2, 1942", "June 9, 1942"])

    def test_chapter_detection_from_part_headings_and_weekdays(self) -> None:
        document = self._build_plain_text_document(
            (
                "Part III\n\nThis part opening should be preserved as its own section heading with "
                "enough words underneath it to count as a chapter-sized unit.\n\n"
                "Tuesday\n\nThe weekday heading should also be recognized when it stands alone and "
                "introduces a fresh block of narrative."
            )
        )

        chapters = build_chapters(document)

        self.assertEqual([chapter.title for chapter in chapters], ["Part III", "Tuesday"])

    def test_non_heading_prose_lines_do_not_trigger_part_or_book_splits(self) -> None:
        self.assertFalse(is_chapter_heading("part of federal law."))
        self.assertFalse(is_chapter_heading("book before I ask you out again?"))
        self.assertFalse(is_chapter_heading("section where the sights won't get bumped."))

    def test_trailing_part_heading_artifacts_are_dropped(self) -> None:
        document = self._build_plain_text_document(
            (
                "Part One\n\nThis opening part has enough narrative beneath it to remain in the parsed output.\n\n"
                "Part Two\n\nPart Three\n\nPart Four"
            )
        )

        chapters = build_chapters(document)

        self.assertEqual([chapter.title for chapter in chapters], ["Part One"])


if __name__ == "__main__":
    unittest.main()
