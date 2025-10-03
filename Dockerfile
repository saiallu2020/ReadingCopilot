# Multi-stage build: frontend -> backend

# ---------- Frontend build stage ----------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
COPY frontend/tsconfig.json ./
COPY frontend/vite.config.* ./ 2>/dev/null || true
RUN npm install --legacy-peer-deps
COPY frontend/ .
RUN npm run build

# ---------- Backend stage ----------
FROM python:3.11-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

# System deps (pdfminer can need fonts; add minimal build tools if future native deps appear)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend ./backend
COPY readingcopilot ./readingcopilot

# Copy built frontend into backend/app/static
RUN mkdir -p backend/app/static
COPY --from=frontend /app/frontend/dist/ backend/app/static/

# Expose port & default CMD
EXPOSE 8000
ENV PORT=8000

# Healthcheck (simple ping)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get('PORT','8000')}/').read()" || exit 1

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
