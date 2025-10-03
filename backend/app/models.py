from __future__ import annotations
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

# Reuse shapes close to desktop version for parity
class Rect(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    def normalize(self) -> 'Rect':
        x1, x2 = sorted([self.x1, self.x2])
        y1, y2 = sorted([self.y1, self.y2])
        return Rect(x1=x1, y1=y1, x2=x2, y2=y2)

class Highlight(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    page_index: int
    rects: List[Rect]
    color: Tuple[int, int, int] = (255, 255, 0)
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    profile_score: Optional[float] = None
    extracted_text: Optional[str] = None
    auto_generated: bool = False

class AnnotationDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    pdf_path: str
    highlights: List[Highlight] = []
    global_profile: Optional[str] = None
    document_goal: Optional[str] = None
    highlight_density_target: float = 0.10
    version: int = 1

class UploadResponse(BaseModel):
    document_id: str
    filename: str

class ProfileUpdate(BaseModel):
    global_profile: str
    document_goal: str
    highlight_density_target: float

class ManualHighlightIn(BaseModel):
    page_index: int
    rects: List[Rect]
    note: Optional[str] = None

class AutoHLRequest(BaseModel):
    density: Optional[float] = None
    min_threshold: Optional[float] = None
    pages: Optional[str] = None  # e.g. "3-5,9"

class AutoHLStatus(BaseModel):
    run_id: str
    state: str
    emitted: int

class AutoHLChunk(BaseModel):
    highlight: Highlight
    done: bool = False
    cancelled: bool = False
