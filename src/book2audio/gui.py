from __future__ import annotations

import os
import queue
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from book2audio.models import ChapterRecord, ProjectManifest
from book2audio.pipeline import ensure_project
from book2audio.project import load_manifest
from book2audio.render import render_project, render_sample
from book2audio.tts import build_backend
from book2audio.voices import VoiceInfo, list_kokoro_voices

SUPPORTED_FILE_TYPES = [
    ("Books", "*.pdf *.epub *.txt *.md"),
    ("PDF", "*.pdf"),
    ("EPUB", "*.epub"),
    ("Text", "*.txt"),
    ("Markdown", "*.md"),
    ("All files", "*.*"),
]


@dataclass(slots=True)
class RenderSettings:
    source_path: Path
    output_root: Path
    voice: str
    language_code: str
    speed: float
    sample_chars: int
    sample_chapter_index: int
    overwrite_audio: bool
    current_project_dir: Path | None = None
    current_project_source: Path | None = None


class Book2AudioGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("book2audio")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.option_add("*Font", "{Segoe UI} 10")

        self.source_var = tk.StringVar()
        self.output_root_var = tk.StringVar(value=str((Path.cwd() / "projects").resolve()))
        self.voice_var = tk.StringVar(value="af_heart")
        self.voice_language_var = tk.StringVar(value="American English")
        self.speed_var = tk.DoubleVar(value=1.0)
        self.sample_chars_var = tk.IntVar(value=650)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Select a source file, then prepare a project or render a sample.")
        self.project_title_var = tk.StringVar(value="No project loaded")
        self.project_path_var = tk.StringVar(value="-")
        self.project_format_var = tk.StringVar(value="-")
        self.project_parser_var = tk.StringVar(value="-")
        self.project_chapters_var = tk.StringVar(value="0")
        self.project_minutes_var = tk.StringVar(value="0.00")
        self.sample_chapter_var = tk.StringVar(value="Chapter 1")

        self.voice_lookup: dict[str, VoiceInfo] = {}
        self.project_dir: Path | None = None
        self.current_source_path: Path | None = None
        self.manifest: ProjectManifest | None = None
        self.chapter_records: list[ChapterRecord] = []
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False

        self._build_ui()
        self._set_controls_enabled(True)
        self._queue_log("Loading available voices...")
        self._start_task("Loading Kokoro voices...", self._load_voices_worker)
        self.root.after(150, self._poll_events)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Header.TLabel", font=("{Segoe UI}", 11, "bold"))

        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=0)
        main.rowconfigure(1, weight=1)
        main.rowconfigure(2, weight=0)

        left = ttk.Frame(main, width=360)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        source_frame = ttk.LabelFrame(left, text="Source", padding=12)
        source_frame.grid(row=0, column=0, sticky="ew")
        source_frame.columnconfigure(0, weight=1)

        ttk.Label(source_frame, text="Book file").grid(row=0, column=0, sticky="w")
        self.source_entry = ttk.Entry(source_frame, textvariable=self.source_var)
        self.source_entry.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        self.browse_source_button = ttk.Button(source_frame, text="Browse...", command=self._browse_source)
        self.browse_source_button.grid(row=1, column=1, padx=(8, 0), pady=(4, 8))

        ttk.Label(source_frame, text="Project output folder").grid(row=2, column=0, sticky="w")
        self.output_entry = ttk.Entry(source_frame, textvariable=self.output_root_var)
        self.output_entry.grid(row=3, column=0, sticky="ew", pady=(4, 8))
        self.browse_output_button = ttk.Button(source_frame, text="Browse...", command=self._browse_output_root)
        self.browse_output_button.grid(row=3, column=1, padx=(8, 0), pady=(4, 8))

        self.prepare_button = ttk.Button(source_frame, text="Prepare Project", command=self._prepare_project)
        self.prepare_button.grid(row=4, column=0, sticky="ew", pady=(4, 0))

        voice_frame = ttk.LabelFrame(left, text="Voice & Render", padding=12)
        voice_frame.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        voice_frame.columnconfigure(0, weight=1)
        voice_frame.columnconfigure(1, weight=1)

        ttk.Label(voice_frame, text="Narrator voice").grid(row=0, column=0, sticky="w")
        self.voice_combo = ttk.Combobox(voice_frame, textvariable=self.voice_var, state="normal", height=18)
        self.voice_combo.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        self.voice_combo.bind("<<ComboboxSelected>>", lambda _event: self._sync_voice_metadata())
        self.voice_combo.bind("<FocusOut>", lambda _event: self._sync_voice_metadata())
        self.refresh_voices_button = ttk.Button(voice_frame, text="Refresh", command=self._refresh_voices)
        self.refresh_voices_button.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(4, 8))

        ttk.Label(voice_frame, text="Language").grid(row=2, column=0, sticky="w")
        ttk.Label(voice_frame, textvariable=self.voice_language_var).grid(row=3, column=0, sticky="w")

        ttk.Label(voice_frame, text="Speed").grid(row=2, column=1, sticky="w")
        self.speed_spinbox = ttk.Spinbox(
            voice_frame,
            from_=0.5,
            to=2.0,
            increment=0.05,
            textvariable=self.speed_var,
            width=10,
        )
        self.speed_spinbox.grid(row=3, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(voice_frame, text="Sample length (chars)").grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.sample_chars_spinbox = ttk.Spinbox(
            voice_frame,
            from_=200,
            to=3000,
            increment=50,
            textvariable=self.sample_chars_var,
            width=10,
        )
        self.sample_chars_spinbox.grid(row=5, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(voice_frame, text="Sample chapter").grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(12, 0))
        ttk.Label(voice_frame, textvariable=self.sample_chapter_var).grid(row=5, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

        self.overwrite_check = ttk.Checkbutton(
            voice_frame,
            text="Overwrite existing sample/audio files",
            variable=self.overwrite_var,
        )
        self.overwrite_check.grid(row=6, column=0, columnspan=2, sticky="w", pady=(14, 0))

        self.render_sample_button = ttk.Button(voice_frame, text="Render Sample", command=self._render_sample)
        self.render_sample_button.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        self.render_full_button = ttk.Button(voice_frame, text="Full Conversion", command=self._render_full)
        self.render_full_button.grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(14, 0))

        self.open_project_button = ttk.Button(voice_frame, text="Open Project Folder", command=self._open_project_folder)
        self.open_project_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        project_frame = ttk.LabelFrame(left, text="Project", padding=12)
        project_frame.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        project_frame.columnconfigure(0, weight=1)
        project_frame.rowconfigure(6, weight=1)

        details = [
            ("Title", self.project_title_var),
            ("Path", self.project_path_var),
            ("Source Format", self.project_format_var),
            ("Parser", self.project_parser_var),
            ("Chapters", self.project_chapters_var),
            ("Estimated Minutes", self.project_minutes_var),
        ]
        for row_index, (label, value) in enumerate(details):
            ttk.Label(project_frame, text=label, style="Header.TLabel").grid(row=row_index * 2, column=0, sticky="w")
            ttk.Label(project_frame, textvariable=value, wraplength=320, justify="left").grid(
                row=row_index * 2 + 1,
                column=0,
                sticky="w",
                pady=(2, 8),
            )

        preview_container = ttk.Frame(main)
        preview_container.grid(row=0, column=1, rowspan=2, sticky="nsew")
        preview_container.columnconfigure(0, weight=1)
        preview_container.rowconfigure(1, weight=1)

        ttk.Label(preview_container, text="Chapter Preview", style="Header.TLabel").grid(row=0, column=0, sticky="w")

        preview_split = ttk.Panedwindow(preview_container, orient=tk.HORIZONTAL)
        preview_split.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        chapter_frame = ttk.Frame(preview_split, padding=(0, 0, 12, 0))
        chapter_frame.columnconfigure(0, weight=1)
        chapter_frame.rowconfigure(1, weight=1)
        ttk.Label(chapter_frame, text="Chapters").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.chapter_listbox = tk.Listbox(chapter_frame, exportselection=False, height=18)
        self.chapter_listbox.grid(row=1, column=0, sticky="nsew")
        self.chapter_listbox.bind("<<ListboxSelect>>", lambda _event: self._show_selected_chapter_preview())
        preview_split.add(chapter_frame, weight=1)

        text_frame = ttk.Frame(preview_split)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.preview_text = ScrolledText(text_frame, wrap=tk.WORD, height=24)
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        self.preview_text.configure(state="disabled")
        preview_split.add(text_frame, weight=3)

        log_frame = ttk.LabelFrame(main, text="Activity", padding=12)
        log_frame.grid(row=2, column=1, sticky="nsew", pady=(16, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(log_frame, wrap=tk.WORD, height=10)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        status_bar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        status_bar.grid(row=1, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(status_bar, textvariable=self.status_var)
        self.status_label.grid(row=0, column=0, sticky="w")

    def _browse_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select a source file",
            filetypes=SUPPORTED_FILE_TYPES,
            initialdir=str(Path.cwd()),
        )
        if not selected:
            return
        self.source_var.set(selected)
        self.status_var.set("Source file selected. Prepare the project or render a sample.")

    def _browse_output_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Select an output folder",
            initialdir=self.output_root_var.get() or str(Path.cwd()),
        )
        if selected:
            self.output_root_var.set(selected)

    def _refresh_voices(self) -> None:
        self._start_task("Refreshing Kokoro voices...", self._load_voices_worker)

    def _prepare_project(self) -> None:
        try:
            settings = self._collect_settings(require_voice=False)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        self._start_task(
            "Preparing project...",
            lambda: self._prepare_project_worker(settings),
        )

    def _render_sample(self) -> None:
        try:
            settings = self._collect_settings(require_voice=True)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        self._start_task(
            "Rendering sample...",
            lambda: self._render_sample_worker(settings),
        )

    def _render_full(self) -> None:
        try:
            settings = self._collect_settings(require_voice=True)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        self._start_task(
            "Rendering full conversion...",
            lambda: self._render_full_worker(settings),
        )

    def _collect_settings(self, *, require_voice: bool) -> RenderSettings:
        source_text = self.source_var.get().strip()
        if not source_text:
            raise ValueError("Choose a source file first.")

        source_path = Path(source_text).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("The selected source file does not exist.")

        output_text = self.output_root_var.get().strip()
        output_root = Path(output_text or "projects").expanduser().resolve()

        voice = self.voice_var.get().strip()
        if require_voice and not voice:
            raise ValueError("Choose a voice before rendering.")

        try:
            speed = float(self.speed_var.get())
        except (tk.TclError, ValueError) as exc:
            raise ValueError("Speed must be a number between 0.5 and 2.0.") from exc
        if speed < 0.5 or speed > 2.0:
            raise ValueError("Speed must be between 0.5 and 2.0.")

        try:
            sample_chars = int(self.sample_chars_var.get())
        except (tk.TclError, ValueError) as exc:
            raise ValueError("Sample length must be an integer between 200 and 3000.") from exc
        if sample_chars < 200 or sample_chars > 3000:
            raise ValueError("Sample length must be between 200 and 3000 characters.")

        voice_info = self.voice_lookup.get(voice)
        language_code = voice_info.language_code if voice_info else (voice[:1] or "a")

        return RenderSettings(
            source_path=source_path,
            output_root=output_root,
            voice=voice,
            language_code=language_code,
            speed=speed,
            sample_chars=sample_chars,
            sample_chapter_index=self._selected_chapter_index(),
            overwrite_audio=bool(self.overwrite_var.get()),
            current_project_dir=self.project_dir,
            current_project_source=self.current_source_path,
        )

    def _start_task(self, status_text: str, worker: Callable[[], None]) -> None:
        if self.busy:
            messagebox.showinfo("Busy", "A task is already running. Please wait for it to finish.", parent=self.root)
            return

        self.busy = True
        self.status_var.set(status_text)
        self._set_controls_enabled(False)
        self._queue_log(status_text)

        thread = threading.Thread(target=self._run_worker, args=(worker,), daemon=True)
        thread.start()

    def _run_worker(self, worker: Callable[[], None]) -> None:
        try:
            worker()
        except Exception as exc:  # pragma: no cover - exercised through manual GUI use
            self.events.put(("error", str(exc), traceback.format_exc()))
        finally:
            self.events.put(("idle", None))

    def _load_voices_worker(self) -> None:
        voices = list_kokoro_voices()
        self.events.put(("voices_loaded", voices))
        self.events.put(("log", f"Loaded {len(voices)} Kokoro voices."))

    def _prepare_project_worker(self, settings: RenderSettings) -> None:
        project_dir, manifest = self._resolve_project(settings, allow_reingest=settings.overwrite_audio)
        self.events.put(("project_ready", project_dir, manifest))
        self.events.put(("log", f"Prepared project: {project_dir}"))

    def _render_sample_worker(self, settings: RenderSettings) -> None:
        project_dir, _manifest = self._resolve_project(settings, allow_reingest=False)
        backend = build_backend(
            "kokoro",
            kokoro_lang_code=settings.language_code,
            kokoro_speed=settings.speed,
            kokoro_split_pattern=r"\n+",
        )
        sample_path = render_sample(
            project_dir,
            backend,
            voice=settings.voice,
            chapter_index=settings.sample_chapter_index,
            sample_chars=settings.sample_chars,
            sample_rate=24000,
            overwrite=settings.overwrite_audio,
        )
        updated_manifest = load_manifest(project_dir)
        self.events.put(("sample_done", project_dir, updated_manifest, sample_path))
        self.events.put(("log", f"Sample rendered: {sample_path}"))

    def _render_full_worker(self, settings: RenderSettings) -> None:
        project_dir, _manifest = self._resolve_project(settings, allow_reingest=False)
        backend = build_backend(
            "kokoro",
            kokoro_lang_code=settings.language_code,
            kokoro_speed=settings.speed,
            kokoro_split_pattern=r"\n+",
        )
        updated_manifest = render_project(
            project_dir,
            backend,
            voice=settings.voice,
            sample_rate=24000,
            overwrite=settings.overwrite_audio,
        )
        self.events.put(("full_done", project_dir, updated_manifest))
        self.events.put(("log", f"Full conversion complete: {project_dir}"))

    def _resolve_project(self, settings: RenderSettings, *, allow_reingest: bool) -> tuple[Path, ProjectManifest]:
        if (
            settings.current_project_dir is not None
            and settings.current_project_source is not None
            and settings.current_project_source == settings.source_path
            and settings.current_project_dir.exists()
        ):
            return settings.current_project_dir, load_manifest(settings.current_project_dir)
        return ensure_project(settings.source_path, settings.output_root, overwrite=allow_reingest)

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            kind = event[0]
            if kind == "voices_loaded":
                self._apply_voice_list(event[1])
            elif kind == "project_ready":
                self._apply_project(event[1], event[2])
                self.status_var.set("Project ready. Review a chapter preview or render a sample.")
            elif kind == "sample_done":
                self._apply_project(event[1], event[2])
                sample_path = event[3]
                self.status_var.set(f"Sample ready: {sample_path.name}")
                messagebox.showinfo(
                    "Sample Ready",
                    f"Sample created:\n{sample_path}",
                    parent=self.root,
                )
            elif kind == "full_done":
                self._apply_project(event[1], event[2])
                self.status_var.set("Full conversion finished.")
                messagebox.showinfo(
                    "Conversion Complete",
                    f"Finished rendering {len(event[2].chapters)} chapters.\n\nProject folder:\n{event[1]}",
                    parent=self.root,
                )
            elif kind == "log":
                self._queue_log(event[1])
            elif kind == "error":
                self.status_var.set("The last task failed. See the activity log for details.")
                self._queue_log(event[1])
                self._queue_log(event[2])
                messagebox.showerror("Task Failed", event[1], parent=self.root)
            elif kind == "idle":
                self.busy = False
                self._set_controls_enabled(True)

        self.root.after(150, self._poll_events)

    def _apply_voice_list(self, voices: list[VoiceInfo]) -> None:
        self.voice_lookup = {voice.voice: voice for voice in voices}
        self.voice_combo["values"] = [voice.voice for voice in voices]
        if self.voice_var.get() not in self.voice_lookup and voices:
            self.voice_var.set("af_heart" if "af_heart" in self.voice_lookup else voices[0].voice)
        self._sync_voice_metadata()

    def _sync_voice_metadata(self) -> None:
        voice = self.voice_var.get().strip()
        if voice in self.voice_lookup:
            self.voice_language_var.set(self.voice_lookup[voice].language)
            return
        prefix = voice[:1]
        fallback = next((item.language for item in self.voice_lookup.values() if item.language_code == prefix), None)
        self.voice_language_var.set(fallback or "-")

    def _apply_project(self, project_dir: Path, manifest: ProjectManifest) -> None:
        self.project_dir = project_dir
        self.current_source_path = Path(manifest.source_file).resolve()
        self.manifest = manifest
        self.chapter_records = list(manifest.chapters)

        self.project_title_var.set(manifest.title)
        self.project_path_var.set(str(project_dir))
        self.project_format_var.set(manifest.source_format)
        self.project_parser_var.set(manifest.parser_name)
        self.project_chapters_var.set(str(len(manifest.chapters)))
        self.project_minutes_var.set(f"{manifest.total_estimated_minutes:.2f}")

        self.chapter_listbox.delete(0, tk.END)
        for chapter in manifest.chapters:
            self.chapter_listbox.insert(
                tk.END,
                self._chapter_label(chapter),
            )

        if manifest.chapters:
            self.chapter_listbox.selection_clear(0, tk.END)
            self.chapter_listbox.selection_set(0)
            self.chapter_listbox.activate(0)
            self.sample_chapter_var.set(f"Chapter {manifest.chapters[0].index}")
            self._show_selected_chapter_preview()
        else:
            self.sample_chapter_var.set("Chapter 1")
            self._set_preview_text("No chapters were found in the project.")

    def _show_selected_chapter_preview(self) -> None:
        if self.project_dir is None or not self.chapter_records:
            self._set_preview_text("Prepare a project to inspect the cleaned chapter text.")
            self.sample_chapter_var.set("Chapter 1")
            return

        selection = self.chapter_listbox.curselection()
        chapter = self.chapter_records[selection[0]] if selection else self.chapter_records[0]
        self.sample_chapter_var.set(f"Chapter {chapter.index}")
        preview_path = self.project_dir / chapter.clean_text_path
        text = preview_path.read_text(encoding="utf-8").strip()
        clipped = text[:6000]
        if len(text) > 6000:
            clipped += "\n\n...[truncated]..."
        self._set_preview_text(clipped)

    def _selected_chapter_index(self) -> int:
        if not self.chapter_records:
            return 1
        selection = self.chapter_listbox.curselection()
        chapter = self.chapter_records[selection[0]] if selection else self.chapter_records[0]
        return chapter.index

    def _chapter_label(self, chapter: ChapterRecord) -> str:
        return f"{chapter.index:03d}  {chapter.title}  [{chapter.word_count} words | {chapter.estimated_minutes:.2f} min]"

    def _set_preview_text(self, text: str) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state="disabled")

    def _queue_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        widgets = [
            self.source_entry,
            self.output_entry,
            self.voice_combo,
            self.speed_spinbox,
            self.sample_chars_spinbox,
            self.browse_source_button,
            self.browse_output_button,
            self.prepare_button,
            self.refresh_voices_button,
            self.render_sample_button,
            self.render_full_button,
            self.open_project_button,
        ]
        for widget in widgets:
            widget.configure(state=state)
        self.overwrite_check.configure(state=state)

    def _open_project_folder(self) -> None:
        if self.project_dir is None:
            messagebox.showinfo("No Project", "Prepare a project first.", parent=self.root)
            return

        target = self.project_dir.resolve()
        try:
            os.startfile(target)  # type: ignore[attr-defined]
        except AttributeError:
            messagebox.showinfo("Project Folder", str(target), parent=self.root)


def main() -> None:
    root = tk.Tk()
    Book2AudioGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
