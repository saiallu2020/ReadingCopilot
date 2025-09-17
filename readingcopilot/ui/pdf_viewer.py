from __future__ import annotations
from typing import List, Callable, Optional
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem
from PySide6.QtGui import QPixmap, QImage, QPen, QColor, QBrush, QMouseEvent, QPainter
from PySide6.QtCore import Qt, QRectF, Signal, QPointF

from readingcopilot.core.annotations import Rect, Highlight, AnnotationDocument
from readingcopilot.core.pdf_loader import PDFDocument

class HighlightGraphicsRect(QGraphicsRectItem):
    def __init__(self, rect: QRectF, color: QColor):
        super().__init__(rect)
        self.setBrush(QBrush(color, Qt.BrushStyle.SolidPattern))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setOpacity(0.35)

class PDFViewer(QGraphicsView):
    highlightCreated = Signal(Highlight)
    pageChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._pdf: Optional[PDFDocument] = None
        self._page_index: int = 0
        self._scale: float = 1.0
        self._page_pixmap_item = None
        self._drag_start: Optional[QPointF] = None
        self._rubber_band_rect: Optional[QGraphicsRectItem] = None
        self.annotation_doc: Optional[AnnotationDocument] = None
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setMouseTracking(True)

    def load_pdf(self, path: str, annotations: Optional[AnnotationDocument] = None):
        if self._pdf:
            self._pdf.close()
        self._pdf = PDFDocument(path)
        self.annotation_doc = annotations or AnnotationDocument.load(path)
        self._page_index = 0
        self._render_current_page()
        self._restore_highlights()

    def _render_current_page(self):
        if not self._pdf:
            return
        try:
            img, w, h = self._pdf.render_page(self._page_index, zoom=1.3)
        except RuntimeError as e:
            # If rendering backend unavailable, show placeholder scene.
            scene = self.scene()
            scene.clear()
            # QGraphicsTextItem imported at module top
            item = QGraphicsTextItem(str(e))
            scene.addItem(item)
            self.setSceneRect(QRectF(0, 0, 800, 600))
            self.pageChanged.emit(self._page_index)
            return
        pix = QPixmap.fromImage(img)
        scene = self.scene()
        scene.clear()
        self._page_pixmap_item = scene.addPixmap(pix)
        self.setSceneRect(QRectF(0, 0, pix.width(), pix.height()))
        self.pageChanged.emit(self._page_index)

    def next_page(self):
        if not self._pdf:
            return
        if self._page_index + 1 < self._pdf.page_count():
            self._page_index += 1
            self._render_current_page()
            self._restore_highlights()

    def prev_page(self):
        if not self._pdf:
            return
        if self._page_index > 0:
            self._page_index -= 1
            self._render_current_page()
            self._restore_highlights()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self.mapToScene(event.pos())
            if self._rubber_band_rect:
                self.scene().removeItem(self._rubber_band_rect)
            self._rubber_band_rect = QGraphicsRectItem()
            pen = QPen(QColor(255, 215, 0))
            pen.setStyle(Qt.PenStyle.DashLine)
            self._rubber_band_rect.setPen(pen)
            self.scene().addItem(self._rubber_band_rect)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start and self._rubber_band_rect:
            current = self.mapToScene(event.pos())
            rect = QRectF(self._drag_start, current).normalized()
            self._rubber_band_rect.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start and self._rubber_band_rect:
            rect = self._rubber_band_rect.rect()
            self.scene().removeItem(self._rubber_band_rect)
            self._rubber_band_rect = None
            self._create_highlight_from_rect(rect)
            self._drag_start = None
        super().mouseReleaseEvent(event)

    def _create_highlight_from_rect(self, rect: QRectF):
        if not self.annotation_doc:
            return
        # Convert scene rect to PDF coordinates (approx). We rendered with zoom 1.3 so divide by 1.3.
        zoom = 1.3
        pdf_rect = Rect(x1=rect.left()/zoom, y1=rect.top()/zoom, x2=rect.right()/zoom, y2=rect.bottom()/zoom)
        highlight = Highlight(page_index=self._page_index, rects=[pdf_rect])
        self.annotation_doc.add_highlight(highlight)
        self._draw_highlight(highlight)
        self.highlightCreated.emit(highlight)

    def _draw_highlight(self, highlight: Highlight):
        if highlight.page_index != self._page_index:
            return
        zoom = 1.3
        for r in highlight.rects:
            x1, y1, x2, y2 = r.normalize().to_tuple()
            rect = QRectF(x1*zoom, y1*zoom, (x2-x1)*zoom, (y2-y1)*zoom)
            item = HighlightGraphicsRect(rect, QColor(*highlight.color))
            self.scene().addItem(item)

    def _restore_highlights(self):
        if not self.annotation_doc:
            return
        for hl in self.annotation_doc.highlights:
            self._draw_highlight(hl)
