from __future__ import annotations
import uvicorn, os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .routers import documents

app = FastAPI(title="ReadingCopilot Web API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(documents.router)

# Serve uploaded PDFs statically so frontend pdf.js can fetch them
import os as _os
_PDF_DIR = _os.path.join('backend','storage','pdfs')
_os.makedirs(_PDF_DIR, exist_ok=True)
app.mount('/pdfs', StaticFiles(directory=_PDF_DIR), name='pdfs')

@app.get('/')
async def root():
    return {"service":"readingcopilot", "status":"ok"}

if __name__ == '__main__':
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=int(os.environ.get('PORT', 8000)), reload=True)
