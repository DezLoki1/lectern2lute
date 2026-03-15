from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from book2audio.pipeline import ensure_project, ingest_book
from book2audio.project import load_manifest
from book2audio.render import render_project, render_sample
from book2audio.tts import TTSBackendError, build_backend
from book2audio.voices import list_kokoro_voices

app = typer.Typer(no_args_is_help=True, help="Local audiobook pipeline for DRM-free text sources.")
console = Console()


class ConvertMode(str, Enum):
    sample = "sample"
    full = "full"


@app.command()
def ingest(
    input_path: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True),
    output_root: Path = typer.Option(
        Path("projects"),
        "--output-root",
        "-o",
        help="Directory where project folders are created.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Reuse an existing project directory if the slug already exists.",
    ),
) -> None:
    project_dir, manifest = ingest_book(input_path, output_root, overwrite=overwrite)
    console.print(f"[bold green]Created project:[/bold green] {project_dir}")
    console.print(f"Title: {manifest.title}")
    console.print(f"Parser: {manifest.parser_name}")
    console.print(f"Chapters: {len(manifest.chapters)}")
    console.print(f"Estimated minutes: {manifest.total_estimated_minutes}")


@app.command()
def inspect(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
) -> None:
    manifest = load_manifest(project_dir)
    table = Table(title=f"{manifest.title} ({manifest.source_format})")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Words", justify="right")
    table.add_column("Minutes", justify="right")
    table.add_column("Audio")

    for chapter in manifest.chapters:
        table.add_row(
            str(chapter.index),
            chapter.title,
            str(chapter.word_count),
            f"{chapter.estimated_minutes:.2f}",
            chapter.audio_path or "-",
        )

    console.print(table)
    console.print(f"Source: {manifest.source_file}")
    console.print(f"Manifest: {project_dir / 'manifest.json'}")


@app.command()
def preview(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    chapter: int = typer.Option(1, "--chapter", "-c", min=1, help="Chapter index to preview."),
    raw: bool = typer.Option(False, "--raw", help="Preview the raw extracted chapter text."),
    max_chars: int = typer.Option(2500, "--max-chars", min=200),
) -> None:
    manifest = load_manifest(project_dir)
    selected = next((item for item in manifest.chapters if item.index == chapter), None)
    if selected is None:
        raise typer.BadParameter(f"Chapter {chapter} was not found in the manifest.")

    target_path = project_dir / (selected.raw_text_path if raw else selected.clean_text_path)
    text = target_path.read_text(encoding="utf-8").strip()
    clipped = text[:max_chars]
    if len(text) > max_chars:
        clipped += "\n\n...[truncated]..."
    console.print(f"[bold]{selected.title}[/bold]\n")
    console.print(clipped)


@app.command()
def render(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    backend: str = typer.Option("silence", "--backend", help="Render backend to use."),
    voice: str = typer.Option("default", "--voice", help="Voice id to pass to the backend."),
    kokoro_lang_code: str = typer.Option(
        "a",
        "--kokoro-lang-code",
        help="Kokoro language code. Official docs show a=American English, b=British English, e=Spanish, f=French and more.",
    ),
    kokoro_speed: float = typer.Option(
        1.0,
        "--kokoro-speed",
        min=0.5,
        max=2.0,
        help="Speech rate for the Kokoro backend.",
    ),
    kokoro_split_pattern: str = typer.Option(
        r"\n+",
        "--kokoro-split-pattern",
        help="Regex split pattern passed to Kokoro segmentation.",
    ),
    command_template: str | None = typer.Option(
        None,
        "--command-template",
        help="Template for --backend command. Must include {input} and {output}.",
    ),
    chapter: list[int] = typer.Option(
        [],
        "--chapter",
        "-c",
        help="Render only selected chapter indexes. Repeat the flag to render multiple chapters.",
    ),
    max_segment_chars: int = typer.Option(
        900,
        "--max-segment-chars",
        min=300,
        help="Maximum characters to pass to the backend in a single segment.",
    ),
    sample_rate: int = typer.Option(
        24000,
        "--sample-rate",
        min=8000,
        help="Intermediate wav sample rate passed to the backend.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Regenerate existing chapter MP3 files."),
) -> None:
    try:
        tts_backend = build_backend(
            backend,
            command_template=command_template,
            kokoro_lang_code=kokoro_lang_code,
            kokoro_speed=kokoro_speed,
            kokoro_split_pattern=kokoro_split_pattern,
        )
        manifest = render_project(
            project_dir,
            tts_backend,
            voice=voice,
            chapter_indexes=chapter or None,
            max_segment_chars=max_segment_chars,
            sample_rate=sample_rate,
            overwrite=overwrite,
        )
    except (RuntimeError, TTSBackendError, ValueError) as exc:
        console.print(f"[bold red]Render failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    rendered = [chapter.audio_path for chapter in manifest.chapters if chapter.audio_path]
    console.print(f"[bold green]Rendered chapters:[/bold green] {len(rendered)}")
    for audio_path in rendered:
        console.print(project_dir / audio_path)


@app.command("voices")
def voices(
    language: str | None = typer.Option(
        None,
        "--language",
        "-l",
        help="Optional language code filter, such as a, b, j, or z.",
    ),
) -> None:
    try:
        voice_list = list_kokoro_voices()
    except RuntimeError as exc:
        console.print(f"[bold red]Voice lookup failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Kokoro Voices")
    table.add_column("Voice")
    table.add_column("Lang")
    table.add_column("Language")

    for voice_info in voice_list:
        if language:
            query = language.strip().lower()
            if query not in {
                voice_info.language_code.lower(),
                voice_info.language.lower(),
                voice_info.voice.lower(),
            } and query not in voice_info.language.lower():
                continue
        table.add_row(voice_info.voice, voice_info.language_code, voice_info.language)

    console.print(table)


@app.command()
def gui() -> None:
    from book2audio.gui import main as gui_main

    gui_main()


@app.command()
def convert(
    source: Path = typer.Argument(..., exists=True, resolve_path=True),
    voice: str = typer.Option(..., "--voice", help="Voice id to use for sample or full rendering."),
    mode: ConvertMode = typer.Option(
        ConvertMode.sample,
        "--mode",
        help="Choose whether to render a quick sample or the full conversion.",
    ),
    output_root: Path = typer.Option(
        Path("projects"),
        "--output-root",
        "-o",
        help="Directory where project folders are created.",
    ),
    backend: str = typer.Option("kokoro", "--backend", help="Render backend to use."),
    chapter: int = typer.Option(
        1,
        "--chapter",
        "-c",
        min=1,
        help="Chapter index to sample. Ignored for full conversion unless repeated in the render command.",
    ),
    sample_chars: int = typer.Option(
        650,
        "--sample-chars",
        min=200,
        help="Approximate maximum characters to render in sample mode.",
    ),
    kokoro_lang_code: str = typer.Option(
        "a",
        "--kokoro-lang-code",
        help="Kokoro language code. Official docs show a=American English, b=British English, e=Spanish, f=French and more.",
    ),
    kokoro_speed: float = typer.Option(
        1.0,
        "--kokoro-speed",
        min=0.5,
        max=2.0,
        help="Speech rate for the Kokoro backend.",
    ),
    kokoro_split_pattern: str = typer.Option(
        r"\n+",
        "--kokoro-split-pattern",
        help="Regex split pattern passed to Kokoro segmentation.",
    ),
    command_template: str | None = typer.Option(
        None,
        "--command-template",
        help="Template for --backend command. Must include {input} and {output}.",
    ),
    sample_rate: int = typer.Option(
        24000,
        "--sample-rate",
        min=8000,
        help="Intermediate wav sample rate passed to the backend.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Regenerate existing sample or audio files, and reingest the source if needed.",
    ),
) -> None:
    if source.is_dir():
        if not (source / "manifest.json").exists():
            console.print("[bold red]Convert failed:[/bold red] directory does not contain a manifest.json file.")
            raise typer.Exit(code=1)
        project_dir = source
        manifest = load_manifest(project_dir)
    else:
        project_dir, manifest = ensure_project(source, output_root, overwrite=overwrite)

    try:
        tts_backend = build_backend(
            backend,
            command_template=command_template,
            kokoro_lang_code=kokoro_lang_code,
            kokoro_speed=kokoro_speed,
            kokoro_split_pattern=kokoro_split_pattern,
        )
        if mode is ConvertMode.sample:
            sample_path = render_sample(
                project_dir,
                tts_backend,
                voice=voice,
                chapter_index=chapter,
                sample_chars=sample_chars,
                sample_rate=sample_rate,
                overwrite=overwrite,
            )
            console.print(f"[bold green]Project:[/bold green] {project_dir}")
            console.print(f"[bold green]Sample:[/bold green] {sample_path}")
            console.print(
                "If the sample sounds good, rerun the same command with "
                "`--mode full` to render the whole book."
            )
            return

        manifest = render_project(
            project_dir,
            tts_backend,
            voice=voice,
            chapter_indexes=None,
            max_segment_chars=900,
            sample_rate=sample_rate,
            overwrite=overwrite,
        )
    except (RuntimeError, TTSBackendError, ValueError) as exc:
        console.print(f"[bold red]Convert failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold green]Project:[/bold green] {project_dir}")
    console.print(f"[bold green]Rendered chapters:[/bold green] {len(manifest.chapters)}")
    for chapter_record in manifest.chapters:
        if chapter_record.audio_path:
            console.print(project_dir / chapter_record.audio_path)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
