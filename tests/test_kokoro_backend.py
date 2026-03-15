import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from book2audio.tts import TTSBackendError, build_backend


class FakeArray(list):
    def astype(self, _dtype: str):
        return self

    def reshape(self, _shape: int):
        return self


class FakeNumpyModule:
    @staticmethod
    def asarray(audio, dtype: str = "float32"):
        del dtype
        return FakeArray(audio)

    @staticmethod
    def concatenate(chunks):
        combined = FakeArray()
        for chunk in chunks:
            combined.extend(chunk)
        return combined


class FakeSoundfileModule:
    @staticmethod
    def write(path: str, audio, sample_rate: int) -> None:
        Path(path).write_text(f"{sample_rate}:{len(audio)}", encoding="utf-8")


class FakeTorchModule:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return True


class FakePipeline:
    def __init__(self, lang_code: str, repo_id: str | None = None, device: str | None = None) -> None:
        self.lang_code = lang_code
        self.repo_id = repo_id
        self.device = device

    def __call__(self, text: str, *, voice: str, speed: float, split_pattern: str):
        del text, voice, speed, split_pattern
        yield ("hello", "hello", [0.1, 0.2, 0.3])
        yield ("world", "world", [0.4, 0.5])


class KokoroBackendTests(unittest.TestCase):
    def test_kokoro_backend_writes_audio_file(self) -> None:
        fake_modules = {
            "kokoro": types.SimpleNamespace(KPipeline=FakePipeline),
            "numpy": FakeNumpyModule(),
            "soundfile": FakeSoundfileModule(),
            "torch": FakeTorchModule(),
        }

        def fake_import(name: str):
            return fake_modules[name]

        backend = build_backend(
            "kokoro",
            kokoro_lang_code="a",
            kokoro_speed=1.1,
            kokoro_split_pattern=r"\n+",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "segment.wav"
            with patch("importlib.import_module", side_effect=fake_import):
                backend.synthesize(
                    "Hello world",
                    Path(temp_dir) / "segment.txt",
                    output_path,
                    voice="af_heart",
                    sample_rate=24000,
                )

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.read_text(encoding="utf-8"), "24000:5")

    def test_kokoro_backend_requires_24khz(self) -> None:
        backend = build_backend("kokoro")

        with self.assertRaises(TTSBackendError):
            backend.synthesize(
                "Hello world",
                Path("segment.txt"),
                Path("segment.wav"),
                voice="af_heart",
                sample_rate=22050,
            )


if __name__ == "__main__":
    unittest.main()
