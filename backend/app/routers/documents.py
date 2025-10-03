from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi import Depends
from typing import List
import os, shutil
from ..models import AnnotationDocument, UploadResponse, ProfileUpdate, ManualHighlightIn, Highlight, Rect
from ..storage import STORE
from ..services import llm_service

router = APIRouter(prefix="/api/docs", tags=["documents"])

PDF_DIR = os.path.join('backend','storage','pdfs')
os.makedirs(PDF_DIR, exist_ok=True)

@router.get('/', response_model=List[AnnotationDocument])
def list_documents():
    return STORE.list()

@router.post('/', response_model=UploadResponse)
def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='Only PDF files allowed')
    dest_path = os.path.join(PDF_DIR, file.filename)
    with open(dest_path, 'wb') as out:
        shutil.copyfileobj(file.file, out)
    doc = AnnotationDocument(filename=file.filename, pdf_path=dest_path)
    STORE.add_document(doc)
    return UploadResponse(document_id=doc.id, filename=file.filename)

@router.get('/{doc_id}', response_model=AnnotationDocument)
def get_document(doc_id: str):
    doc = STORE.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Not found')
    return doc

@router.put('/{doc_id}/profile', response_model=AnnotationDocument)
def update_profile(doc_id: str, payload: ProfileUpdate):
    doc = STORE.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Not found')
    doc.global_profile = payload.global_profile
    doc.document_goal = payload.document_goal
    doc.highlight_density_target = max(0.01, min(0.5, payload.highlight_density_target))
    STORE.update(doc)
    return doc

@router.post('/{doc_id}/highlights', response_model=AnnotationDocument)
def add_highlight(doc_id: str, hl_in: ManualHighlightIn):
    doc = STORE.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Not found')
    hl = Highlight(page_index=hl_in.page_index, rects=[r for r in hl_in.rects], note=hl_in.note)
    doc.highlights.append(hl)
    STORE.update(doc)
    return doc

@router.delete('/{doc_id}/highlights')
def clear_highlights(doc_id: str):
    doc = STORE.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Not found')
    doc.highlights = []
    STORE.update(doc)
    return {"status":"cleared"}

# --- Auto highlight orchestration ---
from fastapi import Query
from ..models import AutoHLRequest, AutoHLStatus
from readingcopilot.core.llm_highlight import DEFAULT_MIN_THRESHOLD

@router.post('/{doc_id}/auto', response_model=AutoHLStatus)
def start_auto(doc_id: str, req: AutoHLRequest):
    doc = STORE.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Not found')
    if not (doc.global_profile and doc.document_goal):
        raise HTTPException(status_code=400, detail='Profile & goal required')
    density = req.density or doc.highlight_density_target
    thr = req.min_threshold or DEFAULT_MIN_THRESHOLD
    page_filter = None
    if req.pages:
        page_filter = _parse_page_range(req.pages)
    run = llm_service.start_auto_highlight(doc, density, thr, page_filter)
    STORE.update(doc)
    return AutoHLStatus(run_id=run.run_id, state=run.state, emitted=run.generated)

@router.get('/{doc_id}/auto/{run_id}', response_model=AutoHLStatus)
def auto_status(doc_id: str, run_id: str):
    run = llm_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='Run not found')
    return AutoHLStatus(run_id=run.run_id, state=run.state, emitted=run.generated)

@router.delete('/{doc_id}/auto/{run_id}', response_model=AutoHLStatus)
def auto_cancel(doc_id: str, run_id: str):
    run = llm_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='Run not found')
    llm_service.cancel_run(run_id)
    return AutoHLStatus(run_id=run.run_id, state='cancelling', emitted=run.generated)

@router.get('/{doc_id}/auto/{run_id}/highlights', response_model=AnnotationDocument)
def auto_results(doc_id: str, run_id: str):
    doc = STORE.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='Not found')
    return doc

# Helper

def _parse_page_range(spec: str) -> set[int]:
    pages: set[int] = set()
    parts = [p.strip() for p in spec.split(',') if p.strip()]
    for part in parts:
        if '-' in part:
            a,b,*rest = part.split('-')
            if rest or not a.isdigit() or not b.isdigit():
                raise ValueError(f'Invalid range segment: {part}')
            start, end = int(a), int(b)
            if start > end:
                start, end = end, start
            for v in range(start, end+1):
                pages.add(v-1)
        else:
            if not part.isdigit():
                raise ValueError(f'Invalid page number: {part}')
            pages.add(int(part)-1)
    return pages
