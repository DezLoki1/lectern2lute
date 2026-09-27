from __future__ import annotations

import ctypes
from pathlib import Path


class AudioPlayerError(RuntimeError):
    """Raised when GUI audio playback fails."""


class AudioPlayer:
    def play(self, path: Path) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class WindowsMciAudioPlayer(AudioPlayer):
    def __init__(self, alias: str = "lectern2lute") -> None:
        self.alias = alias
        self._send_string = ctypes.windll.winmm.mciSendStringW
        self._get_error = ctypes.windll.winmm.mciGetErrorStringW

    def play(self, path: Path) -> None:
        target = path.resolve()
        if not target.exists():
            raise AudioPlayerError(f"Audio file was not found: {target}")

        self.stop()
        quoted = str(target).replace('"', '""')
        self._send(f'open "{quoted}" alias {self.alias}')
        self._send(f"play {self.alias} from 0")

    def stop(self) -> None:
        for command in (f"stop {self.alias}", f"close {self.alias}"):
            try:
                self._send(command)
            except AudioPlayerError:
                continue

    def _send(self, command: str) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        error_code = self._send_string(command, buffer, len(buffer), 0)
        if error_code == 0:
            return buffer.value

        error_buffer = ctypes.create_unicode_buffer(512)
        if self._get_error(error_code, error_buffer, len(error_buffer)):
            message = error_buffer.value
        else:
            message = f"MCI error {error_code}"
        raise AudioPlayerError(message)


class SilentAudioPlayer(AudioPlayer):
    def play(self, path: Path) -> None:  # pragma: no cover - fallback only
        raise AudioPlayerError("Built-in audio playback is only available on Windows.")

    def stop(self) -> None:  # pragma: no cover - fallback only
        return


def build_audio_player() -> AudioPlayer:
    if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "winmm"):
        return WindowsMciAudioPlayer()
    return SilentAudioPlayer()
