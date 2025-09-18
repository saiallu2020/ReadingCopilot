from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QWidget, QHBoxLayout, QSplitter,
    QMessageBox, QToolBar, QProgressDialog, QLineEdit, QLabel, QStatusBar
)
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtCore import Qt, QSize

from readingcopilot.core.annotations import AnnotationDocument, Highlight
from readingcopilot.core.llm_client import build_llm_client
from readingcopilot.core.llm_highlight import LLMHighlighter
from readingcopilot.ui.profile_dialog import ProfileDialog
from readingcopilot.ui.pdf_viewer import PDFViewer
from readingcopilot.ui.annotation_panel import AnnotationPanel

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ReadingCopilot - PDF Annotator")
        self.resize(1200, 900)
        self._llm_client = None  # lazy init
        self._suppress_page_signal = False
        self._state_path = self._state_file_path()

        # Status bar
        self.page_label = QLabel("Page: -/-")
        status = QStatusBar()
        status.addPermanentWidget(self.page_label)
        self.setStatusBar(status)

        self.viewer = PDFViewer()
        self.panel = AnnotationPanel()
        self.viewer.highlightCreated.connect(self.panel.add_highlight)
        self.panel.highlightSelected.connect(self._focus_highlight)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.panel)
        splitter.setSizes([900, 300])

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(splitter)
        self.setCentralWidget(container)
        # Page jump widgets must exist before toolbar creation
        self.page_input = QLineEdit()
        self.page_input.setFixedWidth(60)
        self.page_input.setPlaceholderText("Go to…")
        self.page_input.returnPressed.connect(self._jump_to_page_from_input)
        self._create_menu()
        self._create_toolbar()
        self.viewer.pageChanged.connect(self._update_page_label)

        # Attempt to auto-load last session PDF
        self._load_last_session_pdf()

    def _create_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("File")

        open_action = file_menu.addAction("Open PDF...")
        open_action.triggered.connect(self.open_pdf)

        save_action = file_menu.addAction("Save Annotations")
        save_action.triggered.connect(self.save_annotations)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        nav_menu = menu.addMenu("Navigate")
        prev_act = nav_menu.addAction("Previous Page")
        prev_act.triggered.connect(self.viewer.prev_page)
        next_act = nav_menu.addAction("Next Page")
        next_act.triggered.connect(self.viewer.next_page)
        ai_menu = menu.addMenu("AI")
        profile_act = ai_menu.addAction("Edit Profile / Goal")
        profile_act.triggered.connect(self.edit_profile)
        llm_act = ai_menu.addAction("LLM Auto Highlight")
        llm_act.triggered.connect(self.llm_auto_highlight)
        ai_menu.addSeparator()
        clear_act = ai_menu.addAction("Clear All Highlights…")
        clear_act.triggered.connect(self.clear_all_highlights)

    def _create_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(28, 28))  # larger icons
        tb.setMovable(False)
        self.addToolBar(tb)

        icon_dir = Path(__file__).parent / 'icons'

        def _icon(name: str) -> QIcon:
            p = icon_dir / f"{name}.svg"
            return QIcon(str(p)) if p.exists() else QIcon()

        def add_action(text: str, slot, icon_name: str | None = None, obj_name: str | None = None):
            act = QAction(_icon(icon_name) if icon_name else QIcon(), text, self)
            if obj_name:
                # Will map to a QToolButton via toolbar; setData cannot style so we rely on text matching via stylesheet classes if needed.
                pass
            act.triggered.connect(slot)
            tb.addAction(act)
            return act

        open_act = add_action("Open", self.open_pdf, "open")
        save_act = add_action("Save", self.save_annotations, "save")
        prev_act = add_action("◀", self.viewer.prev_page)
        prev_act.setToolTip("Previous Page (PgUp)")
        next_act = add_action("▶", self.viewer.next_page)
        next_act.setToolTip("Next Page (PgDn)")
        tb.addWidget(self.page_input)
        profile_act = add_action("Profile", self.edit_profile, "profile")
        llm_act = add_action("LLM HL", self.llm_auto_highlight, "llm")
        clear_act = add_action("Clear HLs", self.clear_all_highlights, "clear")
        clear_act.setToolTip("Remove all highlights (manual + auto)")

        # Shortcuts
        prev_act.setShortcut(QKeySequence(Qt.Key.Key_PageUp))
        next_act.setShortcut(QKeySequence(Qt.Key.Key_PageDown))
        go_act = QAction("Go Page", self)
        go_act.setShortcut(QKeySequence("Ctrl+G"))
        go_act.triggered.connect(lambda: self.page_input.setFocus())
        self.addAction(prev_act)
        self.addAction(next_act)
        self.addAction(go_act)

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", str(Path.cwd()), "PDF Files (*.pdf)")
        if not path:
            return
        ann = AnnotationDocument.load(path)
        self.viewer.load_pdf(path, annotations=ann)
        self.panel.set_document(ann)
        self._update_page_label(self.viewer._page_index)
        self._persist_last_pdf(path)

    def save_annotations(self):
        if not self.viewer.annotation_doc:
            QMessageBox.information(self, "Nothing to Save", "Load a PDF and create annotations first.")
            return
        self.viewer.annotation_doc.save()
        QMessageBox.information(self, "Saved", "Annotations saved.")

    def _focus_highlight(self, hl):
        if not self.viewer._pdf:
            return
        # In continuous mode just scroll; in single-page mode re-render.
        if self.viewer.continuous_mode:
            if hl.rects:
                r = hl.rects[0].normalize()
                zoom = self.viewer._zoom
                y_offset = self.viewer._page_offsets.get(hl.page_index, 0.0)
                self.viewer.centerOn(r.x1 * zoom, r.y1 * zoom + y_offset)
            if hl.page_index != self.viewer._page_index:
                self.viewer._page_index = hl.page_index
                self._update_page_label(self.viewer._page_index)
        else:
            if hl.page_index != self.viewer._page_index:
                self.viewer._page_index = hl.page_index
                self.viewer._render_single_page()
                # redraw highlights only for this page
                self.viewer.clear_highlight_items()
                self.viewer._restore_highlights()
            if hl.rects:
                r = hl.rects[0].normalize()
                zoom = self.viewer._zoom
                self.viewer.centerOn(r.x1 * zoom, r.y1 * zoom)
            self._update_page_label(self.viewer._page_index)

    # ---- AI Integration ----
    def edit_profile(self):
        if not self.viewer.annotation_doc:
            QMessageBox.information(self, "No PDF", "Open a PDF first.")
            return
        doc = self.viewer.annotation_doc
        dlg = ProfileDialog(self, global_profile=doc.global_profile or "", document_goal=doc.document_goal or "", density=doc.highlight_density_target)
        if dlg.exec() == ProfileDialog.DialogCode.Accepted:
            doc.global_profile = dlg.global_profile()
            doc.document_goal = dlg.document_goal()
            doc.highlight_density_target = max(0.01, min(0.5, dlg.density()))
            # create snapshot context
            import json
            doc.profile_context = json.dumps({
                "global_profile": doc.global_profile,
                "document_goal": doc.document_goal,
                "density": doc.highlight_density_target,
            })
            # Persist immediately
            try:
                doc.save()
            except Exception as e:
                QMessageBox.warning(self, "Save Error", f"Failed to save profile changes: {e}")
            QMessageBox.information(self, "Profile Saved", "Profile & goal updated (auto-saved).")


    # ---- LLM Auto Highlight ----
    def _init_llm_client(self):
        if self._llm_client is not None:
            return
        try:
            self._llm_client = build_llm_client()
        except Exception as e:
            QMessageBox.critical(self, "LLM Init Failed", f"Azure client initialization failed: {e}")
            self._llm_client = None

    def llm_auto_highlight(self):
        if not self.viewer.annotation_doc or not self.viewer._pdf:
            QMessageBox.information(self, "No PDF", "Open a PDF first.")
            return
        doc = self.viewer.annotation_doc
        if not (doc.global_profile and doc.document_goal):
            QMessageBox.information(self, "Profile Needed", "Set profile and document goal first (AI > Edit Profile / Goal).")
            return
        self._init_llm_client()
        if self._llm_client is None:
            QMessageBox.warning(self, "LLM Error", "Could not initialize LLM client.")
            return
        density = max(0.01, min(0.5, doc.highlight_density_target))
        # Simple progress dialog (indeterminate)
        progress = QProgressDialog("Generating LLM highlights...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        try:
            highlighter = LLMHighlighter(self._llm_client)
            new_highlights = highlighter.generate(doc, doc.pdf_path, density_target=density)
            log_path = getattr(highlighter, 'last_log_path', None)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "LLM Error", f"Failed to generate LLM highlights:\n{e}")
            return
        progress.close()
        if not new_highlights:
            extra = f"\nLog: {log_path}" if log_path else ""
            QMessageBox.information(self, "No Highlights", "LLM produced no relevant highlights (try adjusting density or profile)." + extra)
            return
        added = 0
        for hl in new_highlights:
            if any((existing.extracted_text == hl.extracted_text and existing.page_index == hl.page_index) for existing in doc.highlights):
                continue
            doc.add_highlight(hl)
            # Always draw highlight in continuous mode; otherwise only if on current page
            if self.viewer.continuous_mode or hl.page_index == self.viewer._page_index:
                self.viewer._draw_highlight(hl)
            added += 1
        self.panel.refresh_list()
        msg = f"Added {added} new highlights (scored by model)."
        if log_path:
            msg += f"\nLog saved to: {log_path}"
        QMessageBox.information(self, "LLM Auto Highlight", msg)
        # Auto-save after generation
        try:
            doc.save()
        except Exception:
            pass

    # ---- Clear All Highlights ----
    def clear_all_highlights(self):
        if not self.viewer.annotation_doc:
            QMessageBox.information(self, "No PDF", "Open a PDF first.")
            return
        doc = self.viewer.annotation_doc
        if not doc.highlights:
            QMessageBox.information(self, "No Highlights", "There are no highlights to clear.")
            return
        reply = QMessageBox.question(self, "Confirm Clear", "Remove ALL highlights (manual and auto-generated)? This cannot be undone.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        count = len(doc.highlights)
        doc.clear_highlights()
        # Re-render current page (remove overlay items)
        if self.viewer._pdf:
            if self.viewer.continuous_mode:
                # Remove highlight items only
                self.viewer.clear_highlight_items()
                # Re-draw remaining highlights (there will be none after clear)
            else:
                self.viewer._render_single_page()
        self.panel.refresh_list()
        try:
            doc.save()
        except Exception:
            pass
        QMessageBox.information(self, "Cleared", f"Removed {count} highlights.")

    # ---- Navigation helpers ----
    def _update_page_label(self, page_index: int):
        if not self.viewer._pdf:
            self.page_label.setText("Page: -/-")
            return
        total = self.viewer._pdf.page_count()
        self.page_label.setText(f"Page: {page_index+1}/{total}")

    def _jump_to_page_from_input(self):
        if not self.viewer._pdf:
            return
        text = self.page_input.text().strip()
        if not text:
            return
        try:
            num = int(text)
        except ValueError:
            self.statusBar().showMessage("Invalid page number", 3000)
            return
        total = self.viewer._pdf.page_count()
        if not (1 <= num <= total):
            self.statusBar().showMessage("Page out of range", 3000)
            return
        if (num - 1) != self.viewer._page_index:
            self.viewer._page_index = num - 1
            self.viewer._render_current_page()
            self.viewer._restore_highlights()
        self._update_page_label(self.viewer._page_index)
        self.statusBar().showMessage(f"Jumped to page {num}", 1500)

    # ---- Persistence helpers ----
    def _state_file_path(self) -> str:
        from pathlib import Path as _P
        base = _P.home() / ".readingcopilot"
        base.mkdir(exist_ok=True)
        return str(base / "app_state.json")

    def _persist_last_pdf(self, pdf_path: str):
        import json
        state = {"last_pdf": pdf_path}
        try:
            with open(self._state_path, 'w', encoding='utf-8') as f:
                json.dump(state, f)
        except Exception:
            pass

    def _load_last_session_pdf(self):
        import json
        try:
            with open(self._state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            last_pdf = state.get("last_pdf")
            if last_pdf and Path(last_pdf).exists():
                ann = AnnotationDocument.load(last_pdf)
                self.viewer.load_pdf(last_pdf, annotations=ann)
                self.panel.set_document(ann)
                self._update_page_label(self.viewer._page_index)
        except Exception:
            pass

    def closeEvent(self, event):  # noqa: N802
        # Save on exit
        try:
            if self.viewer.annotation_doc:
                self.viewer.annotation_doc.save()
        except Exception:
            pass
        super().closeEvent(event)


def run():
    app = QApplication(sys.argv)
    # Apply global stylesheet
    try:
        style_path = Path(__file__).parent / 'style.qss'
        if style_path.exists():
            with open(style_path, 'r', encoding='utf-8') as f:
                app.setStyleSheet(f.read())
    except Exception:
        pass
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()
