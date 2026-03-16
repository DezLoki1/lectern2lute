import tempfile
import unittest
from pathlib import Path

from book2audio.pipeline import ingest_book
from book2audio.project import load_manifest, update_chapter_clean_text


class ProjectTests(unittest.TestCase):
    def test_update_chapter_clean_text_refreshes_manifest_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis is the first chapter in the test fixture.\n\n"
                "Chapter 2\n\nThis is the second chapter in the test fixture.",
                encoding="utf-8",
            )

            project_dir, manifest = ingest_book(source, tmp_path / "projects")
            original_total_words = manifest.total_word_count

            updated_manifest = update_chapter_clean_text(
                project_dir,
                1,
                "This replacement text is much longer and should increase the stored word count for the first chapter.",
            )
            reloaded_manifest = load_manifest(project_dir)
            updated_path = project_dir / updated_manifest.chapters[0].clean_text_path

            self.assertEqual(updated_manifest.total_word_count, reloaded_manifest.total_word_count)
            self.assertGreater(updated_manifest.total_word_count, original_total_words)
            self.assertIn("replacement text", updated_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
