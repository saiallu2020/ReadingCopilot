from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QWidget, QHBoxLayout, QSplitter,
    QMessageBox, QToolBar, QProgressDialog, QLineEdit, QLabel, QStatusBar, QInputDialog
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
        self._create_toolbar()
        self.viewer.pageChanged.connect(self._update_page_label)

        # Attempt to auto-load last session PDF
        self._load_last_session_pdf()

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
        profile_act = add_action("Profile", self.edit_profile, "profile")
        llm_act = add_action("LLM HL", self.llm_auto_highlight, "llm")
        # Attach right-click (context menu) for page-range highlighting
        def _configure_llm_btn():
            btn = tb.widgetForAction(llm_act)
            if not btn:
                return
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _: self._prompt_llm_page_range())
            btn.setToolTip("Left-click: highlight whole doc. Right-click: highlight specific page range.")
        # Defer configuration to ensure action widget exists
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _configure_llm_btn)
        clear_act = add_action("Clear HLs", self.clear_all_highlights, "clear")
        clear_act.setToolTip("Remove all highlights (manual + auto)")

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

    def _prompt_llm_page_range(self):
        """Prompt user for a page range and run LLM highlighting on that subset."""
        if not self.viewer.annotation_doc or not self.viewer._pdf:
            QMessageBox.information(self, "No PDF", "Open a PDF first.")
            return
        total = self.viewer._pdf.page_count()
        text, ok = QInputDialog.getText(self, "LLM Highlight Page Range", f"Enter pages (1-{total}) e.g. 3-6,9,12-13:")
        if not ok or not text.strip():
            return
        try:
            page_set = self._parse_page_range(text.strip(), total)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Range", str(e))
            return
        if not page_set:
            QMessageBox.information(self, "No Pages", "No valid pages selected.")
            return
        # Proceed with filtered generation
        doc = self.viewer.annotation_doc
        if not (doc.global_profile and doc.document_goal):
            QMessageBox.information(self, "Profile Needed", "Set profile and document goal first (AI > Edit Profile / Goal).")
            return
        self._init_llm_client()
        if self._llm_client is None:
            QMessageBox.warning(self, "LLM Error", "Could not initialize LLM client.")
            return
        density = max(0.01, min(0.5, doc.highlight_density_target))
        progress = QProgressDialog("Generating LLM highlights (selected pages)...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        try:
            highlighter = LLMHighlighter(self._llm_client)
            new_highlights = highlighter.generate(doc, doc.pdf_path, density_target=density, page_filter=page_set)
            log_path = getattr(highlighter, 'last_log_path', None)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "LLM Error", f"Failed to generate LLM highlights:\n{e}")
            return
        progress.close()
        if not new_highlights:
            extra = f"\nLog: {log_path}" if log_path else ""
            QMessageBox.information(self, "No Highlights", "LLM produced no relevant highlights for selected pages." + extra)
            return
        added = 0
        for hl in new_highlights:
            if any((existing.extracted_text == hl.extracted_text and existing.page_index == hl.page_index) for existing in doc.highlights):
                continue
            doc.add_highlight(hl)
            if self.viewer.continuous_mode or hl.page_index == self.viewer._page_index:
                self.viewer._draw_highlight(hl)
            added += 1
        self.panel.refresh_list()
        info_pages = ", ".join(str(p+1) for p in sorted(page_set))
        msg = f"Added {added} new highlights for pages: {info_pages}."
        if log_path:
            msg += f"\nLog saved to: {log_path}"
        QMessageBox.information(self, "LLM Auto Highlight (Range)", msg)
        try:
            doc.save()
        except Exception:
            pass

    @staticmethod
    def _parse_page_range(spec: str, total_pages: int) -> set[int]:
        """Parse a page range spec (1-based numbers) into a zero-based set.

        Accepts forms like: '3-6,9,12-13'. Raises ValueError on invalid tokens.
        Ignores whitespace. Ensures pages within 1..total_pages.
        """
        pages: set[int] = set()
        if not spec:
            return pages
        parts = [p.strip() for p in spec.split(',') if p.strip()]
        for part in parts:
            if '-' in part:
                a, b, *rest = part.split('-')
                if rest:
                    raise ValueError(f"Invalid range segment: {part}")
                if not a.isdigit() or not b.isdigit():
                    raise ValueError(f"Invalid number in segment: {part}")
                start = int(a); end = int(b)
                if start > end:
                    start, end = end, start
                if start < 1 or end > total_pages:
                    raise ValueError(f"Range {start}-{end} out of bounds (1-{total_pages})")
                for v in range(start, end+1):
                    pages.add(v-1)
            else:
                if not part.isdigit():
                    raise ValueError(f"Invalid page number: {part}")
                v = int(part)
                if v < 1 or v > total_pages:
                    raise ValueError(f"Page {v} out of bounds (1-{total_pages})")
                pages.add(v-1)
        return pages

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
