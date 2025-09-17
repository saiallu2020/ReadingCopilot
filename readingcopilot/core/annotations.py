from __future__ import annotations
from typing import List, Optional, Tuple, Any
from pydantic import BaseModel, Field
from datetime import datetime
import json
import uuid

# Coordinate system: page-relative, float values in PDF points (72 dpi), rectangle = (x1, y1, x2, y2)

class Rect(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    def normalize(self) -> 'Rect':
        x1, x2 = sorted([self.x1, self.x2])
        y1, y2 = sorted([self.y1, self.y2])
        return Rect(x1=x1, y1=y1, x2=x2, y2=y2)

    def to_tuple(self) -> Tuple[float, float, float, float]:
        r = self.normalize()
        return r.x1, r.y1, r.x2, r.y2

class Highlight(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    page_index: int
    rects: List[Rect]  # multi-rect highlight (support for text across wrapped lines)
    color: Tuple[int, int, int] = (255, 255, 0)  # RGB
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    tags: List[str] = []
    profile_score: Optional[float] = None  # future AI relevance score
    extracted_text: Optional[str] = None   # text captured inside highlight (future population)
    auto_generated: bool = False           # whether created by auto highlighter

    def update_note(self, note: str):
        self.note = note
        self.updated_at = datetime.utcnow()

class AnnotationDocument(BaseModel):
    pdf_path: str
    highlights: List[Highlight] = []
    profile_context: Optional[str] = None  # JSON snapshot of profile & doc goal & density settings
    global_profile: Optional[str] = None   # 150-word general background/profile
    document_goal: Optional[str] = None    # 150-word PDF-specific goal
    highlight_density_target: float = 0.10 # target fraction (0.01 .. 0.5) user preference
    version: int = 1

    def add_highlight(self, highlight: Highlight):
        self.highlights.append(highlight)

    def clear_highlights(self):
        """Remove all highlights from the document.

        Caller is responsible for persisting via save()."""
        self.highlights.clear()

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(indent=2, **kwargs)

    @staticmethod
    def from_json(data: str) -> 'AnnotationDocument':
        return AnnotationDocument.model_validate_json(data)

    def save(self, path: Optional[str] = None):
        path = path or self._default_annotations_path()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, pdf_path: str, path: Optional[str] = None) -> 'AnnotationDocument':
        inst_path = path or cls._default_annotations_path_for(pdf_path)
        try:
            with open(inst_path, 'r', encoding='utf-8') as f:
                return cls.from_json(f.read())
        except FileNotFoundError:
            return AnnotationDocument(pdf_path=pdf_path)

    def _default_annotations_path(self) -> str:
        return self._default_annotations_path_for(self.pdf_path)

    @staticmethod
    def _default_annotations_path_for(pdf_path: str) -> str:
        return pdf_path + '.annotations.json'

# FUTURE: Positional Text Mapping Strategy
# 1. Use pdfminer.six or pdfplumber to extract per-character or per-word bounding boxes.
# 2. For each Highlight.rect, find intersecting words and concatenate in reading order.
# 3. Store extracted_text: Optional[str] in Highlight (add new field + migration step if necessary).
# 4. Use extracted_text for relevance scoring against Profile interests (keyword + embedding pipelines).
