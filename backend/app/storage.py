from __future__ import annotations
import os, json, threading
from typing import Dict
from .models import AnnotationDocument

_STORAGE_LOCK = threading.RLock()

class DocStore:
    def __init__(self, base: str = "storage"):
        self.base = base
        os.makedirs(self.base, exist_ok=True)
        self._docs: Dict[str, AnnotationDocument] = {}
        self._load_index()

    def _index_path(self):
        return os.path.join(self.base, 'index.json')

    def _load_index(self):
        try:
            with open(self._index_path(), 'r', encoding='utf-8') as f:
                data = json.load(f)
            for d in data:
                self._docs[d['id']] = AnnotationDocument(**d)
        except Exception:
            pass

    def _persist_index(self):
        try:
            with open(self._index_path(), 'w', encoding='utf-8') as f:
                json.dump([d.model_dump() for d in self._docs.values()], f, indent=2)
        except Exception:
            pass

    def add_document(self, doc: AnnotationDocument):
        with _STORAGE_LOCK:
            self._docs[doc.id] = doc
            self._persist_index()

    def get(self, doc_id: str) -> AnnotationDocument | None:
        return self._docs.get(doc_id)

    def list(self):
        return list(self._docs.values())

    def update(self, doc: AnnotationDocument):
        with _STORAGE_LOCK:
            self._docs[doc.id] = doc
            self._persist_index()

STORE = DocStore()
