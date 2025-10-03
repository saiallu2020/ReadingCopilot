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

# Optionally serve built frontend (Vite build copied to backend/app/static by Dockerfile).
_STATIC_DIR = _os.path.join(_os.path.dirname(__file__), 'static')
if _os.path.isdir(_STATIC_DIR):
    app.mount('/', StaticFiles(directory=_STATIC_DIR, html=True), name='frontend')

    # Fallback route for SPA (only if static present)
    from fastapi import Request
    from fastapi.responses import FileResponse
    @app.get('/{full_path:path}')
    async def spa_fallback(full_path: str, request: Request):  # noqa: D401
        if full_path.startswith('api/') or full_path.startswith('pdfs/'):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail='Not Found')
        index_path = _os.path.join(_STATIC_DIR, 'index.html')
        if _os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "frontend build not present"}

@app.get('/')
async def root():
    return {"service":"readingcopilot", "status":"ok"}

if __name__ == '__main__':
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=int(os.environ.get('PORT', 8000)), reload=True)
