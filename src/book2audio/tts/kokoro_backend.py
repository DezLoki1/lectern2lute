from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from book2audio.tts.base import TTSBackend, TTSBackendError


class KokoroBackend(TTSBackend):
    name = "kokoro"
    output_sample_rate = 24000

    def __init__(
        self,
        *,
        lang_code: str = "a",
        speed: float = 1.0,
        split_pattern: str = r"\n+",
        device: str | None = None,
        repo_id: str = "hexgrad/Kokoro-82M",
    ) -> None:
        self.lang_code = lang_code
        self.speed = speed
        self.split_pattern = split_pattern
        self.device = device
        self.repo_id = repo_id
        self._pipeline: Any | None = None

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
        if sample_rate != self.output_sample_rate:
            raise TTSBackendError(
                f"Kokoro emits {self.output_sample_rate} Hz audio. Use --sample-rate {self.output_sample_rate}."
            )

        if not text.strip():
            raise TTSBackendError("Kokoro cannot synthesize an empty segment.")

        kokoro_module = self._import_dependency(
            "kokoro",
            "Install the Kokoro backend with `pip install -e .[kokoro]` in a Python 3.11 or 3.12 environment.",
        )
        torch_module = self._import_dependency(
            "torch",
            "Install torch in the active environment before using the Kokoro backend.",
        )
        numpy_module = self._import_dependency(
            "numpy",
            "Install numpy in the active environment before using the Kokoro backend.",
        )
        soundfile_module = self._import_dependency(
            "soundfile",
            "Install soundfile in the active environment before using the Kokoro backend.",
        )

        if self._pipeline is None:
            try:
                pipeline_device = self.device or ("cuda" if torch_module.cuda.is_available() else "cpu")
                self._pipeline = kokoro_module.KPipeline(
                    lang_code=self.lang_code,
                    repo_id=self.repo_id,
                    device=pipeline_device,
                )
            except Exception as exc:  # pragma: no cover - depends on local runtime setup
                raise TTSBackendError(
                    "Kokoro failed to initialize. On Windows, make sure espeak-ng is installed and on PATH."
                ) from exc

        try:
            generator = self._pipeline(
                text,
                voice=voice,
                speed=self.speed,
                split_pattern=self.split_pattern,
            )
            chunks = [
                self._normalize_audio_chunk(numpy_module, audio)
                for _, _, audio in generator
            ]
            chunks = [chunk for chunk in chunks if len(chunk) > 0]
        except Exception as exc:  # pragma: no cover - depends on runtime/model state
            raise TTSBackendError(f"Kokoro synthesis failed: {exc}") from exc

        if not chunks:
            raise TTSBackendError("Kokoro returned no audio for the requested segment.")

        combined = numpy_module.concatenate(chunks).astype("float32")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        soundfile_module.write(str(output_path), combined, self.output_sample_rate)

    @staticmethod
    def _import_dependency(module_name: str, install_hint: str) -> Any:
        try:
            return importlib.import_module(module_name)
        except ImportError as exc:
            raise TTSBackendError(install_hint) from exc

    @staticmethod
    def _normalize_audio_chunk(numpy_module: Any, audio: Any) -> Any:
        if hasattr(audio, "detach"):
            audio = audio.detach()
        if hasattr(audio, "cpu"):
            audio = audio.cpu()
        if hasattr(audio, "numpy"):
            audio = audio.numpy()
        return numpy_module.asarray(audio, dtype="float32").reshape(-1)
