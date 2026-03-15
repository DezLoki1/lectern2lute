import tempfile
import unittest
from pathlib import Path

from book2audio.pipeline import ingest_book


class PipelineTests(unittest.TestCase):
    def test_ingest_txt_creates_manifest_and_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis is the first chapter with enough words to keep the chapter detector "
                "happy and moving forward into a real project.\n\n"
                "Chapter 2\n\nThis is the second chapter, and it also contains enough words to keep "
                "the pipeline from collapsing into a single section.",
                encoding="utf-8",
            )

            project_dir, manifest = ingest_book(source, tmp_path / "projects")

            self.assertTrue(project_dir.exists())
            self.assertTrue((project_dir / "manifest.json").exists())
            self.assertEqual(len(manifest.chapters), 2)
            self.assertTrue((project_dir / manifest.chapters[0].clean_text_path).exists())


if __name__ == "__main__":
    unittest.main()
