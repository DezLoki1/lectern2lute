# lectern2lute

`lectern2lute` is a Windows-first Python CLI for turning DRM-free `PDF`, `EPUB`, `TXT`, and `MD` files into audiobook-ready chapter projects.

This first scaffold focuses on the parts that usually make or break quality:

- format-aware text extraction
- aggressive cleanup for narration
- automatic chapter detection
- inspectable per-chapter raw and cleaned text
- a render pipeline with pluggable local TTS backends

## Current status

The project already supports:

- ingesting supported input files into a reusable project folder
- cleaning and splitting text into chapters
- previewing raw or cleaned chapter text
- render planning and chapter export with a pluggable backend
- a built-in `kokoro` backend for local speech generation
- a built-in `indextts` backend for expressive, voice-cloned narration with IndexTTS-2.5 (NVIDIA GPU)
- a built-in `silence` backend for smoke testing the audio pipeline end to end
- a `command` backend for wiring other local TTS engines later
- a basic Windows GUI for source selection, chapter preview, voice selection, sample renders, and full conversion

## Project layout

After ingest, each book gets its own folder:

```text
projects/
  my-book/
    manifest.json
    chapters/
      001-chapter-1.raw.txt
      001-chapter-1.clean.txt
    renders/
      001-chapter-1/
        segment-001.txt
        segment-001.wav
        chapter.mp3
```

## Install

For real audiobook generation with Kokoro, use Python `3.11` or `3.12`. The official `kokoro` package currently declares support for Python `>=3.10,<3.13`.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e .[dev]
```

You also need `ffmpeg` available on `PATH` for chapter export.

### Kokoro setup

```powershell
py -m pip install -e .[kokoro]
```

On Windows, install `espeak-ng` as recommended by the official Kokoro docs before using the backend.

If `torch.cuda.is_available()` is `False` after install, you likely have a CPU-only PyTorch wheel. Replace it using the official PyTorch install selector for your CUDA version:

<https://pytorch.org/get-started/locally/>

## CLI

### Recommended flow

List the available Kokoro voices:

```powershell
lectern2lute voices
```

Create a project from a source file and render a short sample:

```powershell
lectern2lute convert .\books\example.pdf `
  --voice af_heart `
  --mode sample
```

If the sample sounds right, rerun the same command in full mode:

```powershell
lectern2lute convert .\books\example.pdf `
  --voice af_heart `
  --mode full
```

`convert` will ingest the source file automatically, reuse the same project on later runs, and store sample clips under `projects\<slug>\samples\`.

### Basic GUI

Launch the desktop app from the terminal:

```powershell
lectern2lute gui
```

Or use the dedicated launcher after reinstalling the editable package:

```powershell
py -m pip install -e .[kokoro]
lectern2lute-gui
```

The GUI lets you:

- choose a `PDF`, `EPUB`, `TXT`, or `MD` source file
- prepare and inspect the parsed project
- preview cleaned chapter text
- choose a Kokoro voice and speed
- render a short sample from the selected chapter
- run the full conversion once the sample sounds right
- export a finished project to a chapter-marked `M4B`

### Advanced commands

### Ingest a book manually

```powershell
lectern2lute ingest .\books\example.epub
```

### Inspect the generated project

```powershell
lectern2lute inspect .\projects\example
```

### Preview cleaned chapter text

```powershell
lectern2lute preview .\projects\example --chapter 1
```

### Smoke-test the audio pipeline

```powershell
lectern2lute render .\projects\example --backend silence
```

### Render with Kokoro

```powershell
lectern2lute render .\projects\example `
  --backend kokoro `
  --voice af_heart `
  --kokoro-lang-code a `
  --sample-rate 24000
```

The official Kokoro examples use `KPipeline(lang_code='a')` and voices such as `af_heart`. Make sure the language code matches the voice family you choose.

### Render with IndexTTS-2.5

IndexTTS-2.5 sounds more expressive than Kokoro but needs an NVIDIA GPU (about 6 GB of VRAM with BF16) and is much slower. It has no preset voices: it clones the narrator from a short reference clip.

IndexTTS pins its own versions of PyTorch and friends, so it lives in its own folder and environment. lectern2lute starts it as a background worker, loads the model once, and reuses it for every segment.

One-time setup, run next to your `lectern2lute` folder:

```powershell
py -m pip install -U uv
git clone https://github.com/index-tts/index-tts.git
cd index-tts
uv sync
uv tool install "huggingface-hub"
hf download IndexTeam/IndexTTS-2.5 --local-dir=checkpoints
uv run tools/gpu_check.py
```

Skip `--all-extras` on Windows; DeepSpeed is hard to install there and isn't needed. IndexTTS installs PyTorch built for CUDA 12.8, which RTX 50-series cards require.

If you put IndexTTS somewhere else, set `LECTERN2LUTE_INDEXTTS_DIR` or pass `--indextts-dir`.

Voices are audio clips. lectern2lute looks in two places, in this order:

- a `voices` folder inside `lectern2lute` for your own clips: a clean 5-15 second `.wav` of one speaker, named after the voice id you want (`voices\narrator.wav` becomes `--voice narrator`)
- `index-tts\examples`, which you can fill with the IndexTTS demo voices:

```powershell
cd index-tts
uv run python -c "from indextts.utils.examples_downloader import ensure_examples_available; ensure_examples_available()"
```

Only clone voices you have permission to use.

```powershell
lectern2lute voices --backend indextts
lectern2lute convert .\books\example.epub --backend indextts --voice narrator --mode sample
```

In the GUI, switch **Voice engine** to IndexTTS-2.5. The first sample takes a while because the model has to load. Worker output is logged to `lectern2lute-indextts.log` in your temp folder.

### Export a finished project to M4B

After the full chapter render is done, wrap the chapter MP3 files into a single `.m4b` audiobook with embedded chapter markers:

```powershell
lectern2lute export-m4b .\projects\example --author "John Doe" --narrator "af_heart"
```

By default, the export lands under `projects\<slug>\exports\<slug>.m4b` and writes a small sidecar JSON file with the export metadata.

### Filter voices by language

```powershell
lectern2lute voices --language "American English"
```

### Use an external local TTS command

The command template must produce a `.wav` file at `{output}` and can read the segment text from `{input}`.

```powershell
lectern2lute render .\projects\example `
  --backend command `
  --voice af_sky `
  --command-template "my-tts-cli --input {input} --output {output} --voice {voice}"
```

The placeholders are already shell-quoted for Windows paths, so the template should use them directly instead of wrapping them in extra quotes.

Available placeholders:

- `{input}`: segment text file path
- `{output}`: target wav path
- `{voice}`: requested voice id
- `{sample_rate}`: sample rate for the intermediate wav

## Next steps

- add pronunciation override dictionaries
- add IndexTTS emotion controls (emotion reference clips or per-passage emotion text)
- add OCR as an optional separate pipeline
- add a GUI shell on top of the same backend
