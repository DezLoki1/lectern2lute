import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from book2audio.voices import (
    build_fallback_voice_list,
    friendly_voice_label,
    get_voice_sample_path,
    list_kokoro_voices,
)


class VoiceTests(unittest.TestCase):
    def test_list_kokoro_voices_returns_sorted_records(self) -> None:
        fake_files = [
            "voices/zf_xiaobei.pt",
            "voices/af_heart.pt",
            "voices/am_michael.pt",
        ]

        with patch("huggingface_hub.list_repo_files", return_value=fake_files):
            voices = list_kokoro_voices()

        self.assertEqual([voice.voice for voice in voices], ["af_heart", "am_michael", "zf_xiaobei"])
        self.assertEqual(voices[0].language_code, "a")
        self.assertEqual(voices[2].language_code, "z")

    def test_build_fallback_voice_list_contains_default_voice(self) -> None:
        voices = build_fallback_voice_list()

        self.assertTrue(any(voice.voice == "af_heart" for voice in voices))
        self.assertTrue(any(voice.voice == "zf_xiaobei" for voice in voices))

    def test_friendly_voice_label_formats_name_and_language(self) -> None:
        voice = next(item for item in build_fallback_voice_list() if item.voice == "am_adam")

        self.assertEqual(friendly_voice_label(voice), "Adam (American English)")

    def test_get_voice_sample_path_returns_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_dir = root / "voice samples"
            sample_dir.mkdir()
            sample_path = sample_dir / "am_adam.mp3"
            sample_path.write_bytes(b"test")

            resolved = get_voice_sample_path("am_adam", root)

        self.assertEqual(resolved, sample_path)


if __name__ == "__main__":
    unittest.main()
