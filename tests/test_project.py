import tempfile
import unittest
from pathlib import Path

from book2audio.pipeline import ingest_book
from book2audio.project import (
    delete_chapter,
    load_manifest,
    merge_chapters,
    rename_chapter_title,
    split_chapter,
    update_chapter_clean_text,
)


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

    def test_overwrite_ingest_clears_stale_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis is enough text to create a project fixture for rebuild testing.",
                encoding="utf-8",
            )

            project_dir, _manifest = ingest_book(source, tmp_path / "projects")
            stale_chapter = project_dir / "chapters" / "stale.raw.txt"
            stale_sample = project_dir / "samples" / "old-sample.mp3"
            stale_render = project_dir / "renders" / "old" / "chapter.mp3"

            stale_chapter.write_text("old", encoding="utf-8")
            stale_sample.parent.mkdir(parents=True, exist_ok=True)
            stale_sample.write_text("old", encoding="utf-8")
            stale_render.parent.mkdir(parents=True, exist_ok=True)
            stale_render.write_text("old", encoding="utf-8")

            ingest_book(source, tmp_path / "projects", overwrite=True)

            self.assertFalse(stale_chapter.exists())
            self.assertFalse(stale_sample.exists())
            self.assertFalse(stale_render.exists())

    def test_rename_delete_merge_and_split_chapters_rewrite_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nFirst chapter text has enough words to support the structure editing tests.\n\n"
                "Chapter 2\n\nHeading Two\n\nSecond chapter text also has enough words to survive a split.\n\n"
                "Chapter 3\n\nThird chapter text is here so merge and delete have something to work with.",
                encoding="utf-8",
            )

            project_dir, _manifest = ingest_book(source, tmp_path / "projects")

            renamed_manifest = rename_chapter_title(project_dir, 2, "Renamed Middle")
            self.assertEqual(renamed_manifest.chapters[1].title, "Renamed Middle")

            update_chapter_clean_text(
                project_dir,
                2,
                "Renamed Middle\n\nLead-in text before the inserted break.\n\n"
                "Heading Two\n\nSecond chapter text also has enough words to survive a split.",
            )
            split_manifest = split_chapter(
                project_dir,
                2,
                cursor_offset=len("Renamed Middle\n\nLead-in text before the inserted break.\n\n"),
                new_title="Inserted Split",
            )
            self.assertEqual(
                [chapter.title for chapter in split_manifest.chapters],
                ["Chapter 1", "Renamed Middle", "Inserted Split", "Chapter 3"],
            )
            split_text = (project_dir / split_manifest.chapters[2].clean_text_path).read_text(encoding="utf-8")
            self.assertIn("Heading Two", split_text)

            merged_manifest = merge_chapters(project_dir, 3, direction="previous")
            self.assertEqual(
                [chapter.title for chapter in merged_manifest.chapters],
                ["Chapter 1", "Renamed Middle", "Chapter 3"],
            )
            merged_text = (project_dir / merged_manifest.chapters[1].clean_text_path).read_text(encoding="utf-8")
            self.assertIn("Heading Two", merged_text)
            self.assertIn("Second chapter text", merged_text)

            deleted_manifest = delete_chapter(project_dir, 2)
            self.assertEqual([chapter.title for chapter in deleted_manifest.chapters], ["Chapter 1", "Chapter 3"])
            self.assertFalse((project_dir / "renders").exists())
            self.assertFalse((project_dir / "samples").exists())


if __name__ == "__main__":
    unittest.main()
