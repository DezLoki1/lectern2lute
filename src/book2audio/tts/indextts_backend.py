from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import IO, Sequence

from book2audio.tts.base import TTSBackend, TTSBackendError
from book2audio.voices import find_indextts_voice, indextts_voice_dirs

APP_ROOT = Path(__file__).resolve().parents[3]
WORKER_SCRIPT = Path(__file__).resolve().with_name("indextts_worker.py")
LOG_PATH = Path(tempfile.gettempdir()) / "lectern2lute-indextts.log"


def default_indextts_dir() -> Path:
    """IndexTTS checkout: $LECTERN2LUTE_INDEXTTS_DIR, else an `index-tts` folder next to or inside the app."""
    configured = os.environ.get("LECTERN2LUTE_INDEXTTS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in (APP_ROOT.parent / "index-tts", APP_ROOT / "index-tts"):
        if candidate.is_dir():
            return candidate
    return APP_ROOT.parent / "index-tts"


def indextts_settings_tag(speed: float, lang: str = "EN") -> str:
    return f"{speed:g}x-{lang.lower()}"


def speed_to_duration_factor(speed: float) -> float:
    # IndexTTS-2.5 takes a duration multiplier (0.5-2.0); speed is its inverse.
    return min(2.0, max(0.5, 1.0 / speed))


class IndexTTSBackend(TTSBackend):
    """Runs IndexTTS-2.5 in its own environment through a long-lived worker process.

    The model loads once when the first segment is synthesized and stays in memory
    until close() is called or lectern2lute exits.
    """

    name = "indextts"

    def __init__(
        self,
        *,
        indextts_dir: Path | None = None,
        lang: str = "EN",
        speed: float = 1.0,
        use_bf16: bool = True,
        voice_dirs: Sequence[Path] | None = None,
        worker_command: Sequence[str] | None = None,
    ) -> None:
        self.indextts_dir = Path(indextts_dir) if indextts_dir else default_indextts_dir()
        self.lang = lang.upper()
        self.speed = speed
        self.use_bf16 = use_bf16
        self.voice_dirs = list(voice_dirs) if voice_dirs is not None else indextts_voice_dirs(self.indextts_dir)
        self._worker_command = list(worker_command) if worker_command else None
        self._process: subprocess.Popen[str] | None = None
        self._log_file: IO[str] | None = None

    def settings_tag(self) -> str:
        return indextts_settings_tag(self.speed, self.lang)

    def synthesize(
        self,
        text: str,
        input_path: Path,
        output_path: Path,
        *,
        voice: str,
        sample_rate: int,
    ) -> None:
        del input_path
        if not text.strip():
            raise TTSBackendError("IndexTTS cannot synthesize an empty segment.")
        if self._worker_command is None:
            self._check_install()

        voice_path = find_indextts_voice(voice, self.voice_dirs)
        if voice_path is None:
            searched = ", ".join(str(path) for path in self.voice_dirs) or "(no voice folders found)"
            raise TTSBackendError(
                f"IndexTTS voice '{voice}' was not found. IndexTTS clones a voice from a short audio clip: "
                f"put a clean 5-15 second .wav named {voice}.wav in one of: {searched}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        native_path = output_path.with_name(output_path.stem + ".native.wav")
        self._request(
            {
                "text": text,
                "voice_path": str(voice_path),
                "output_path": str(native_path.resolve()),
                "lang": self.lang,
                "duration_factor": speed_to_duration_factor(self.speed),
            }
        )
        _convert_sample_rate(native_path, output_path, sample_rate)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def __del__(self) -> None:  # pragma: no cover - interpreter shutdown ordering varies
        try:
            self.close()
        except Exception:
            pass

    def _request(self, payload: dict) -> None:
        process = self._ensure_worker()
        assert process.stdin is not None
        try:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
        except OSError as exc:
            self._fail("IndexTTS worker stopped unexpectedly.", exc)
        reply = self._read_reply(process)
        if not reply.get("ok"):
            raise TTSBackendError(f"IndexTTS synthesis failed: {reply.get('error', 'unknown error')}")

    def _ensure_worker(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self.close()

        command = self._worker_command or self._build_worker_command()
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(self.indextts_dir), env.get("PYTHONPATH", "")]))
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        self._log_file = LOG_PATH.open("a", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(self.indextts_dir) if self.indextts_dir.is_dir() else None,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log_file,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )
        except OSError as exc:
            self._fail("Could not start the IndexTTS worker.", exc)

        ready = self._read_reply(self._process)
        if not ready.get("ready"):
            self._fail(ready.get("error", "IndexTTS worker did not report ready."))
        return self._process

    def _check_install(self) -> None:
        if not (self.indextts_dir / "indextts").is_dir():
            raise TTSBackendError(
                f"IndexTTS was not found at {self.indextts_dir}. Clone https://github.com/index-tts/index-tts there "
                "(see the README's IndexTTS setup), or point LECTERN2LUTE_INDEXTTS_DIR / --indextts-dir at your copy."
            )
        if not (self.indextts_dir / "checkpoints" / "config.yaml").exists():
            raise TTSBackendError(
                f"IndexTTS-2.5 model files are missing from {self.indextts_dir / 'checkpoints'}. "
                "Download them with `hf download IndexTeam/IndexTTS-2.5 --local-dir=checkpoints` inside the IndexTTS folder."
            )

    def _build_worker_command(self) -> list[str]:
        self._check_install()

        worker_args = [str(WORKER_SCRIPT), "--model-dir", "checkpoints"]
        if not self.use_bf16:
            worker_args.append("--no-bf16")

        venv_python = self.indextts_dir / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if venv_python.exists():
            return [str(venv_python), *worker_args]
        uv = shutil.which("uv")
        if uv:
            return [uv, "run", "--project", str(self.indextts_dir), "python", *worker_args]
        raise TTSBackendError(
            f"No IndexTTS environment found in {self.indextts_dir}. Run `uv sync` inside that folder first."
        )

    def _read_reply(self, process: subprocess.Popen[str]) -> dict:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline()
            if not line:
                self._fail("IndexTTS worker exited unexpectedly.")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def _fail(self, message: str, cause: BaseException | None = None) -> None:
        self.close()
        details = _log_tail()
        suffix = f"\nLast lines of {LOG_PATH}:\n{details}" if details else f"\nSee {LOG_PATH} for details."
        raise TTSBackendError(message + suffix) from cause


def _convert_sample_rate(source: Path, target: Path, sample_rate: int) -> None:
    try:
        with wave.open(str(source), "rb") as wav_file:
            native_rate = wav_file.getframerate()
    except (OSError, wave.Error) as exc:
        raise TTSBackendError(f"IndexTTS wrote an unreadable wav file: {source}") from exc

    if native_rate == sample_rate:
        source.replace(target)
        return

    if shutil.which("ffmpeg") is None:
        raise TTSBackendError("ffmpeg is required on PATH to resample IndexTTS audio.")
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ar", str(sample_rate), "-ac", "1", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise TTSBackendError(f"ffmpeg failed while resampling IndexTTS audio:\n{result.stderr.strip()}")
    source.unlink(missing_ok=True)


def _log_tail(lines: int = 15) -> str:
    try:
        content = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])
