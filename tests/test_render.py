import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from book2audio.pipeline import ingest_book
from book2audio.project import load_manifest
from book2audio.render import (
    RenderCancelled,
    RenderController,
    RenderProgress,
    _concat_file_line,
    render_project,
    render_sample,
)
from book2audio.tts import build_backend
from book2audio.tts.base import SilenceBackend


class TaggedSilenceBackend(SilenceBackend):
    def __init__(self, tag: str) -> None:
        self.tag = tag

    def settings_tag(self) -> str:
        return self.tag


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
                sample_metadata={"voice": "default", "speed": 1.0},
            )

            self.assertTrue(sample_path.exists())
            self.assertTrue(sample_path.with_suffix(".json").exists())

    def test_render_project_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify progress callbacks during a full render. "
                "It includes enough text to create more than one segment for the silence backend path.\n\n"
                "Chapter 2\n\nThis chapter gives the render pipeline a second chapter to report progress against.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            updates: list[RenderProgress] = []

            render_project(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                max_segment_chars=80,
                progress_callback=updates.append,
            )

            self.assertTrue(updates)
            self.assertEqual(updates[-1].phase, "complete")
            self.assertEqual(updates[-1].percent, 100.0)
            self.assertTrue(any(item.phase == "segment_start" for item in updates))
            self.assertTrue(any(item.phase == "chapter_complete" for item in updates))

    def test_render_sample_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify sample progress callbacks in the render pipeline.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            updates: list[RenderProgress] = []

            render_sample(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                sample_chars=300,
                sample_metadata={"voice": "default", "speed": 1.0},
                progress_callback=updates.append,
            )

            self.assertTrue(updates)
            self.assertEqual(updates[-1].phase, "complete")
            self.assertEqual(updates[-1].percent, 100.0)
            self.assertEqual(updates[0].phase, "segment_start")

    def test_render_project_can_be_cancelled_between_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify cooperative cancellation in the render pipeline. "
                "It includes enough text to split into multiple render segments so a stop request can be honored "
                "between them without corrupting finished work.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            controller = RenderController()

            def on_progress(progress: RenderProgress) -> None:
                if progress.phase == "segment_complete" and progress.segment_index == 1:
                    controller.request_cancel()

            with self.assertRaises(RenderCancelled):
                render_project(
                    project_dir,
                    build_backend("silence"),
                    voice="default",
                    sample_rate=24000,
                    max_segment_chars=80,
                    progress_callback=on_progress,
                    controller=controller,
                )

            manifest = load_manifest(project_dir)
            self.assertIsNone(manifest.chapters[0].audio_path)
            self.assertFalse((project_dir / "renders" / "001-chapter-1" / "chapter.mp3").exists())

    def test_render_project_can_pause_and_resume_between_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify cooperative pause and resume in the render pipeline. "
                "It includes enough text to split into several render segments so the controller can pause "
                "the worker between safe boundaries before allowing it to continue.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            controller = RenderController()
            pause_once = threading.Event()

            def on_progress(progress: RenderProgress) -> None:
                if (
                    progress.phase == "segment_complete"
                    and progress.segment_index == 1
                    and not pause_once.is_set()
                ):
                    pause_once.set()
                    controller.request_pause()

                    def resume_later() -> None:
                        time.sleep(0.15)
                        controller.resume()

                    threading.Thread(target=resume_later, daemon=True).start()

            started = time.monotonic()
            manifest = render_project(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                max_segment_chars=80,
                progress_callback=on_progress,
                controller=controller,
            )
            elapsed = time.monotonic() - started

            self.assertTrue(pause_once.is_set())
            self.assertGreaterEqual(elapsed, 0.12)
            self.assertTrue(manifest.chapters[0].audio_path)
            self.assertTrue((project_dir / manifest.chapters[0].audio_path).exists())

    def test_render_sample_keeps_separate_files_per_backend_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nA short chapter used to check that changing speed makes a new sample.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            slow = render_sample(project_dir, TaggedSilenceBackend("1x"), voice="default", sample_rate=24000)
            fast = render_sample(project_dir, TaggedSilenceBackend("1.2x"), voice="default", sample_rate=24000)

            self.assertNotEqual(slow, fast)
            self.assertTrue(slow.exists())
            self.assertTrue(fast.exists())

    def test_concat_line_escapes_single_quotes(self) -> None:
        line = _concat_file_line(Path("/books/D'Angelo/segment-001.wav"))
        self.assertTrue(line.endswith("/books/D'\\''Angelo/segment-001.wav'"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not on PATH")
    def test_render_handles_apostrophe_in_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir) / "D'Angelo"
            tmp_path.mkdir()
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nFirst sentence of a chapter that is long enough to need two segments. "
                "Second sentence keeps it going past the segment limit so concat has work to do.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            manifest = render_project(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                max_segment_chars=300,
            )

            self.assertTrue((project_dir / manifest.chapters[0].audio_path).exists())


if __name__ == "__main__":
    unittest.main()
