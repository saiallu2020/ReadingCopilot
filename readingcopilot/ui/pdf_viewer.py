from __future__ import annotations
from typing import List, Callable, Optional, Dict, Tuple
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem, QGraphicsPixmapItem
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
        self._scale: float = 1.0  # unused in current fixed zoom pipeline
        self._zoom: float = 1.3
        self._page_pixmap_item = None  # legacy single-page reference
        self._page_items: List[Tuple[int, 'QGraphicsPixmapItem']] = []  # (page_index, item)
        self._page_offsets: Dict[int, float] = {}  # page_index -> y offset (scene coords, unscaled already applied)
        self.continuous_mode: bool = True  # enable stacked pages with smooth scrolling
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
        self._render_document()
        self._restore_highlights()

    def _render_single_page(self):
        """Legacy single-page render (used if continuous_mode is False)."""
        if not self._pdf:
            return
        try:
            img, w, h = self._pdf.render_page(self._page_index, zoom=self._zoom)
        except RuntimeError as e:
            scene = self.scene(); scene.clear()
            item = QGraphicsTextItem(str(e)); scene.addItem(item)
            self.setSceneRect(QRectF(0, 0, 800, 600))
            self.pageChanged.emit(self._page_index)
            return
        pix = QPixmap.fromImage(img)
        scene = self.scene(); scene.clear()
        self._page_pixmap_item = scene.addPixmap(pix)
        self.setSceneRect(QRectF(0, 0, pix.width(), pix.height()))
        self.pageChanged.emit(self._page_index)

    def _render_all_pages(self):
        if not self._pdf:
            return
        scene = self.scene(); scene.clear()
        self._page_items.clear()
        self._page_offsets.clear()
        y_cursor = 0.0
        max_width = 0.0
        for idx in range(self._pdf.page_count()):
            try:
                img, w, h = self._pdf.render_page(idx, zoom=self._zoom)
            except RuntimeError as e:
                # Represent missing page with placeholder text
                placeholder = QGraphicsTextItem(f"Render error page {idx+1}: {e}")
                placeholder.setPos(10, y_cursor + 10)
                scene.addItem(placeholder)
                self._page_offsets[idx] = y_cursor
                y_cursor += 600  # arbitrary fallback height
                continue
            pix = QPixmap.fromImage(img)
            item = scene.addPixmap(pix)
            item.setPos(0, y_cursor)
            self._page_offsets[idx] = y_cursor
            self._page_items.append((idx, item))
            y_cursor += pix.height() + 20  # gap between pages
            max_width = max(max_width, pix.width())
        self.setSceneRect(QRectF(0, 0, max_width, y_cursor))
        self.pageChanged.emit(self._page_index)

    def _render_document(self):
        if self.continuous_mode:
            self._render_all_pages()
        else:
            self._render_single_page()

    def next_page(self):
        if not self._pdf:
            return
        if self._page_index + 1 < self._pdf.page_count():
            self._page_index += 1
            if self.continuous_mode:
                # Scroll to page top
                self.centerOn(0, self._page_offsets.get(self._page_index, 0) + 10)
            else:
                self._render_single_page(); self._restore_highlights()
            self.pageChanged.emit(self._page_index)

    def prev_page(self):
        if not self._pdf:
            return
        if self._page_index > 0:
            self._page_index -= 1
            if self.continuous_mode:
                self.centerOn(0, self._page_offsets.get(self._page_index, 0) + 10)
            else:
                self._render_single_page(); self._restore_highlights()
            self.pageChanged.emit(self._page_index)

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
        # Determine page index in continuous mode by y position
        page_index = self._page_index
        if self.continuous_mode and self._page_offsets:
            top_y = rect.top()
            # Find the page whose offset range contains top_y
            for idx in sorted(self._page_offsets.keys()):
                y_off = self._page_offsets[idx]
                # Determine page height from next offset (or scene bottom)
                next_off = self._page_offsets.get(idx + 1, y_off + 10**6)
                if y_off <= top_y < next_off:
                    page_index = idx
                    break
        zoom = self._zoom
        # Adjust rect relative to page origin for storage
        page_offset_y = self._page_offsets.get(page_index, 0.0) if self.continuous_mode else 0.0
        rel_top = (rect.top() - page_offset_y) / zoom
        rel_left = rect.left() / zoom
        rel_bottom = (rect.bottom() - page_offset_y) / zoom
        rel_right = rect.right() / zoom
        pdf_rect = Rect(x1=rel_left, y1=rel_top, x2=rel_right, y2=rel_bottom)
        highlight = Highlight(page_index=page_index, rects=[pdf_rect])
        self.annotation_doc.add_highlight(highlight)
        self._draw_highlight(highlight)
        self.highlightCreated.emit(highlight)

    def _draw_highlight(self, highlight: Highlight):
        # In single-page mode only draw current page highlights
        if not self.continuous_mode and highlight.page_index != self._page_index:
            return
        zoom = self._zoom
        y_offset = self._page_offsets.get(highlight.page_index, 0.0) if self.continuous_mode else 0.0
        for r in highlight.rects:
            x1, y1, x2, y2 = r.normalize().to_tuple()
            rect = QRectF(x1*zoom, y1*zoom + y_offset, (x2-x1)*zoom, (y2-y1)*zoom)
            item = HighlightGraphicsRect(rect, QColor(*highlight.color))
            self.scene().addItem(item)

    def _restore_highlights(self):
        if not self.annotation_doc:
            return
        for hl in self.annotation_doc.highlights:
            self._draw_highlight(hl)

    def scroll_to_page(self, page_index: int):
        if not self._pdf:
            return
        if 0 <= page_index < self._pdf.page_count():
            self._page_index = page_index
            if self.continuous_mode:
                self.centerOn(0, self._page_offsets.get(page_index, 0) + 10)
                self.pageChanged.emit(self._page_index)
            else:
                self._render_single_page(); self._restore_highlights()

    def clear_highlight_items(self):
        scene = self.scene()
        for item in list(scene.items()):
            if isinstance(item, HighlightGraphicsRect):
                scene.removeItem(item)

    def wheelEvent(self, event):  # noqa: N802
        if not self._pdf:
            return super().wheelEvent(event)
        super().wheelEvent(event)
        if self.continuous_mode:
            self._update_visible_page()

    def _update_visible_page(self):
        if not self._pdf or not self._page_offsets:
            return
        # Use vertical center of viewport to choose page
        vr = self.viewport().rect()
        center_scene = self.mapToScene(vr.center())
        y = center_scene.y()
        # Find page whose offset range contains y
        current = self._page_index
        sorted_offsets = sorted(self._page_offsets.items())
        for idx, off in sorted_offsets:
            next_off = self._page_offsets.get(idx + 1, float('inf'))
            if off <= y < next_off:
                if idx != current:
                    self._page_index = idx
                    self.pageChanged.emit(self._page_index)
                break
