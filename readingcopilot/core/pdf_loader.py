from __future__ import annotations
from typing import List, Tuple, Optional
try:
    from pypdf import PdfReader  # type: ignore
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Missing dependency 'pypdf'. Activate your virtual environment and run 'pip install -r requirements.txt'. "
        "If already installed, ensure you're not invoking system Python instead of the venv."
    ) from e

"""pdf_loader

Refactored to use pypdf for text extraction and structural info. For rendering, PyPDF does not rasterize pages, so we rely on QtPdf (if available) or a fallback minimal renderer.

Strategy:
 - Use QPdfDocument (Qt6's QtPdf module) when present for page rendering.
 - If QtPdf is not installed with the PySide6 distribution, we provide a placeholder that raises a helpful error.
 - Coordinate system: pypdf exposes mediabox in default PDF units (points). We adopt those directly (same as previous implementation) so existing annotations remain valid.

Limitations vs PyMuPDF:
 - No direct per-block coordinates without extra parsing. Future enhancement: integrate pdfminer.six or pdfplumber for positional text mapping.
"""

try:
    from PySide6.QtPdf import QPdfDocument  # type: ignore
    from PySide6.QtGui import QImage
    HAVE_QPDF = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_QPDF = False
    QPdfDocument = None  # type: ignore
    QImage = None  # type: ignore


class PDFDocument:
    def __init__(self, path: str):
        self.path = path
        self.reader = PdfReader(path)
        self._qpdf: Optional[QPdfDocument] = None
        if HAVE_QPDF:
            self._qpdf = QPdfDocument()
            status = self._qpdf.load(path)
            # status 0 = success; ignore others for now

    # ---- Basic Metadata ----
    def page_count(self) -> int:
        return len(self.reader.pages)

    def get_page_size(self, index: int) -> Tuple[float, float]:
        page = self.reader.pages[index]
        mb = page.mediabox
        width = float(mb.right) - float(mb.left)
        height = float(mb.top) - float(mb.bottom)
        return width, height

    # ---- Rendering ----
    def render_page(self, index: int, zoom: float = 1.3):
        """Render a page to QImage, returning (image, width, height).

        With QtPdf available we can render natively. Otherwise we raise an informative error.
        Future fallback: integrate pillow + ghostscript/poppler for headless rasterization if needed.
        """
        if not HAVE_QPDF or self._qpdf is None:
            raise RuntimeError("QtPdf (QPdfDocument) not available in this PySide6 build. Install PySide6-Essentials with QtPdf support.")
        from PySide6.QtCore import QSize
        page_size = self._qpdf.pagePointSize(index)
        target_w = max(1, int(page_size.width() * zoom))
        target_h = max(1, int(page_size.height() * zoom))
        size = QSize(target_w, target_h)
        # QPdfDocument.render returns a QImage in this signature
        img = self._qpdf.render(index, size)
        if img.isNull():  # pragma: no cover
            raise RuntimeError("Failed to render PDF page: received null image from QPdfDocument.render")
        return img, target_w, target_h

    # ---- Text Extraction ----
    def extract_text_blocks(self, index: int):
        """Return a naive single block of full page text.

        pypdf does not yield positioned blocks. We return a list with one synthetic block:
        [(0, 0, width, height, text, 0, 0)] to maintain prior interface compatibility.
        """
        width, height = self.get_page_size(index)
        page = self.reader.pages[index]
        text = page.extract_text() or ""
        return [(0.0, 0.0, width, height, text, 0, 0)]

    def close(self):
        # pypdf has no explicit close; kept for interface symmetry
        pass
