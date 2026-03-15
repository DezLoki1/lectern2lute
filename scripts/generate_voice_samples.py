from __future__ import annotations

import json
import subprocess
from pathlib import Path

from huggingface_hub import list_repo_files
from kokoro.pipeline import LANG_CODES

from book2audio.tts.kokoro_backend import KokoroBackend

REPO_ID = "hexgrad/Kokoro-82M"
OUTPUT_DIR = Path("voice samples")
INDEX_FILE = Path("voice samples.md")

SAMPLE_TEXTS = {
    "a": "Hello. This is a short American English narrator sample for the book to audio voice test.",
    "b": "Hello. This is a short British English narrator sample for the book to audio voice test.",
    "e": "Hola. Esta es una breve muestra de narracion en espanol para la prueba de voces.",
    "f": "Bonjour. Ceci est un court echantillon de narration francaise pour le test des voix.",
    "h": "\u0928\u092e\u0938\u094d\u0924\u0947\u0964 \u092f\u0939 \u0906\u0935\u093e\u091c\u093c \u092a\u0930\u0940\u0915\u094d\u0937\u0923 \u0915\u0947 \u0932\u093f\u090f \u0939\u093f\u0928\u094d\u0926\u0940 \u0915\u0925\u0928 \u0915\u093e \u090f\u0915 \u091b\u094b\u091f\u093e \u0928\u092e\u0942\u0928\u093e \u0939\u0948\u0964",
    "i": "Ciao. Questo e un breve campione di narrazione italiana per il test delle voci.",
    "j": "\u3053\u3093\u306b\u3061\u306f\u3002\u3053\u308c\u306f\u97f3\u58f0\u30c6\u30b9\u30c8\u7528\u306e\u77ed\u3044\u65e5\u672c\u8a9e\u30ca\u30ec\u30fc\u30b7\u30e7\u30f3\u30b5\u30f3\u30d7\u30eb\u3067\u3059\u3002",
    "p": "Ola. Esta e uma breve amostra de narracao em portugues para o teste de vozes.",
    "z": "\u4f60\u597d\u3002\u8fd9\u662f\u4e00\u6bb5\u7528\u4e8e\u8bed\u97f3\u6d4b\u8bd5\u7684\u7b80\u77ed\u4e2d\u6587\u65c1\u767d\u793a\u4f8b\u3002",
}


def list_voices(repo_id: str) -> list[str]:
    files = list_repo_files(repo_id, repo_type="model")
    return sorted(
        file_path.split("/")[-1][:-3]
        for file_path in files
        if file_path.startswith("voices/") and file_path.endswith(".pt")
    )


def render_voice_samples() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    voices = list_voices(REPO_ID)
    backends: dict[str, KokoroBackend] = {}
    records: list[dict[str, str]] = []

    for index, voice in enumerate(voices, start=1):
        lang_code = voice[0]
        sample_text = SAMPLE_TEXTS[lang_code]
        language = LANG_CODES[lang_code]
        backend = backends.get(lang_code)
        if backend is None:
            backend = KokoroBackend(lang_code=lang_code, repo_id=REPO_ID)
            backends[lang_code] = backend

        wav_path = OUTPUT_DIR / f"{voice}.wav"
        mp3_path = OUTPUT_DIR / f"{voice}.mp3"
        text_path = OUTPUT_DIR / f"{voice}.txt"
        text_path.write_text(sample_text + "\n", encoding="utf-8")

        if mp3_path.exists():
            print(f"[{index}/{len(voices)}] Skipping {voice} ({language})")
        else:
            print(f"[{index}/{len(voices)}] Rendering {voice} ({language})")
            backend.synthesize(
                sample_text,
                text_path,
                wav_path,
                voice=voice,
                sample_rate=24000,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    str(mp3_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            wav_path.unlink(missing_ok=True)

        records.append(
            {
                "voice": voice,
                "language_code": lang_code,
                "language": language,
                "sample_text": sample_text,
                "mp3": mp3_path.as_posix(),
                "text": text_path.as_posix(),
            }
        )

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    write_index(records)


def write_index(records: list[dict[str, str]]) -> None:
    lines = [
        "# Voice Samples",
        "",
        f"Generated from `{REPO_ID}`.",
        "",
        "Each sample uses a short language-matched line and renders to an MP3 file in the `voice samples/` folder.",
        "",
    ]

    current_language_code = None
    for record in records:
        if record["language_code"] != current_language_code:
            current_language_code = record["language_code"]
            lines.append(f"## {record['language']}")
            lines.append("")

        mp3_path = record["mp3"].replace(" ", "%20")
        text_path = record["text"].replace(" ", "%20")
        lines.append(f"- `{record['voice']}`: [{record['voice']}.mp3]({mp3_path})")
        lines.append(f"  Sample text: [{record['voice']}.txt]({text_path})")
        lines.append("")

    INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    render_voice_samples()
