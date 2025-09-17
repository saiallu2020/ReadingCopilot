from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Iterable
import re
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


SENTENCE_REGEX = re.compile(r"(?<!\b[A-Z])(?<=[.!?])\s+(?=[A-Z0-9])")

def split_into_sentences(text: str) -> List[str]:
    """Split text into sentences conservatively.

    Uses a regex that attempts not to split on common abbreviations (rough heuristic: avoids single capital letter before period rule by negative lookbehind).
    Falls back to the whole text if no boundary found.
    """
    raw = text.strip()
    if not raw:
        return []
    parts = SENTENCE_REGEX.split(raw)
    # Clean & keep non-empty
    return [p.strip() for p in parts if p.strip()]

def extract_chunks(pdf_path: str, max_chars: int = 1200, merge_distance: float = 12.0, invert_y: bool = True) -> List[TextChunk]:
    """Extract textual chunks with approximate bounding boxes at sentence granularity.

    Strategy:
      1. Collect lines with geometry.
      2. Form 'paragraph buffers' separated by vertical gaps (> merge_distance) OR blank lines.
      3. Within each paragraph buffer, split text into sentences.
      4. Accumulate sentences into chunks without exceeding max_chars; never cut a sentence or word mid-unit.
      5. Rect list for a chunk = union of the paragraph's line rects (coarse but stable).
    """
    chunks: List[TextChunk] = []
    chunk_id = 0
    reader = PdfReader(pdf_path)
    page_heights: List[float] = []
    for p in reader.pages:
        mb = p.mediabox
        h = float(mb.top) - float(mb.bottom)
        page_heights.append(h)

    for page_index, page_layout in enumerate(extract_pages(pdf_path)):
        paragraph_lines: List[Tuple[str, Tuple[float, float, float, float]]] = []
        last_bottom = None

        def flush_paragraph():
            nonlocal chunk_id  # we mutate chunk_id
            nonlocal paragraph_lines  # just to be explicit (allowed since defined in enclosing function scope)
            if not paragraph_lines:
                return
            para_text = "".join(l for l, _ in paragraph_lines)
            sentences = split_into_sentences(para_text)
            if not sentences:
                paragraph_lines = []
                return
            line_rects = [r for _, r in paragraph_lines]
            current_sent_parts: List[str] = []
            current_rects: List[Tuple[float, float, float, float]] = []
            current_chars = 0
            for sent in sentences:
                sent_len = len(sent)
                if current_chars + sent_len > max_chars and current_chars > 0:
                    chunks.append(TextChunk(
                        id=chunk_id,
                        page_index=page_index,
                        text=" ".join(current_sent_parts).strip(),
                        rects=current_rects.copy(),
                        char_count=current_chars
                    ))
                    chunk_id += 1
                    current_sent_parts = []
                    current_rects = []
                    current_chars = 0
                current_sent_parts.append(sent)
                for r in line_rects:
                    if r not in current_rects:
                        current_rects.append(r)
                current_chars += sent_len
            if current_chars > 0:
                chunks.append(TextChunk(
                    id=chunk_id,
                    page_index=page_index,
                    text=" ".join(current_sent_parts).strip(),
                    rects=current_rects.copy(),
                    char_count=current_chars
                ))
                chunk_id += 1
            paragraph_lines = []

        for line in _iter_text_lines(page_layout):
            raw_line = line.get_text()
            if not raw_line.strip():
                flush_paragraph()
                continue
            x0, y0, x1, y1 = line.bbox
            if invert_y:
                page_h = page_heights[page_index]
                new_y0 = page_h - y1
                new_y1 = page_h - y0
                y0, y1 = new_y0, new_y1
            if last_bottom is not None and (y0 > last_bottom + merge_distance):
                flush_paragraph()
            paragraph_lines.append((raw_line, (x0, y0, x1, y1)))
            last_bottom = y0
        flush_paragraph()
    return chunks
