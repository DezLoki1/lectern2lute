from __future__ import annotations

import os
import queue
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from book2audio.audio import AudioPlayerError, build_audio_player
from book2audio.estimation import estimate_project_runtime
from book2audio.models import ChapterRecord, ProjectManifest
from book2audio.pipeline import ensure_project
from book2audio.project import (
    delete_chapter,
    load_manifest,
    merge_chapters,
    rename_chapter_title,
    split_chapter,
    update_chapter_clean_text,
)
from book2audio.render import RenderProgress, render_project, render_sample
from book2audio.tts import build_backend
from book2audio.voices import (
    VoiceInfo,
    friendly_voice_label,
    get_voice_sample_path,
    list_kokoro_voices,
)

APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = APP_ROOT / "projects"
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
    selected_chapter_index: int
    overwrite_audio: bool
    current_project_dir: Path | None = None
    current_project_source: Path | None = None
    force_rebuild: bool = False


class Book2AudioGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("lectern2lute")
        self.root.geometry("1380x860")
        self.root.minsize(1080, 700)
        self.root.option_add("*Font", "{Segoe UI} 10")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.audio_player = build_audio_player()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self.editor_dirty = False
        self.ignore_editor_modified = False
        self.suspend_selection_events = False
        self.active_chapter_index: int | None = None
        self.last_sample_path: Path | None = None
        self.task_started_at: float | None = None

        self.source_var = tk.StringVar()
        self.output_root_var = tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT))
        self.voice_display_var = tk.StringVar()
        self.voice_id_var = tk.StringVar(value="af_heart")
        self.voice_language_var = tk.StringVar(value="-")
        self.voice_preview_var = tk.StringVar(value="Built-in preview: checking...")
        self.speed_var = tk.DoubleVar(value=1.0)
        self.sample_chars_var = tk.IntVar(value=650)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.workflow_var = tk.StringVar(
            value="1. Choose a book.  2. Prepare or rebuild the project.  3. Pick a voice.  "
            "4. Generate a sample from the selected chapter.  5. Convert the full book."
        )
        self.status_var = tk.StringVar(value="Choose a source file, then prepare the project.")
        self.editor_state_var = tk.StringVar(value="Cleaned chapter text will appear here and can be edited.")
        self.project_title_var = tk.StringVar(value="No project loaded")
        self.project_path_var = tk.StringVar(value="-")
        self.project_format_var = tk.StringVar(value="-")
        self.project_parser_var = tk.StringVar(value="-")
        self.project_chapters_var = tk.StringVar(value="0")
        self.project_minutes_var = tk.StringVar(value="0.00")
        self.sample_chapter_var = tk.StringVar(value="Selected chapter for samples: not loaded yet")
        self.last_sample_var = tk.StringVar(value="No generated sample yet")
        self.progress_value_var = tk.DoubleVar(value=0.0)
        self.progress_detail_var = tk.StringVar(value="Idle")

        self.project_dir: Path | None = None
        self.current_source_path: Path | None = None
        self.manifest: ProjectManifest | None = None
        self.chapter_records: list[ChapterRecord] = []
        self.voice_lookup: dict[str, VoiceInfo] = {}
        self.voice_label_to_id: dict[str, str] = {}
        self.voice_id_to_label: dict[str, str] = {}

        self._build_ui()
        self.speed_var.trace_add("write", self._on_estimation_inputs_changed)
        self.voice_display_var.trace_add("write", self._on_estimation_inputs_changed)
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
        main.rowconfigure(1, weight=1)
        main.rowconfigure(2, weight=0)

        action_frame = ttk.LabelFrame(main, text="Workflow", padding=12)
        action_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        for column in range(3):
            action_frame.columnconfigure(column, weight=1)

        ttk.Label(
            action_frame,
            textvariable=self.workflow_var,
            wraplength=1220,
            justify="left",
            style="Header.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            action_frame,
            textvariable=self.sample_chapter_var,
            wraplength=1220,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self.prepare_button = ttk.Button(action_frame, text="Prepare Project", command=self._prepare_project)
        self.prepare_button.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.rebuild_button = ttk.Button(action_frame, text="Rebuild Project", command=self._rebuild_project)
        self.rebuild_button.grid(row=2, column=1, sticky="ew", padx=8, pady=(12, 0))
        self.render_sample_button = ttk.Button(action_frame, text="Generate Sample", command=self._render_sample)
        self.render_sample_button.grid(row=2, column=2, sticky="ew", pady=(12, 0))

        self.render_chapter_button = ttk.Button(
            action_frame,
            text="Render Selected Chapter",
            command=self._render_selected_chapter,
        )
        self.render_chapter_button.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.render_full_button = ttk.Button(action_frame, text="Convert Full Book", command=self._render_full)
        self.render_full_button.grid(row=3, column=1, sticky="ew", padx=8, pady=(8, 0))
        self.open_project_button = ttk.Button(action_frame, text="Open Project Folder", command=self._open_project_folder)
        self.open_project_button.grid(row=3, column=2, sticky="ew", pady=(8, 0))

        left_container = ttk.Frame(main, width=390)
        left_container.grid(row=1, column=0, sticky="nsew", padx=(0, 16))
        left_container.columnconfigure(0, weight=1)
        left_container.rowconfigure(0, weight=1)

        self.left_scroll_canvas = tk.Canvas(left_container, highlightthickness=0, borderwidth=0)
        self.left_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.left_scrollbar = ttk.Scrollbar(left_container, orient=tk.VERTICAL, command=self.left_scroll_canvas.yview)
        self.left_scrollbar.grid(row=0, column=1, sticky="ns")
        self.left_scroll_canvas.configure(yscrollcommand=self.left_scrollbar.set)

        left = ttk.Frame(self.left_scroll_canvas, width=390)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        self.left_scroll_window = self.left_scroll_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", self._sync_left_scrollregion)
        self.left_scroll_canvas.bind("<Configure>", self._sync_left_canvas_width)
        self.left_scroll_canvas.bind("<Enter>", self._bind_left_mousewheel)
        self.left_scroll_canvas.bind("<Leave>", self._unbind_left_mousewheel)
        left.bind("<Enter>", self._bind_left_mousewheel)
        left.bind("<Leave>", self._unbind_left_mousewheel)

        source_frame = ttk.LabelFrame(left, text="Book & Output", padding=12)
        source_frame.grid(row=0, column=0, sticky="ew")
        source_frame.columnconfigure(0, weight=1)

        ttk.Label(
            source_frame,
            text="Choose a source file and the folder where the prepared project should live.",
            wraplength=350,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(source_frame, text="Book file").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.source_entry = ttk.Entry(source_frame, textvariable=self.source_var)
        self.source_entry.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        self.browse_source_button = ttk.Button(source_frame, text="Browse...", command=self._browse_source)
        self.browse_source_button.grid(row=2, column=1, padx=(8, 0), pady=(4, 8))

        ttk.Label(source_frame, text="Project output folder").grid(row=3, column=0, sticky="w")
        self.output_entry = ttk.Entry(source_frame, textvariable=self.output_root_var)
        self.output_entry.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.browse_output_button = ttk.Button(source_frame, text="Browse...", command=self._browse_output_root)
        self.browse_output_button.grid(row=4, column=1, padx=(8, 0), pady=(4, 0))

        voice_frame = ttk.LabelFrame(left, text="Voice & Samples", padding=12)
        voice_frame.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        voice_frame.columnconfigure(0, weight=1)
        voice_frame.columnconfigure(1, weight=1)

        ttk.Label(
            voice_frame,
            text="Pick the narrator voice, tune the speed, and preview either the built-in voice sample or your generated sample.",
            wraplength=350,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(voice_frame, text="Narrator voice").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.voice_combo = ttk.Combobox(
            voice_frame,
            textvariable=self.voice_display_var,
            state="readonly",
            height=18,
        )
        self.voice_combo.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_selected)
        self.refresh_voices_button = ttk.Button(voice_frame, text="Refresh", command=self._refresh_voices)
        self.refresh_voices_button.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(4, 8))

        ttk.Label(voice_frame, text="Voice ID").grid(row=3, column=0, sticky="w")
        ttk.Label(voice_frame, textvariable=self.voice_id_var).grid(row=4, column=0, sticky="w")

        ttk.Label(voice_frame, text="Language").grid(row=3, column=1, sticky="w", padx=(8, 0))
        ttk.Label(voice_frame, textvariable=self.voice_language_var).grid(row=4, column=1, sticky="w", padx=(8, 0))

        ttk.Label(voice_frame, textvariable=self.voice_preview_var, wraplength=340, justify="left").grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(10, 0),
        )

        ttk.Label(voice_frame, text="Speed").grid(row=6, column=0, sticky="w", pady=(12, 0))
        self.speed_spinbox = ttk.Spinbox(
            voice_frame,
            from_=0.5,
            to=2.0,
            increment=0.05,
            textvariable=self.speed_var,
            width=10,
        )
        self.speed_spinbox.grid(row=7, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(voice_frame, text="Sample length (chars)").grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(12, 0))
        self.sample_chars_spinbox = ttk.Spinbox(
            voice_frame,
            from_=200,
            to=3000,
            increment=50,
            textvariable=self.sample_chars_var,
            width=10,
        )
        self.sample_chars_spinbox.grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(4, 0))

        ttk.Label(voice_frame, text="Last sample").grid(row=8, column=0, sticky="w", pady=(12, 0))
        ttk.Label(voice_frame, textvariable=self.last_sample_var, wraplength=340, justify="left").grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(4, 0),
        )

        self.play_voice_button = ttk.Button(voice_frame, text="Play Voice Preview", command=self._play_voice_preview)
        self.play_voice_button.grid(row=10, column=0, sticky="ew", pady=(12, 0))
        self.play_sample_button = ttk.Button(voice_frame, text="Play Last Sample", command=self._play_last_sample)
        self.play_sample_button.grid(row=10, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))

        self.stop_audio_button = ttk.Button(voice_frame, text="Stop Audio", command=self._stop_audio)
        self.stop_audio_button.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        project_frame = ttk.LabelFrame(left, text="Project Snapshot", padding=12)
        project_frame.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        project_frame.columnconfigure(0, weight=1)

        self.overwrite_check = ttk.Checkbutton(
            project_frame,
            text="Overwrite existing chapter/full audio files",
            variable=self.overwrite_var,
        )
        self.overwrite_check.grid(row=0, column=0, sticky="w")

        details = [
            ("Title", self.project_title_var),
            ("Path", self.project_path_var),
            ("Source Format", self.project_format_var),
            ("Parser", self.project_parser_var),
            ("Chapters", self.project_chapters_var),
            ("Estimated Runtime", self.project_minutes_var),
        ]
        for row_index, (label, value) in enumerate(details):
            offset = 1
            ttk.Label(project_frame, text=label, style="Header.TLabel").grid(
                row=offset + row_index * 2,
                column=0,
                sticky="w",
                pady=(10 if row_index == 0 else 0, 0),
            )
            ttk.Label(project_frame, textvariable=value, wraplength=350, justify="left").grid(
                row=offset + row_index * 2 + 1,
                column=0,
                sticky="w",
                pady=(2, 8),
            )

        right = ttk.Frame(main)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        editor_header = ttk.Frame(right)
        editor_header.grid(row=0, column=0, sticky="ew")
        editor_header.columnconfigure(0, weight=1)

        ttk.Label(editor_header, text="Review Chapters & Edit Text", style="Header.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Label(editor_header, textvariable=self.editor_state_var, wraplength=760, justify="left").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 0),
        )

        editor_toolbar = ttk.Frame(right)
        editor_toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for column in range(4):
            editor_toolbar.columnconfigure(column, weight=1)
        self.save_edits_button = ttk.Button(editor_toolbar, text="Save Edits", command=self._save_current_chapter)
        self.save_edits_button.grid(row=0, column=0, sticky="ew")
        self.revert_edits_button = ttk.Button(editor_toolbar, text="Revert Chapter", command=self._revert_current_chapter)
        self.revert_edits_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.rename_title_button = ttk.Button(editor_toolbar, text="Rename Title", command=self._rename_current_chapter)
        self.rename_title_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self.split_chapter_button = ttk.Button(editor_toolbar, text="Split at Cursor", command=self._split_current_chapter)
        self.split_chapter_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        self.merge_up_button = ttk.Button(editor_toolbar, text="Merge Up", command=self._merge_with_previous)
        self.merge_up_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.merge_down_button = ttk.Button(editor_toolbar, text="Merge Down", command=self._merge_with_next)
        self.merge_down_button.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.delete_chapter_button = ttk.Button(
            editor_toolbar,
            text="Delete Chapter",
            command=self._delete_current_chapter,
        )
        self.delete_chapter_button.grid(row=1, column=2, sticky="ew", padx=(8, 0), pady=(8, 0))

        content_split = ttk.Panedwindow(right, orient=tk.HORIZONTAL)
        content_split.grid(row=2, column=0, sticky="nsew", pady=(8, 0))

        chapter_frame = ttk.Frame(content_split, padding=(0, 0, 12, 0))
        chapter_frame.columnconfigure(0, weight=1)
        chapter_frame.rowconfigure(1, weight=1)
        ttk.Label(chapter_frame, text="Detected chapters").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.chapter_listbox = tk.Listbox(chapter_frame, exportselection=False, height=24)
        self.chapter_listbox.grid(row=1, column=0, sticky="nsew")
        self.chapter_listbox.bind("<<ListboxSelect>>", self._on_chapter_selected)
        content_split.add(chapter_frame, weight=1)

        editor_frame = ttk.Frame(content_split)
        editor_frame.columnconfigure(0, weight=1)
        editor_frame.rowconfigure(0, weight=1)
        self.editor_text = ScrolledText(editor_frame, wrap=tk.WORD, undo=True)
        self.editor_text.grid(row=0, column=0, sticky="nsew")
        self.editor_text.bind("<<Modified>>", self._on_editor_modified)
        content_split.add(editor_frame, weight=3)

        log_frame = ttk.LabelFrame(main, text="Activity", padding=12)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(16, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(log_frame, wrap=tk.WORD, height=8)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        status_bar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        status_bar.grid(row=1, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        status_bar.columnconfigure(1, weight=0)
        ttk.Label(status_bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(status_bar, textvariable=self.progress_detail_var).grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.progress_bar = ttk.Progressbar(
            status_bar,
            orient=tk.HORIZONTAL,
            mode="determinate",
            variable=self.progress_value_var,
            maximum=100,
        )
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self._set_editor_text("")

    def _browse_source(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select a source file",
            filetypes=SUPPORTED_FILE_TYPES,
            initialdir=str(APP_ROOT),
        )
        if not selected:
            return
        self.source_var.set(selected)
        self.status_var.set("Source file selected. Prepare the project, or rebuild it for a fresh parse.")

    def _browse_output_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Select an output folder",
            initialdir=self.output_root_var.get() or str(DEFAULT_OUTPUT_ROOT),
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

        self._start_task("Preparing project...", lambda: self._prepare_project_worker(settings))

    def _rebuild_project(self) -> None:
        if not self._ensure_safe_to_continue("rebuilding the project"):
            return

        try:
            settings = self._collect_settings(require_voice=False)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        confirmed = messagebox.askyesno(
            "Rebuild Project",
            "Rebuild the prepared project from the original source?\n\n"
            "This will replace the current cleaned chapter files, samples, and renders for this project.",
            parent=self.root,
        )
        if not confirmed:
            return

        settings.force_rebuild = True
        self._start_task("Rebuilding project from source...", lambda: self._prepare_project_worker(settings))

    def _render_sample(self) -> None:
        if not self._ensure_safe_to_continue("rendering a sample"):
            return

        try:
            settings = self._collect_settings(require_voice=True)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        self._start_task("Rendering sample...", lambda: self._render_sample_worker(settings))

    def _render_selected_chapter(self) -> None:
        if not self._ensure_safe_to_continue("rendering the selected chapter"):
            return

        try:
            settings = self._collect_settings(require_voice=True)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        self._start_task("Rendering selected chapter...", lambda: self._render_selected_chapter_worker(settings))

    def _render_full(self) -> None:
        if not self._ensure_safe_to_continue("rendering the full conversion"):
            return

        try:
            settings = self._collect_settings(require_voice=True)
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return

        self._start_task("Rendering full conversion...", lambda: self._render_full_worker(settings))

    def _collect_settings(self, *, require_voice: bool) -> RenderSettings:
        source_text = self.source_var.get().strip()
        if not source_text:
            raise ValueError("Choose a source file first.")

        source_path = Path(source_text).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise ValueError("The selected source file does not exist.")

        output_text = self.output_root_var.get().strip()
        output_root = Path(output_text or DEFAULT_OUTPUT_ROOT).expanduser().resolve()

        voice_id = self._selected_voice_id()
        if require_voice and not voice_id:
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

        voice_info = self.voice_lookup.get(voice_id)
        language_code = voice_info.language_code if voice_info else (voice_id[:1] or "a")

        return RenderSettings(
            source_path=source_path,
            output_root=output_root,
            voice=voice_id,
            language_code=language_code,
            speed=speed,
            sample_chars=sample_chars,
            selected_chapter_index=self._selected_chapter_index(),
            overwrite_audio=bool(self.overwrite_var.get()),
            current_project_dir=self.project_dir,
            current_project_source=self.current_source_path,
            force_rebuild=False,
        )

    def _start_task(self, status_text: str, worker: Callable[[], None]) -> None:
        if self.busy:
            messagebox.showinfo("Busy", "A task is already running. Please wait for it to finish.", parent=self.root)
            return

        self.busy = True
        self.task_started_at = monotonic()
        self.status_var.set(status_text)
        self.progress_value_var.set(0.0)
        self.progress_detail_var.set("Waiting for progress...")
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
        project_dir, manifest = self._resolve_project(settings, allow_reingest=settings.force_rebuild)
        self.events.put(("project_ready", project_dir, manifest, settings.force_rebuild))
        action = "Rebuilt" if settings.force_rebuild else "Prepared"
        self.events.put(("log", f"{action} project: {project_dir}"))

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
            chapter_index=settings.selected_chapter_index,
            sample_chars=settings.sample_chars,
            sample_rate=24000,
            overwrite=True,
            progress_callback=self._emit_render_progress,
            sample_metadata={"voice": settings.voice, "speed": settings.speed},
        )
        updated_manifest = load_manifest(project_dir)
        self.events.put(("sample_done", project_dir, updated_manifest, sample_path))
        self.events.put(("log", f"Sample rendered: {sample_path}"))

    def _render_selected_chapter_worker(self, settings: RenderSettings) -> None:
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
            chapter_indexes=[settings.selected_chapter_index],
            sample_rate=24000,
            overwrite=True,
            progress_callback=self._emit_render_progress,
        )
        chapter = next((item for item in updated_manifest.chapters if item.index == settings.selected_chapter_index), None)
        chapter_audio = None if chapter is None or chapter.audio_path is None else project_dir / chapter.audio_path
        self.events.put(("chapter_done", project_dir, updated_manifest, chapter_audio))
        if chapter_audio is not None:
            self.events.put(("log", f"Chapter rendered: {chapter_audio}"))

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
            progress_callback=self._emit_render_progress,
        )
        self.events.put(("full_done", project_dir, updated_manifest))
        self.events.put(("log", f"Full conversion complete: {project_dir}"))

    def _emit_render_progress(self, progress: RenderProgress) -> None:
        self.events.put(("progress", progress))

    def _resolve_project(self, settings: RenderSettings, *, allow_reingest: bool) -> tuple[Path, ProjectManifest]:
        if allow_reingest:
            return ensure_project(settings.source_path, settings.output_root, overwrite=True)
        if (
            settings.current_project_dir is not None
            and settings.current_project_source is not None
            and settings.current_project_source == settings.source_path
            and settings.current_project_dir.exists()
            and settings.current_project_dir.parent.resolve() == settings.output_root.resolve()
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
                self._apply_project(event[1], event[2], selected_chapter_index=self._selected_chapter_index())
                status_text = (
                    "Project rebuilt. Review the cleaned text, then generate a new sample."
                    if event[3]
                    else "Project ready. Review the cleaned text, tweak it if needed, then generate a sample."
                )
                self.status_var.set(status_text)
                self._reset_progress_display()
            elif kind == "progress":
                self._apply_render_progress(event[1])
            elif kind == "sample_done":
                self._apply_project(event[1], event[2], selected_chapter_index=self._selected_chapter_index())
                self._update_last_sample_path(event[3])
                self.status_var.set(f"Sample ready: {event[3].name}")
                self.progress_value_var.set(100.0)
                self.progress_detail_var.set("100% complete")
                messagebox.showinfo("Sample Ready", f"Sample created:\n{event[3]}", parent=self.root)
            elif kind == "chapter_done":
                self._apply_project(event[1], event[2], selected_chapter_index=self._selected_chapter_index())
                chapter_audio = event[3]
                self.status_var.set("Selected chapter render finished.")
                self.progress_value_var.set(100.0)
                self.progress_detail_var.set("100% complete")
                if chapter_audio is not None:
                    messagebox.showinfo("Chapter Ready", f"Chapter audio created:\n{chapter_audio}", parent=self.root)
            elif kind == "full_done":
                self._apply_project(event[1], event[2], selected_chapter_index=self._selected_chapter_index())
                self.status_var.set("Full conversion finished.")
                self.progress_value_var.set(100.0)
                self.progress_detail_var.set("100% complete")
                messagebox.showinfo(
                    "Conversion Complete",
                    f"Finished rendering {len(event[2].chapters)} chapters.\n\nProject folder:\n{event[1]}",
                    parent=self.root,
                )
            elif kind == "log":
                self._queue_log(event[1])
            elif kind == "error":
                self.status_var.set("The last task failed. See the activity log for details.")
                self.progress_value_var.set(0.0)
                self.progress_detail_var.set("Task failed")
                self._queue_log(event[1])
                self._queue_log(event[2])
                messagebox.showerror("Task Failed", event[1], parent=self.root)
            elif kind == "idle":
                self.busy = False
                self.task_started_at = None
                if self.progress_value_var.get() < 100.0:
                    self._reset_progress_display()
                self._set_controls_enabled(True)

        self.root.after(150, self._poll_events)

    def _apply_voice_list(self, voices: list[VoiceInfo]) -> None:
        sorted_voices = sorted(voices, key=lambda item: (item.language, friendly_voice_label(item), item.voice))
        self.voice_lookup = {voice.voice: voice for voice in sorted_voices}
        self.voice_label_to_id.clear()
        self.voice_id_to_label.clear()

        labels: list[str] = []
        for voice in sorted_voices:
            label = friendly_voice_label(voice)
            if label in self.voice_label_to_id:
                label = f"{label} [{voice.voice}]"
            self.voice_label_to_id[label] = voice.voice
            self.voice_id_to_label[voice.voice] = label
            labels.append(label)

        self.voice_combo["values"] = labels
        selected_voice = self.voice_id_var.get()
        if selected_voice not in self.voice_lookup and sorted_voices:
            selected_voice = "af_heart" if "af_heart" in self.voice_lookup else sorted_voices[0].voice
        self.voice_id_var.set(selected_voice)
        self.voice_display_var.set(self.voice_id_to_label.get(selected_voice, ""))
        self._sync_voice_metadata()

    def _on_voice_selected(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._sync_voice_metadata()

    def _sync_voice_metadata(self) -> None:
        selected_voice = self._selected_voice_id()
        if selected_voice:
            self.voice_id_var.set(selected_voice)

        voice_info = self.voice_lookup.get(selected_voice)
        if voice_info is not None:
            self.voice_language_var.set(voice_info.language)
        else:
            self.voice_language_var.set("-")

        preview_path = None if not selected_voice else get_voice_sample_path(selected_voice, APP_ROOT)
        if preview_path is None:
            self.voice_preview_var.set("Built-in preview: not found. You can still render your own sample from the book.")
        else:
            self.voice_preview_var.set(f"Built-in preview ready: {preview_path.name}")
        self._update_last_sample_path()
        self._refresh_project_runtime_estimate()

    def _on_estimation_inputs_changed(self, *_args: object) -> None:
        self._refresh_project_runtime_estimate()

    def _apply_render_progress(self, progress: RenderProgress) -> None:
        self.progress_value_var.set(progress.percent)
        self.status_var.set(progress.message)
        self.progress_detail_var.set(self._format_progress_detail(progress))

    def _format_progress_detail(self, progress: RenderProgress) -> str:
        parts = [f"{progress.percent:.0f}%"]
        if progress.total_chapters > 0 and progress.chapter_position > 0:
            parts.append(f"Chapter {progress.chapter_position}/{progress.total_chapters}")
        if progress.total_segments_in_chapter > 0 and progress.segment_index > 0:
            parts.append(f"Segment {progress.segment_index}/{progress.total_segments_in_chapter}")

        eta_text = self._estimate_eta_text(progress)
        if eta_text is not None:
            parts.append(f"ETA {eta_text}")
        return " | ".join(parts)

    def _estimate_eta_text(self, progress: RenderProgress) -> str | None:
        if self.task_started_at is None:
            return None
        if progress.total_units <= 0 or progress.completed_units <= 0:
            return None
        if progress.completed_units >= progress.total_units:
            return "00:00"

        elapsed = max(0.0, monotonic() - self.task_started_at)
        seconds_per_unit = elapsed / progress.completed_units
        remaining_seconds = seconds_per_unit * (progress.total_units - progress.completed_units)
        return self._format_duration_seconds(remaining_seconds)

    def _format_duration_seconds(self, seconds: float) -> str:
        total_seconds = max(0, int(round(seconds)))
        minutes, seconds_part = divmod(total_seconds, 60)
        hours, minutes_part = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes_part:02d}:{seconds_part:02d}"
        return f"{minutes_part:02d}:{seconds_part:02d}"

    def _reset_progress_display(self) -> None:
        self.progress_value_var.set(0.0)
        self.progress_detail_var.set("Idle")

    def _sync_left_scrollregion(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.left_scroll_canvas.configure(scrollregion=self.left_scroll_canvas.bbox("all"))

    def _sync_left_canvas_width(self, event: tk.Event[tk.Misc]) -> None:
        self.left_scroll_canvas.itemconfigure(self.left_scroll_window, width=event.width)

    def _bind_left_mousewheel(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.left_scroll_canvas.bind_all("<MouseWheel>", self._on_left_mousewheel)

    def _unbind_left_mousewheel(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self.left_scroll_canvas.unbind_all("<MouseWheel>")

    def _on_left_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return
        self.left_scroll_canvas.yview_scroll(int(-delta / 120), "units")

    def _apply_project(
        self,
        project_dir: Path,
        manifest: ProjectManifest,
        *,
        selected_chapter_index: int | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.current_source_path = Path(manifest.source_file).resolve()
        self.manifest = manifest
        self.chapter_records = list(manifest.chapters)

        self.project_title_var.set(manifest.title)
        self.project_path_var.set(str(project_dir))
        self.project_format_var.set(manifest.source_format)
        self.project_parser_var.set(manifest.parser_name)
        self.project_chapters_var.set(str(len(manifest.chapters)))
        self.project_minutes_var.set(f"{manifest.total_estimated_minutes:.2f} min")

        self.suspend_selection_events = True
        listbox_state = str(self.chapter_listbox.cget("state"))
        if listbox_state == "disabled":
            self.chapter_listbox.configure(state="normal")
        self.chapter_listbox.delete(0, tk.END)
        for chapter in manifest.chapters:
            self.chapter_listbox.insert(tk.END, self._chapter_label(chapter))

        chosen_index = selected_chapter_index
        if chosen_index is None and self.active_chapter_index is not None:
            chosen_index = self.active_chapter_index
        if chosen_index is None and manifest.chapters:
            chosen_index = manifest.chapters[0].index

        if manifest.chapters and chosen_index is not None:
            listbox_index = self._chapter_listbox_index(chosen_index)
            if listbox_index is None:
                listbox_index = 0
            self.chapter_listbox.selection_clear(0, tk.END)
            self.chapter_listbox.selection_set(listbox_index)
            self.chapter_listbox.activate(listbox_index)
            self._load_chapter_into_editor(self.chapter_records[listbox_index].index)
        else:
            self.active_chapter_index = None
            self.sample_chapter_var.set("Selected chapter for samples: not available")
            self.editor_state_var.set("No chapters were found in the current project.")
            self._set_editor_text("")

        if listbox_state == "disabled":
            self.chapter_listbox.configure(state="disabled")
        self.suspend_selection_events = False
        self._update_last_sample_path()
        self._refresh_project_runtime_estimate()

    def _on_chapter_selected(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self.suspend_selection_events or not self.chapter_records:
            return

        selection = self.chapter_listbox.curselection()
        if not selection:
            return

        next_index = self.chapter_records[selection[0]].index
        if next_index == self.active_chapter_index:
            return

        if not self._ensure_safe_to_continue("switching chapters"):
            self._restore_active_chapter_selection()
            return

        self._load_chapter_into_editor(next_index)

    def _load_chapter_into_editor(self, chapter_index: int) -> None:
        if self.project_dir is None:
            self._set_editor_text("")
            return

        chapter = next((item for item in self.chapter_records if item.index == chapter_index), None)
        if chapter is None:
            return

        text = (self.project_dir / chapter.clean_text_path).read_text(encoding="utf-8").rstrip()
        self.active_chapter_index = chapter.index
        self.sample_chapter_var.set(f"Selected chapter for samples: {chapter.index:03d}  {chapter.title}")
        self.editor_state_var.set(
            f"Editing cleaned text for {chapter.title}. Save changes before rerendering if you want them applied."
        )
        self._set_editor_text(text)
        self._update_last_sample_path()

    def _set_editor_text(self, text: str) -> None:
        self.ignore_editor_modified = True
        text_state = str(self.editor_text.cget("state"))
        if text_state == "disabled":
            self.editor_text.configure(state="normal")
        self.editor_text.delete("1.0", tk.END)
        self.editor_text.insert("1.0", text)
        self.editor_text.edit_modified(False)
        if text_state == "disabled":
            self.editor_text.configure(state="disabled")
        self.ignore_editor_modified = False
        self.editor_dirty = False

    def _on_editor_modified(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self.ignore_editor_modified:
            return
        if not self.editor_text.edit_modified():
            return

        self.editor_text.edit_modified(False)
        self.editor_dirty = True
        if self.active_chapter_index is not None:
            chapter = next((item for item in self.chapter_records if item.index == self.active_chapter_index), None)
            if chapter is not None:
                self.editor_state_var.set(f"Unsaved edits in {chapter.title}. Save before rerendering or switching chapters.")

    def _save_current_chapter(self, *, show_message: bool = True) -> bool:
        if self.project_dir is None or self.active_chapter_index is None:
            messagebox.showinfo("No Chapter", "Prepare a project and select a chapter first.", parent=self.root)
            return False

        updated_manifest = update_chapter_clean_text(
            self.project_dir,
            self.active_chapter_index,
            self.editor_text.get("1.0", "end-1c"),
        )
        self._apply_project(self.project_dir, updated_manifest, selected_chapter_index=self.active_chapter_index)
        self.editor_state_var.set("Saved cleaned chapter text. Future renders will use these edits.")
        self.status_var.set("Saved cleaned chapter text.")
        self._queue_log(f"Saved cleaned text for chapter {self.active_chapter_index}.")
        if show_message:
            messagebox.showinfo("Saved", "Cleaned chapter text saved.", parent=self.root)
        return True

    def _revert_current_chapter(self) -> None:
        if self.project_dir is None or self.active_chapter_index is None:
            return
        if self.editor_dirty:
            confirmed = messagebox.askyesno(
                "Revert Edits",
                "Discard unsaved changes for the selected chapter and reload the last saved text?",
                parent=self.root,
            )
            if not confirmed:
                return

        self._load_chapter_into_editor(self.active_chapter_index)
        self.status_var.set("Reloaded the last saved cleaned chapter text.")
        self._queue_log(f"Reloaded chapter {self.active_chapter_index} from disk.")

    def _rename_current_chapter(self) -> None:
        chapter = self._current_chapter_record()
        if chapter is None:
            messagebox.showinfo("No Chapter", "Prepare a project and select a chapter first.", parent=self.root)
            return
        if not self._ensure_ready_for_structure_edit("renaming the chapter title"):
            return

        new_title = simpledialog.askstring(
            "Rename Chapter",
            "New chapter title:",
            initialvalue=chapter.title,
            parent=self.root,
        )
        if new_title is None:
            return

        updated_manifest = rename_chapter_title(self.project_dir, chapter.index, new_title)  # type: ignore[arg-type]
        self._apply_project(self.project_dir, updated_manifest, selected_chapter_index=chapter.index)  # type: ignore[arg-type]
        self.status_var.set(f"Renamed chapter {chapter.index}.")
        self._queue_log(f"Renamed chapter {chapter.index} to {new_title.strip() or chapter.title}.")

    def _split_current_chapter(self) -> None:
        chapter = self._current_chapter_record()
        if chapter is None:
            messagebox.showinfo("No Chapter", "Prepare a project and select a chapter first.", parent=self.root)
            return
        if not self._ensure_ready_for_structure_edit("splitting the chapter", require_saved=True):
            return

        editor_text = self.editor_text.get("1.0", "end-1c")
        cursor_offset = self._current_split_offset()
        suggested_title = self._suggest_split_title(editor_text, cursor_offset, f"{chapter.title} (Part 2)")
        new_title = simpledialog.askstring(
            "Split Chapter",
            "Title for the new chapter created after the cursor:",
            initialvalue=suggested_title,
            parent=self.root,
        )
        if new_title is None:
            return

        try:
            updated_manifest = split_chapter(
                self.project_dir,  # type: ignore[arg-type]
                chapter.index,
                cursor_offset,
                new_title=new_title,
            )
        except ValueError as exc:
            messagebox.showerror("Split Failed", str(exc), parent=self.root)
            return

        next_index = min(chapter.index + 1, len(updated_manifest.chapters))
        self._apply_project(self.project_dir, updated_manifest, selected_chapter_index=next_index)  # type: ignore[arg-type]
        self.status_var.set(f"Split chapter {chapter.index} at the cursor.")
        self._queue_log(f"Split chapter {chapter.index}; new chapter selected at index {next_index}.")

    def _merge_with_previous(self) -> None:
        chapter = self._current_chapter_record()
        if chapter is None:
            messagebox.showinfo("No Chapter", "Prepare a project and select a chapter first.", parent=self.root)
            return
        if chapter.index <= 1:
            messagebox.showinfo("Cannot Merge", "The first chapter cannot be merged upward.", parent=self.root)
            return
        if not self._ensure_ready_for_structure_edit("merging with the previous chapter"):
            return

        confirmed = messagebox.askyesno(
            "Merge Up",
            "Merge the selected chapter into the previous chapter?\n\n"
            "This clears any generated samples or renders for the project.",
            parent=self.root,
        )
        if not confirmed:
            return

        updated_manifest = merge_chapters(self.project_dir, chapter.index, direction="previous")  # type: ignore[arg-type]
        selected_index = max(1, chapter.index - 1)
        self._apply_project(self.project_dir, updated_manifest, selected_chapter_index=selected_index)  # type: ignore[arg-type]
        self.status_var.set(f"Merged chapter {chapter.index} into chapter {selected_index}.")
        self._queue_log(f"Merged chapter {chapter.index} upward into chapter {selected_index}.")

    def _merge_with_next(self) -> None:
        chapter = self._current_chapter_record()
        if chapter is None:
            messagebox.showinfo("No Chapter", "Prepare a project and select a chapter first.", parent=self.root)
            return
        if chapter.index >= len(self.chapter_records):
            messagebox.showinfo("Cannot Merge", "The last chapter cannot be merged downward.", parent=self.root)
            return
        if not self._ensure_ready_for_structure_edit("merging with the next chapter"):
            return

        confirmed = messagebox.askyesno(
            "Merge Down",
            "Merge the selected chapter with the next chapter?\n\n"
            "This clears any generated samples or renders for the project.",
            parent=self.root,
        )
        if not confirmed:
            return

        updated_manifest = merge_chapters(self.project_dir, chapter.index, direction="next")  # type: ignore[arg-type]
        self._apply_project(self.project_dir, updated_manifest, selected_chapter_index=chapter.index)  # type: ignore[arg-type]
        self.status_var.set(f"Merged chapter {chapter.index} with the following chapter.")
        self._queue_log(f"Merged chapter {chapter.index} downward into chapter {chapter.index + 1}.")

    def _delete_current_chapter(self) -> None:
        chapter = self._current_chapter_record()
        if chapter is None:
            messagebox.showinfo("No Chapter", "Prepare a project and select a chapter first.", parent=self.root)
            return
        if len(self.chapter_records) <= 1:
            messagebox.showinfo("Cannot Delete", "The only chapter in a project cannot be deleted.", parent=self.root)
            return
        if not self._ensure_ready_for_structure_edit("deleting the chapter"):
            return

        confirmed = messagebox.askyesno(
            "Delete Chapter",
            f"Delete chapter {chapter.index}: {chapter.title}?\n\n"
            "This clears any generated samples or renders for the project.",
            parent=self.root,
        )
        if not confirmed:
            return

        updated_manifest = delete_chapter(self.project_dir, chapter.index)  # type: ignore[arg-type]
        selected_index = min(chapter.index, len(updated_manifest.chapters))
        self._apply_project(self.project_dir, updated_manifest, selected_chapter_index=selected_index)  # type: ignore[arg-type]
        self.status_var.set(f"Deleted chapter {chapter.index}.")
        self._queue_log(f"Deleted chapter {chapter.index}: {chapter.title}.")

    def _ensure_safe_to_continue(self, action: str) -> bool:
        if not self.editor_dirty:
            return True

        choice = messagebox.askyesnocancel(
            "Unsaved Changes",
            f"Save the current chapter edits before {action}?\n\nChoose No to continue without saving them.",
            parent=self.root,
        )
        if choice is None:
            return False
        if choice:
            return self._save_current_chapter(show_message=False)
        return True

    def _ensure_ready_for_structure_edit(self, action: str, *, require_saved: bool = False) -> bool:
        if self.project_dir is None or self.active_chapter_index is None:
            return False
        if not self.editor_dirty:
            return True
        if not require_saved:
            return self._ensure_safe_to_continue(action)

        choice = messagebox.askyesnocancel(
            "Unsaved Changes",
            f"Save the current chapter edits before {action}?\n\n"
            "Splitting uses the current editor text, so saving first is recommended.",
            parent=self.root,
        )
        if choice is None or not choice:
            return False
        return self._save_current_chapter(show_message=False)

    def _current_chapter_record(self) -> ChapterRecord | None:
        if self.active_chapter_index is None:
            return None
        return next((item for item in self.chapter_records if item.index == self.active_chapter_index), None)

    def _current_split_offset(self) -> int:
        selection = self.editor_text.tag_ranges(tk.SEL)
        index = selection[0] if selection else self.editor_text.index(tk.INSERT)
        return len(self.editor_text.get("1.0", index))

    def _suggest_split_title(self, text: str, cursor_offset: int, fallback: str) -> str:
        remaining = text[cursor_offset:].lstrip()
        for line in remaining.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) <= 80 and len(stripped.split()) <= 8 and stripped[-1:] not in ".!?;:":
                return stripped
            break
        return fallback

    def _selected_voice_id(self) -> str:
        selected_label = self.voice_display_var.get().strip()
        if selected_label in self.voice_label_to_id:
            return self.voice_label_to_id[selected_label]
        current_voice_id = self.voice_id_var.get().strip()
        if current_voice_id in self.voice_lookup:
            return current_voice_id
        return current_voice_id

    def _selected_chapter_index(self) -> int:
        if not self.chapter_records:
            return 1
        selection = self.chapter_listbox.curselection()
        if selection:
            return self.chapter_records[selection[0]].index
        if self.active_chapter_index is not None:
            return self.active_chapter_index
        return self.chapter_records[0].index

    def _restore_active_chapter_selection(self) -> None:
        if self.active_chapter_index is None:
            return
        listbox_index = self._chapter_listbox_index(self.active_chapter_index)
        if listbox_index is None:
            return

        self.suspend_selection_events = True
        self.chapter_listbox.selection_clear(0, tk.END)
        self.chapter_listbox.selection_set(listbox_index)
        self.chapter_listbox.activate(listbox_index)
        self.suspend_selection_events = False

    def _chapter_listbox_index(self, chapter_index: int) -> int | None:
        for index, chapter in enumerate(self.chapter_records):
            if chapter.index == chapter_index:
                return index
        return None

    def _chapter_label(self, chapter: ChapterRecord) -> str:
        return f"{chapter.index:03d}  {chapter.title}  [{chapter.word_count} words | {chapter.estimated_minutes:.2f} min]"

    def _update_last_sample_path(self, sample_path: Path | None = None) -> None:
        if sample_path is not None:
            self.last_sample_path = sample_path
        else:
            self.last_sample_path = self._expected_sample_path()

        if self.last_sample_path is None:
            self.last_sample_var.set("No sample rendered yet")
        else:
            self.last_sample_var.set(self.last_sample_path.name)
        self._refresh_project_runtime_estimate()

    def _refresh_project_runtime_estimate(self) -> None:
        if self.project_dir is None or self.manifest is None:
            return

        try:
            speed = float(self.speed_var.get())
        except (tk.TclError, ValueError):
            speed = 1.0

        voice_id = self._selected_voice_id() or "default"
        estimate = estimate_project_runtime(
            self.project_dir,
            self.manifest,
            voice=voice_id,
            speed=speed,
        )
        self.project_minutes_var.set(estimate.label)

    def _expected_sample_path(self) -> Path | None:
        if self.project_dir is None or self.active_chapter_index is None:
            return None

        voice_id = self._selected_voice_id()
        if not voice_id:
            return None

        chapter = next((item for item in self.chapter_records if item.index == self.active_chapter_index), None)
        if chapter is None:
            return None

        sample_path = self.project_dir / "samples" / f"{chapter.index:03d}-{chapter.slug}-{voice_id}.mp3"
        if sample_path.exists():
            return sample_path
        return None

    def _play_voice_preview(self) -> None:
        voice_id = self._selected_voice_id()
        if not voice_id:
            messagebox.showinfo("No Voice", "Choose a voice first.", parent=self.root)
            return

        preview_path = get_voice_sample_path(voice_id, APP_ROOT)
        if preview_path is None:
            messagebox.showinfo(
                "Preview Not Found",
                "No built-in preview file was found for this voice. You can still render a sample from your book.",
                parent=self.root,
            )
            return

        self._play_audio_file(preview_path, f"Playing built-in preview for {self.voice_display_var.get()}.")

    def _play_last_sample(self) -> None:
        if self.last_sample_path is None or not self.last_sample_path.exists():
            messagebox.showinfo("No Sample", "Render a sample first, then you can play it here.", parent=self.root)
            return

        self._play_audio_file(self.last_sample_path, f"Playing last sample: {self.last_sample_path.name}")

    def _play_audio_file(self, path: Path, status_text: str) -> None:
        try:
            self.audio_player.play(path)
        except AudioPlayerError as exc:
            messagebox.showerror("Playback Failed", str(exc), parent=self.root)
            return

        self.status_var.set(status_text)
        self._queue_log(status_text)

    def _stop_audio(self) -> None:
        try:
            self.audio_player.stop()
        except AudioPlayerError as exc:
            messagebox.showerror("Stop Failed", str(exc), parent=self.root)
            return

        self.status_var.set("Audio playback stopped.")
        self._queue_log("Audio playback stopped.")

    def _queue_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        readonly = "readonly" if enabled else "disabled"

        self.source_entry.configure(state=state)
        self.output_entry.configure(state=state)
        self.voice_combo.configure(state=readonly)
        self.speed_spinbox.configure(state=state)
        self.sample_chars_spinbox.configure(state=state)
        self.browse_source_button.configure(state=state)
        self.browse_output_button.configure(state=state)
        self.prepare_button.configure(state=state)
        self.refresh_voices_button.configure(state=state)
        self.play_voice_button.configure(state=state)
        self.play_sample_button.configure(state=state)
        self.rebuild_button.configure(state=state)
        self.render_sample_button.configure(state=state)
        self.render_chapter_button.configure(state=state)
        self.render_full_button.configure(state=state)
        self.open_project_button.configure(state=state)
        self.save_edits_button.configure(state=state)
        self.revert_edits_button.configure(state=state)
        self.rename_title_button.configure(state=state)
        self.split_chapter_button.configure(state=state)
        self.merge_up_button.configure(state=state)
        self.merge_down_button.configure(state=state)
        self.delete_chapter_button.configure(state=state)
        self.overwrite_check.configure(state=state)
        self.chapter_listbox.configure(state=state)
        self.editor_text.configure(state=state)
        self.stop_audio_button.configure(state="normal")

    def _open_project_folder(self) -> None:
        if self.project_dir is None:
            messagebox.showinfo("No Project", "Prepare a project first.", parent=self.root)
            return

        target = self.project_dir.resolve()
        try:
            os.startfile(target)  # type: ignore[attr-defined]
        except AttributeError:
            messagebox.showinfo("Project Folder", str(target), parent=self.root)

    def _on_close(self) -> None:
        try:
            self.audio_player.stop()
        except AudioPlayerError:
            pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    Book2AudioGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
