import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from book2audio.gui import Book2AudioGUI, RenderSettings
from book2audio.render import RenderController, RenderProgress
from book2audio.pipeline import ingest_book


class GuiTests(unittest.TestCase):
    def test_apply_project_populates_widgets_even_when_controls_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists to populate the GUI editor.\n\n"
                "Chapter 2\n\nThis chapter exists to populate the chapter list.",
                encoding="utf-8",
            )
            project_dir, manifest = ingest_book(source, tmp_path / "projects")

            root = tk.Tk()
            root.withdraw()
            try:
                with patch.object(Book2AudioGUI, "_start_task", lambda self, status_text, worker: None):
                    app = Book2AudioGUI(root)
                app._set_controls_enabled(False)
                app._apply_project(project_dir, manifest, selected_chapter_index=1)

                self.assertEqual(app.chapter_listbox.size(), 2)
                self.assertIn("populate the GUI editor", app.editor_text.get("1.0", "end-1c"))
            finally:
                root.destroy()

    def test_workflow_actions_are_visible_and_renamed(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(Book2AudioGUI, "_start_task", lambda self, status_text, worker: None):
                app = Book2AudioGUI(root)

            self.assertEqual(app.prepare_button.cget("text"), "Prepare Project")
            self.assertEqual(app.rebuild_button.cget("text"), "Rebuild Project")
            self.assertEqual(app.render_sample_button.cget("text"), "Generate Sample")
            self.assertEqual(app.render_chapter_button.cget("text"), "Render Selected Chapter")
            self.assertEqual(app.render_full_button.cget("text"), "Convert Full Book")
            self.assertEqual(app.pause_render_button.cget("text"), "Pause Render")
            self.assertEqual(app.stop_render_button.cget("text"), "Stop Render")
            self.assertEqual(app.rename_title_button.cget("text"), "Rename Title")
            self.assertEqual(app.split_chapter_button.cget("text"), "Split at Cursor")
            self.assertEqual(app.merge_up_button.cget("text"), "Merge Up")
            self.assertEqual(app.merge_down_button.cget("text"), "Merge Down")
            self.assertEqual(app.delete_chapter_button.cget("text"), "Delete Chapter")
        finally:
            root.destroy()

    def test_render_control_buttons_follow_active_render_state(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(Book2AudioGUI, "_start_task", lambda self, status_text, worker: None):
                app = Book2AudioGUI(root)

            self.assertEqual(str(app.pause_render_button.cget("state")), "disabled")
            self.assertEqual(str(app.stop_render_button.cget("state")), "disabled")

            app.busy = True
            app.render_controller = RenderController()
            app.render_pause_requested = True
            app._sync_render_control_buttons()

            self.assertEqual(str(app.pause_render_button.cget("state")), "normal")
            self.assertEqual(app.pause_render_button.cget("text"), "Resume Render")
            self.assertEqual(str(app.stop_render_button.cget("state")), "normal")
        finally:
            root.destroy()

    def test_left_panel_is_scrollable(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(Book2AudioGUI, "_start_task", lambda self, status_text, worker: None):
                app = Book2AudioGUI(root)

            self.assertIsInstance(app.left_scroll_canvas, tk.Canvas)
            self.assertEqual(str(app.left_scrollbar.cget("orient")), "vertical")
        finally:
            root.destroy()

    def test_apply_render_progress_updates_status_strip(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(Book2AudioGUI, "_start_task", lambda self, status_text, worker: None):
                app = Book2AudioGUI(root)

            app.task_started_at = 0.0
            with patch("book2audio.gui.monotonic", return_value=10.0):
                app._apply_render_progress(
                    RenderProgress(
                        phase="segment_complete",
                        chapter_index=2,
                        chapter_title="Example",
                        chapter_position=2,
                        total_chapters=5,
                        segment_index=3,
                        total_segments_in_chapter=8,
                        completed_units=4,
                        total_units=10,
                        percent=40.0,
                        message="Rendering chapter 2/5 segment 3/8: Example",
                    )
                )

            self.assertEqual(app.progress_value_var.get(), 40.0)
            self.assertIn("40%", app.progress_detail_var.get())
            self.assertIn("Chapter 2/5", app.progress_detail_var.get())
            self.assertIn("ETA", app.progress_detail_var.get())
        finally:
            root.destroy()

    def test_resolve_project_uses_reingest_when_rebuild_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "book.txt"
            source.write_text(
                "Chapter 1\n\nThis chapter exists so the rebuild path can be exercised in the GUI.",
                encoding="utf-8",
            )
            project_dir, _manifest = ingest_book(source, tmp_path / "projects")

            root = tk.Tk()
            root.withdraw()
            try:
                with patch.object(Book2AudioGUI, "_start_task", lambda self, status_text, worker: None):
                    app = Book2AudioGUI(root)

                settings = RenderSettings(
                    source_path=source.resolve(),
                    output_root=(tmp_path / "projects").resolve(),
                    voice="af_heart",
                    language_code="a",
                    speed=1.0,
                    sample_chars=650,
                    selected_chapter_index=1,
                    overwrite_audio=False,
                    current_project_dir=project_dir,
                    current_project_source=source.resolve(),
                    force_rebuild=True,
                )

                with patch("book2audio.gui.ensure_project") as ensure_project_mock:
                    sentinel_manifest = object()
                    ensure_project_mock.return_value = (project_dir, sentinel_manifest)

                    resolved_project, resolved_manifest = app._resolve_project(settings, allow_reingest=True)

                ensure_project_mock.assert_called_once_with(
                    source.resolve(),
                    (tmp_path / "projects").resolve(),
                    overwrite=True,
                )
                self.assertEqual(resolved_project, project_dir)
                self.assertIs(resolved_manifest, sentinel_manifest)
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
