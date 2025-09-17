from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class Interest(BaseModel):
    name: str
    keywords: List[str] = []
    weight: float = 1.0

class Profile(BaseModel):
    id: str
    description: str
    interests: List[Interest] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None

    def touch(self):
        self.updated_at = datetime.utcnow()

    def all_keywords(self) -> List[str]:
        kws = []
        for i in self.interests:
            kws.extend(i.keywords)
        return kws
