import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from book2audio.export import export_project_m4b
from book2audio.pipeline import ingest_book
from book2audio.render import render_project
from book2audio.tts import build_backend


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class ExportTests(unittest.TestCase):
    def test_export_project_m4b_creates_file_with_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify the M4B export path. "
                "It creates one rendered MP3 chapter before the export step.\n\n"
                "Chapter 2\n\nThis second chapter gives the exporter multiple chapter markers to write.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")
            render_project(
                project_dir,
                build_backend("silence"),
                voice="default",
                sample_rate=24000,
                max_segment_chars=120,
            )

            output_path = export_project_m4b(
                project_dir,
                author="John Example",
                narrator="Ada Reader",
            )

            self.assertTrue(output_path.exists())
            self.assertTrue(output_path.with_suffix(".json").exists())

            metadata_payload = json.loads(output_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(metadata_payload["chapter_count"], 2)
            self.assertEqual(metadata_payload["author"], "John Example")
            self.assertEqual(metadata_payload["narrator"], "Ada Reader")

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_chapters",
                    "-show_format",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            payload = json.loads(probe.stdout)
            self.assertEqual(len(payload.get("chapters", [])), 2)
            self.assertEqual(payload.get("format", {}).get("format_name"), "mov,mp4,m4a,3gp,3g2,mj2")

    def test_export_project_m4b_requires_rendered_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter has not been rendered yet.",
                encoding="utf-8",
            )

            project_dir, _ = ingest_book(source, tmp_path / "projects")

            with self.assertRaises(ValueError):
                export_project_m4b(project_dir)


if __name__ == "__main__":
    unittest.main()
