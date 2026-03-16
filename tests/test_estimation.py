import tempfile
import unittest
from pathlib import Path

from book2audio.estimation import estimate_project_runtime
from book2audio.pipeline import ingest_book
from book2audio.render import render_sample
from book2audio.tts import build_backend


class EstimationTests(unittest.TestCase):
    def test_estimate_project_runtime_uses_matching_sample_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to calibrate the project runtime estimate against a generated sample.\n\n"
                "Chapter 2\n\nThis second chapter gives the estimate more total words to extrapolate from.",
                encoding="utf-8",
            )

            project_dir, manifest = ingest_book(source, tmp_path / "projects")
            render_sample(
                project_dir,
                build_backend("silence"),
                voice="af_heart",
                sample_rate=24000,
                sample_chars=300,
                sample_metadata={"voice": "af_heart", "speed": 1.0},
            )

            estimate = estimate_project_runtime(project_dir, manifest, voice="af_heart", speed=1.0)

            self.assertEqual(estimate.source, "sample")
            self.assertIn("sample-calibrated", estimate.label)

    def test_estimate_project_runtime_falls_back_when_speed_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to verify that sample calibration is ignored when the speed changes.",
                encoding="utf-8",
            )

            project_dir, manifest = ingest_book(source, tmp_path / "projects")
            render_sample(
                project_dir,
                build_backend("silence"),
                voice="af_heart",
                sample_rate=24000,
                sample_chars=300,
                sample_metadata={"voice": "af_heart", "speed": 1.0},
            )

            estimate = estimate_project_runtime(project_dir, manifest, voice="af_heart", speed=1.25)

            self.assertEqual(estimate.source, "word_count")
            self.assertNotIn("sample-calibrated", estimate.label)


if __name__ == "__main__":
    unittest.main()
