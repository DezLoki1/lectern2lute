import json
import shutil
import sys
import tempfile
import textwrap
import unittest
import wave
from pathlib import Path

from book2audio.tts import TTSBackendError, build_backend
from book2audio.tts.indextts_backend import WORKER_SCRIPT, IndexTTSBackend, speed_to_duration_factor
from book2audio.voices import find_indextts_voice, friendly_voice_label, indextts_voice_dirs, list_indextts_voices

# Stands in for indextts_worker.py: same line protocol, but writes silence instead of loading the model.
FAKE_WORKER = textwrap.dedent(
    """
    import json, sys, wave
    log_path, mode = sys.argv[1], sys.argv[2]
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(json.dumps({"event": "start"}) + "\\n")
    if mode == "crash":
        sys.stderr.write("CUDA out of memory\\n")
        sys.exit(3)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(json.dumps({"event": "request", **request}) + "\\n")
        if mode == "fail":
            print(json.dumps({"ok": False, "error": "text too long"}), flush=True)
            continue
        print(">> noisy library output", flush=True)
        with wave.open(request["output_path"], "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(bytes(2205 * 2))
        print(json.dumps({"ok": True}), flush=True)
    """
)


class IndexTTSBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.worker_path = self.root / "fake_worker.py"
        self.worker_path.write_text(FAKE_WORKER, encoding="utf-8")
        self.log_path = self.root / "worker-log.jsonl"
        self.voices_dir = self.root / "voices"
        self.voices_dir.mkdir()
        (self.voices_dir / "narrator.wav").write_bytes(b"RIFF")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_backend(self, mode: str = "ok", **kwargs) -> IndexTTSBackend:
        backend = IndexTTSBackend(
            indextts_dir=self.root,
            voice_dirs=[self.voices_dir],
            worker_command=[sys.executable, str(self.worker_path), str(self.log_path), mode],
            **kwargs,
        )
        self.addCleanup(backend.close)
        return backend

    def log_events(self) -> list[dict]:
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def test_synthesize_sends_request_and_writes_wav(self) -> None:
        backend = self.make_backend(speed=1.25, lang="en")
        output_path = self.root / "out" / "segment-001.wav"

        backend.synthesize("Hello there.", self.root / "in.txt", output_path, voice="narrator", sample_rate=22050)

        with wave.open(str(output_path), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 22050)
        self.assertFalse(output_path.with_name("segment-001.native.wav").exists())
        request = self.log_events()[-1]
        self.assertEqual(request["text"], "Hello there.")
        self.assertEqual(request["voice_path"], str(self.voices_dir / "narrator.wav"))
        self.assertEqual(request["lang"], "EN")
        self.assertAlmostEqual(request["duration_factor"], 0.8)

    def test_worker_is_reused_between_segments(self) -> None:
        backend = self.make_backend()
        for index in (1, 2, 3):
            backend.synthesize(
                f"Segment {index}.", self.root / "in.txt", self.root / f"s{index}.wav", voice="narrator", sample_rate=22050
            )

        events = [event["event"] for event in self.log_events()]
        self.assertEqual(events.count("start"), 1)
        self.assertEqual(events.count("request"), 3)

    def test_unknown_voice_explains_reference_clips(self) -> None:
        backend = self.make_backend()
        with self.assertRaisesRegex(TTSBackendError, "missing.wav"):
            backend.synthesize("Hi.", self.root / "in.txt", self.root / "out.wav", voice="missing", sample_rate=22050)

    def test_worker_error_is_reported(self) -> None:
        backend = self.make_backend(mode="fail")
        with self.assertRaisesRegex(TTSBackendError, "text too long"):
            backend.synthesize("Hi.", self.root / "in.txt", self.root / "out.wav", voice="narrator", sample_rate=22050)

    def test_worker_crash_is_reported(self) -> None:
        backend = self.make_backend(mode="crash")
        with self.assertRaisesRegex(TTSBackendError, "exited unexpectedly"):
            backend.synthesize("Hi.", self.root / "in.txt", self.root / "out.wav", voice="narrator", sample_rate=22050)

    def test_real_worker_script_against_fake_indextts_package(self) -> None:
        package = self.root / "indextts"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "infer_v2_5.py").write_text(
            textwrap.dedent(
                """
                import wave

                class IndexTTS2:
                    def __init__(self, cfg_path, model_dir, use_bf16):
                        print(">> loading model from", model_dir)
                        self.use_bf16 = use_bf16

                    def infer(self, spk_audio_prompt, text, output_path, lang, duration_factor, verbose):
                        print(">> wav file saved to:", output_path)
                        with wave.open(output_path, "wb") as wav_file:
                            wav_file.setnchannels(1)
                            wav_file.setsampwidth(2)
                            wav_file.setframerate(22050)
                            wav_file.writeframes(bytes(441 * 2))
                """
            ),
            encoding="utf-8",
        )
        backend = IndexTTSBackend(
            indextts_dir=self.root,
            voice_dirs=[self.voices_dir],
            worker_command=[sys.executable, str(WORKER_SCRIPT), "--model-dir", str(self.root / "checkpoints")],
        )
        self.addCleanup(backend.close)
        output_path = self.root / "real.wav"

        backend.synthesize("Hello.", self.root / "in.txt", output_path, voice="narrator", sample_rate=22050)

        self.assertTrue(output_path.exists())

    @unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg is not installed")
    def test_output_is_resampled_to_requested_rate(self) -> None:
        backend = self.make_backend()
        output_path = self.root / "out.wav"
        backend.synthesize("Hi.", self.root / "in.txt", output_path, voice="narrator", sample_rate=24000)
        with wave.open(str(output_path), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 24000)

    def test_missing_install_gives_setup_hint(self) -> None:
        backend = build_backend("indextts", indextts_dir=self.root / "nowhere")
        with self.assertRaisesRegex(TTSBackendError, "IndexTTS was not found"):
            backend.synthesize("Hi.", self.root / "in.txt", self.root / "out.wav", voice="narrator", sample_rate=22050)

    def test_speed_maps_to_clamped_duration_factor(self) -> None:
        self.assertAlmostEqual(speed_to_duration_factor(1.0), 1.0)
        self.assertAlmostEqual(speed_to_duration_factor(2.0), 0.5)
        self.assertAlmostEqual(speed_to_duration_factor(0.25), 2.0)


class IndexTTSVoiceTests(unittest.TestCase):
    def test_voice_listing_skips_emotion_clips_and_prefers_app_voices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_voices = root / "app" / "voices"
            examples = root / "index-tts" / "examples"
            app_voices.mkdir(parents=True)
            examples.mkdir(parents=True)
            for path in (app_voices / "voice_01.wav", examples / "voice_01.wav", examples / "voice_02.wav"):
                path.write_bytes(b"RIFF")
            (examples / "emo_sad.wav").write_bytes(b"RIFF")
            (examples / "cases.jsonl").write_text("{}", encoding="utf-8")

            dirs = indextts_voice_dirs(root / "index-tts", app_root=root / "app")
            voices = list_indextts_voices(dirs)

            self.assertEqual([voice.voice for voice in voices], ["voice_01", "voice_02"])
            self.assertEqual(find_indextts_voice("voice_01", dirs), app_voices / "voice_01.wav")
            self.assertEqual(friendly_voice_label(voices[0]), "Voice 01 (Cloned voice)")


if __name__ == "__main__":
    unittest.main()
