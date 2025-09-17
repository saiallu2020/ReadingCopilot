from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Iterable
from pypdf import PdfReader  # leverage already-installed dependency for page size

try:
    from pdfminer.high_level import extract_pages  # type: ignore
    from pdfminer.layout import LTTextContainer, LTTextLine  # type: ignore
except Exception as e:  # pragma: no cover - environment dependent
    raise ImportError(
        "pdfminer.six is required for LLM highlighting. Install with 'pip install pdfminer.six'."
        f" (Import error: {e})"
    )

@dataclass
class TextChunk:
    id: int
    page_index: int
    text: str
    rects: List[Tuple[float,float,float,float]]  # list of (x1,y1,x2,y2)
    char_count: int


def _iter_text_lines(layout_obj) -> Iterable[LTTextLine]:
    if isinstance(layout_obj, LTTextLine):
        yield layout_obj
    elif isinstance(layout_obj, LTTextContainer):
        for line in layout_obj:
            yield from _iter_text_lines(line)
    else:
        if hasattr(layout_obj, '__iter__'):
            for child in layout_obj:
                yield from _iter_text_lines(child)


def extract_chunks(pdf_path: str, max_chars: int = 1200, merge_distance: float = 12.0, invert_y: bool = True) -> List[TextChunk]:
    """Extract textual chunks with approximate bounding boxes.

    Strategy:
      - Iterate pages
      - Collect lines (LTTextLine) and their bounding boxes
      - Merge consecutive lines into a chunk until max_chars exceeded
    """
    chunks: List[TextChunk] = []
    chunk_id = 0
    # Preload page heights for coordinate inversion (pdfminer uses origin bottom-left, viewer expects top-left y increasing down)
    reader = PdfReader(pdf_path)
    page_heights: List[float] = []
    for p in reader.pages:
        mb = p.mediabox
        h = float(mb.top) - float(mb.bottom)
        page_heights.append(h)

    for page_index, page_layout in enumerate(extract_pages(pdf_path)):
        current_text_parts: List[str] = []
        current_rects: List[Tuple[float,float,float,float]] = []
        current_chars = 0
        last_bottom = None
        for line in _iter_text_lines(page_layout):
            line_text = line.get_text()
            if not line_text.strip():
                continue
            # bounding box
            x0, y0, x1, y1 = line.bbox  # pdfminer: (x0,y0,x1,y1) with origin bottom-left
            if invert_y:
                page_h = page_heights[page_index]
                # Convert to top-left origin: new_y0 = page_h - old_y1, new_y1 = page_h - old_y0
                new_y0 = page_h - y1
                new_y1 = page_h - y0
                y0, y1 = new_y0, new_y1
            line_chars = len(line_text)
            new_para = False
            if last_bottom is not None and (y0 > last_bottom + merge_distance):
                new_para = True
            if current_chars + line_chars > max_chars or new_para:
                if current_chars > 0:
                    chunks.append(TextChunk(
                        id=chunk_id,
                        page_index=page_index,
                        text="".join(current_text_parts).strip(),
                        rects=current_rects.copy(),
                        char_count=current_chars
                    ))
                    chunk_id += 1
                current_text_parts = []
                current_rects = []
                current_chars = 0
            current_text_parts.append(line_text)
            current_rects.append((x0, y0, x1, y1))
            current_chars += line_chars
            last_bottom = y0
        # flush page
        if current_chars > 0:
            chunks.append(TextChunk(
                id=chunk_id,
                page_index=page_index,
                text="".join(current_text_parts).strip(),
                rects=current_rects.copy(),
                char_count=current_chars
            ))
            chunk_id += 1
    return chunks
