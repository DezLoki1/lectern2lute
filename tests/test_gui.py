import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from book2audio.gui import Book2AudioGUI
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


if __name__ == "__main__":
    unittest.main()
