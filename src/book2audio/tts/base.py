from __future__ import annotations

import subprocess
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from book2audio.utils import word_count


class TTSBackendError(RuntimeError):
    pass


class TTSBackend(ABC):
    name: str

    @abstractmethod
    def synthesize(
        self,
        text: str,
        input_path: Path,
        output_path: Path,
        *,
        voice: str,
        sample_rate: int,
    ) -> None:
        raise NotImplementedError


class SilenceBackend(TTSBackend):
    name = "silence"

    def synthesize(
        self,
        text: str,
        input_path: Path,
        output_path: Path,
        *,
        voice: str,
        sample_rate: int,
    ) -> None:
        del input_path, voice
        duration_seconds = max(0.35, word_count(text) * 0.35)
        total_frames = int(sample_rate * duration_seconds)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(total_frames * 2))


class CommandTTSBackend(TTSBackend):
    name = "command"

    def __init__(self, command_template: str) -> None:
        if "{input}" not in command_template or "{output}" not in command_template:
            raise TTSBackendError(
                "The command template must include both {input} and {output} placeholders."
            )
        self.command_template = command_template

    def synthesize(
        self,
        text: str,
        input_path: Path,
        output_path: Path,
        *,
        voice: str,
        sample_rate: int,
    ) -> None:
        del text
        output_path.parent.mkdir(parents=True, exist_ok=True)
        formatted = self.command_template.format(
            input=subprocess.list2cmdline([str(input_path)]),
            output=subprocess.list2cmdline([str(output_path)]),
            voice=subprocess.list2cmdline([voice]),
            sample_rate=sample_rate,
        )
        result = subprocess.run(
            formatted,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise TTSBackendError(
                f"External TTS command failed with exit code {result.returncode}:\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        if not output_path.exists():
            raise TTSBackendError(
                "External TTS command completed but did not create the expected output wav file."
            )


def build_backend(
    name: str,
    command_template: str | None = None,
    *,
    kokoro_lang_code: str = "a",
    kokoro_speed: float = 1.0,
    kokoro_split_pattern: str = r"\n+",
) -> TTSBackend:
    normalized = name.strip().lower()
    if normalized == "silence":
        return SilenceBackend()
    if normalized == "command":
        if not command_template:
            raise TTSBackendError("--command-template is required when --backend command is used.")
        return CommandTTSBackend(command_template=command_template)
    if normalized == "kokoro":
        from book2audio.tts.kokoro_backend import KokoroBackend

        return KokoroBackend(
            lang_code=kokoro_lang_code,
            speed=kokoro_speed,
            split_pattern=kokoro_split_pattern,
        )
    raise TTSBackendError(f"Unsupported backend: {name}")
