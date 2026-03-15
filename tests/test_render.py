import tempfile
import unittest
from pathlib import Path

from book2audio.pipeline import ingest_book
from book2audio.render import render_project, render_sample
from book2audio.tts import build_backend


class RenderTests(unittest.TestCase):
    def test_render_creates_chapter_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify the render pipeline from ingest "
                "through cleanup and MP3 export using the built-in silence backend. "
                "It includes enough extra sentences to force the renderer to split a single "
                "chapter into multiple segments before ffmpeg stitches them back together. "
                "That gives us a Windows-safe regression test for concat path handling. "
                "The sample text keeps going for one more sentence so the chapter comfortably "
                "crosses the chosen max segment size.\n\n"
                "Chapter 2\n\nThis follow-up chapter gives ffmpeg something else to stitch "
                "so the render path exercises more than one chapter directory.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            manifest = render_project(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                max_segment_chars=120,
            )

            self.assertEqual(len(manifest.chapters), 2)
            self.assertTrue(manifest.chapters[0].audio_path)
            self.assertTrue((project_dir / manifest.chapters[0].audio_path).exists())

    def test_render_sample_creates_preview_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify the sample render path and should "
                "produce a small preview MP3 rather than a full chapter export.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            sample_path = render_sample(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                sample_chars=300,
            )

            self.assertTrue(sample_path.exists())


if __name__ == "__main__":
    unittest.main()
