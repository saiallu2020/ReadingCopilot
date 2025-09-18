from __future__ import annotations
from typing import Optional
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QTextEdit, QLabel
from PySide6.QtCore import Qt, Signal
from readingcopilot.core.annotations import Highlight, AnnotationDocument
from readingcopilot.core.keywords import extract_keywords

class AnnotationPanel(QWidget):
    highlightSelected = Signal(Highlight)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Optional[AnnotationDocument] = None
        self._current: Optional[Highlight] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Highlights"))
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list_widget, 2)

        layout.addWidget(QLabel("Reading Notes"))
        self.note_edit = QTextEdit()
        self.note_edit.textChanged.connect(self._on_note_changed)
        layout.addWidget(self.note_edit, 3)

    def set_document(self, doc: AnnotationDocument):
        self.doc = doc
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        if not self.doc:
            return
        # ensure highlights are in a stable, sorted order by page index
        self.doc.highlights = sorted(self.doc.highlights, key=lambda hl: hl.page_index)
        for hl in self.doc.highlights:
            # Populate missing notes (e.g., legacy saved highlights) using heuristic keywords
            if (not hl.note) and hl.extracted_text:
                kw = extract_keywords(hl.extracted_text, max_keywords=4)
                if kw:
                    hl.note = "; ".join(kw)
            item = QListWidgetItem(f"Page {hl.page_index+1} - {hl.note[:30] if hl.note else 'No note'}")
            item.setData(Qt.ItemDataRole.UserRole, hl)
            self.list_widget.addItem(item)

    def add_highlight(self, hl: Highlight):
        if not self.doc:
            return
        item = QListWidgetItem(f"Page {hl.page_index+1} - {hl.note[:30] if hl.note else 'No note'}")
        item.setData(Qt.ItemDataRole.UserRole, hl)
        self.list_widget.addItem(item)

    def _on_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            return
        hl = current.data(Qt.ItemDataRole.UserRole)
        self._current = hl
        self.note_edit.blockSignals(True)
        self.note_edit.setPlainText(hl.note or "")
        self.note_edit.blockSignals(False)
        self.highlightSelected.emit(hl)

    def _on_note_changed(self):
        if self._current:
            self._current.update_note(self.note_edit.toPlainText())
            self.refresh_list()
