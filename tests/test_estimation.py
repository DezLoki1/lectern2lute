import tempfile
import unittest
from pathlib import Path

from book2audio.estimation import estimate_project_runtime
from book2audio.pipeline import ingest_book
from book2audio.render import render_sample
from book2audio.tts import build_backend
from book2audio.tts.base import SilenceBackend
from book2audio.tts.kokoro_backend import kokoro_settings_tag


class SpeedTaggedSilenceBackend(SilenceBackend):
    def __init__(self, speed: float) -> None:
        self.speed = speed

    def settings_tag(self) -> str:
        return kokoro_settings_tag(self.speed)


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

    def test_estimate_project_runtime_finds_speed_tagged_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter checks that samples named with a speed tag still calibrate the estimate.",
                encoding="utf-8",
            )

            project_dir, manifest = ingest_book(source, tmp_path / "projects")
            sample_path = render_sample(
                project_dir,
                SpeedTaggedSilenceBackend(1.2),
                voice="af_heart",
                sample_rate=24000,
                sample_chars=300,
                sample_metadata={"voice": "af_heart", "speed": 1.2},
            )

            estimate = estimate_project_runtime(project_dir, manifest, voice="af_heart", speed=1.2)

            self.assertTrue(sample_path.name.endswith("-af_heart-1.2x.mp3"))
            self.assertEqual(estimate.source, "sample")


if __name__ == "__main__":
    unittest.main()
