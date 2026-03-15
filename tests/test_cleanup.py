import unittest

from book2audio.cleanup import clean_text_for_tts


class CleanupTests(unittest.TestCase):
    def test_cleanup_removes_page_numbers_and_markdown(self) -> None:
        source = """# Chapter 1

        12
        This is a wrapped
        paragraph with a [12] note.

        - bullet one
        - bullet two
        """
        cleaned = clean_text_for_tts(source)

        self.assertNotIn("12", cleaned)
        self.assertNotIn("# Chapter", cleaned)
        self.assertIn("wrapped paragraph", cleaned)
        self.assertNotIn("[12]", cleaned)
        self.assertIn("bullet one", cleaned)


if __name__ == "__main__":
    unittest.main()
