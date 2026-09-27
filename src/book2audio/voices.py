from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class VoiceInfo:
    voice: str
    language_code: str
    language: str


CLONED_VOICE_LANGUAGE = "Cloned voice"

FALLBACK_KOKORO_VOICES: tuple[tuple[str, str], ...] = (
    ("af_alloy", "a"),
    ("af_aoede", "a"),
    ("af_bella", "a"),
    ("af_heart", "a"),
    ("af_jessica", "a"),
    ("af_kore", "a"),
    ("af_nicole", "a"),
    ("af_nova", "a"),
    ("af_river", "a"),
    ("af_sarah", "a"),
    ("af_sky", "a"),
    ("am_adam", "a"),
    ("am_echo", "a"),
    ("am_eric", "a"),
    ("am_fenrir", "a"),
    ("am_liam", "a"),
    ("am_michael", "a"),
    ("am_onyx", "a"),
    ("am_puck", "a"),
    ("am_santa", "a"),
    ("bf_alice", "b"),
    ("bf_emma", "b"),
    ("bf_isabella", "b"),
    ("bf_lily", "b"),
    ("bm_daniel", "b"),
    ("bm_fable", "b"),
    ("bm_george", "b"),
    ("bm_lewis", "b"),
    ("ef_dora", "e"),
    ("em_alex", "e"),
    ("em_santa", "e"),
    ("ff_siwis", "f"),
    ("hf_alpha", "h"),
    ("hf_beta", "h"),
    ("hm_omega", "h"),
    ("hm_psi", "h"),
    ("if_sara", "i"),
    ("im_nicola", "i"),
    ("jf_alpha", "j"),
    ("jf_gongitsune", "j"),
    ("jf_nezumi", "j"),
    ("jf_tebukuro", "j"),
    ("jm_kumo", "j"),
    ("pf_dora", "p"),
    ("pm_alex", "p"),
    ("pm_santa", "p"),
    ("zf_xiaobei", "z"),
    ("zf_xiaoni", "z"),
    ("zf_xiaoxiao", "z"),
    ("zf_xiaoyi", "z"),
    ("zm_yunjian", "z"),
    ("zm_yunxi", "z"),
    ("zm_yunxia", "z"),
    ("zm_yunyang", "z"),
)

FALLBACK_LANGUAGE_NAMES = {
    "a": "American English",
    "b": "British English",
    "e": "es",
    "f": "fr-fr",
    "h": "hi",
    "i": "it",
    "j": "Japanese",
    "p": "pt-br",
    "z": "Mandarin Chinese",
}


def build_fallback_voice_list() -> list[VoiceInfo]:
    return [
        VoiceInfo(
            voice=voice,
            language_code=language_code,
            language=FALLBACK_LANGUAGE_NAMES.get(language_code, language_code),
        )
        for voice, language_code in FALLBACK_KOKORO_VOICES
    ]


def humanize_voice_id(voice: str) -> str:
    if "_" not in voice:
        return voice.replace("-", " ").title()
    return voice.split("_", 1)[1].replace("_", " ").replace("-", " ").title()


def friendly_voice_label(voice_info: VoiceInfo) -> str:
    if voice_info.language == CLONED_VOICE_LANGUAGE:
        return f"{voice_info.voice.replace('_', ' ').replace('-', ' ').title()} ({voice_info.language})"
    return f"{humanize_voice_id(voice_info.voice)} ({voice_info.language})"


def get_voice_sample_path(voice: str, root: Path | None = None) -> Path | None:
    base_root = root or Path(__file__).resolve().parents[2]
    sample_path = base_root / "voice samples" / f"{voice}.mp3"
    if sample_path.exists():
        return sample_path
    return None


def list_kokoro_voices(repo_id: str = "hexgrad/Kokoro-82M") -> list[VoiceInfo]:
    try:
        from huggingface_hub import list_repo_files
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Kokoro voice discovery requires the Kokoro runtime. Install it with `pip install -e .[kokoro]`."
        ) from exc

    try:
        from kokoro.pipeline import LANG_CODES
    except ImportError:  # pragma: no cover - depends on optional install
        LANG_CODES = FALLBACK_LANGUAGE_NAMES

    try:
        files = list_repo_files(repo_id, repo_type="model")
        voices = sorted(
            file_path.split("/")[-1][:-3]
            for file_path in files
            if file_path.startswith("voices/") and file_path.endswith(".pt")
        )
    except Exception:  # pragma: no cover - network or hub issues
        return build_fallback_voice_list()

    return [
        VoiceInfo(
            voice=voice,
            language_code=voice[0],
            language=LANG_CODES.get(voice[0], voice[0]),
        )
        for voice in voices
    ]


INDEXTTS_VOICE_SUFFIXES = (".wav", ".mp3", ".flac")


def indextts_voice_dirs(indextts_dir: Path, app_root: Path | None = None) -> list[Path]:
    """Folders searched for IndexTTS reference clips: the app's `voices` folder first, then IndexTTS examples."""
    base_root = app_root or Path(__file__).resolve().parents[2]
    return [path for path in (base_root / "voices", Path(indextts_dir) / "examples") if path.is_dir()]


def _indextts_voice_files(voice_dirs: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for folder in voice_dirs:
        for path in sorted(folder.iterdir()):
            # IndexTTS ships emotion reference clips (emo_*.wav) beside its voices; they aren't narrators.
            if path.suffix.lower() not in INDEXTTS_VOICE_SUFFIXES or path.stem.startswith("emo_"):
                continue
            found.setdefault(path.stem, path)
    return found


def list_indextts_voices(voice_dirs: list[Path]) -> list[VoiceInfo]:
    return [
        VoiceInfo(voice=name, language_code="en", language=CLONED_VOICE_LANGUAGE)
        for name in sorted(_indextts_voice_files(voice_dirs))
    ]


def find_indextts_voice(voice: str, voice_dirs: list[Path]) -> Path | None:
    return _indextts_voice_files(voice_dirs).get(voice)
