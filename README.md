# ReadingCopilot

ReadingCopilot is an extensible local-first PDF reader that will evolve into an AI-assisted research companion. Phase 1 (this commit) delivers a basic Mac Preview–style PDF viewer with manual highlighting and notes. Future phases will automatically surface/highlight content relevant to a user profile (e.g., "data center GPU business risks" or "net income + hyperscaler traction").

## Features (Current)
* Open and render PDF files (pypdf for structure/text + QtPdf (QPdfDocument) for rasterization)
* Create rectangular highlights by click-drag selection
* Maintain multiple highlights per page
* Add / edit free-form notes per highlight in a side panel
* Persist annotations to a JSON sidecar file: `<pdf>.annotations.json`
* Profile & Goal dialog (global profile + document-specific goal + highlight density target)
* LLM Auto Highlight (Azure OpenAI) scores extracted text chunks for relevance (auto-generated highlights appear in orange) and now assigns a short LLM-generated phrase (1–4 words) as the highlight note for quick scanning.

## Roadmap (Next)
1. Finer text-span mapping (per-line / per-word geometry) and highlight merging
2. Embedding or hybrid semantic scoring (sentence-transformers) with caching
3. Weighted multi-profile scoring & color gradients
4. Inline density meter / coverage visualization
5. Export annotated summary (Markdown / HTML) grouped by theme
6. Feedback loop (accept/reject highlights to adapt weighting)
7. Model response rationale display per highlight

## Installation
```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

If your PySide6 build does not include QtPdf (QPdfDocument), rendering will show a placeholder error message. In that case install a wheel that bundles QtPdf, or consider adding an optional rasterization backend (future roadmap).
```

## Run
```bash
python -m readingcopilot.ui.main
```

## LLM Highlighting (Azure OpenAI)

LLM-based highlighting scores paragraph-like chunks extracted with `pdfminer.six` and selects the most relevant spans toward your target density. This build now uses ONLY Azure OpenAI (no local Ollama dependency).

### Azure Environment Variables (required unless noted)
| Variable | Purpose | Default |
|----------|---------|---------|
| `RC_LLM_PROVIDER` | (Deprecated – ignored, always Azure) | (n/a) |
| `RC_AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI endpoint base URL | — |
| `RC_AZURE_OPENAI_KEY` | Azure OpenAI API key | — |
| `RC_AZURE_OPENAI_DEPLOYMENT` | Deployment name | `gpt-4o-mini` |
| `RC_AZURE_OPENAI_API_VERSION` | API version | `2024-05-01-preview` |
| `RC_AZURE_OPENAI_MAX_TOKENS` | Max completion tokens for scoring response | `250` |

PowerShell example:
```powershell
$env:RC_AZURE_OPENAI_ENDPOINT = 'https://<your-resource>.openai.azure.com'
$env:RC_AZURE_OPENAI_KEY = '<your-key>'
$env:RC_AZURE_OPENAI_DEPLOYMENT = 'gpt-4o-mini'
python -m readingcopilot.ui.main
```

### Usage
1. Open a PDF.
2. AI > Edit Profile / Goal: enter global background + document goal and adjust density.
3. AI > LLM Auto Highlight.
4. Highlights appear (orange tint). Manual highlights remain yellow.

If the Azure call fails or returns malformed JSON, the app logs diagnostic details and surfaces an error dialog; no fallback dummy scorer is retained.

### Incremental Streaming & Cancellation (New)
The LLM highlight pipeline now streams results incrementally:
* A small spinner (braille frames) appears in the toolbar instead of a blocking modal.
* As each batch of chunks is scored, new above-threshold highlights are emitted immediately and drawn; you can start reading them while later pages continue processing.
* Page-range runs (right-click the LLM HL button) also stream.
* A completion dialog summarizes counts and log location; annotations auto-save.

Implementation notes:
* `LLMHighlighter.generate_streaming` performs batch scoring and heuristic early selection (may differ slightly from full global optimum for latency).
* `LLMStreamWorker` (QThread) emits `highlightReady` signals back to the UI thread.
* Annotation panel inserts highlights in page order on arrival.
* Spinner stops on finish or error.

You can cancel mid-run via the "Cancel AI" toolbar button:
* Already-emitted highlights remain and are saved automatically.
* Spinner switches to "Cancelling" until the current batch finishes.
* Final dialog is labeled (Cancelled) and still shows the log path.

Planned improvements: adaptive batch size, dynamic threshold relaxation if target density underfilled late, streaming rationale surfacing, and optional real-time metrics in status bar.

### How It Works (High-Level)
1. `pdfminer.six` extracts lines and groups them into chunks (bounded by vertical gaps and character limits).
2. Chunks are batched to the LLM with a JSON instruction to return relevance scores 0–1.
3. Scores are sorted; chunks are selected until the soft word budget (density target) is met.
4. Each chunk's line rectangles form a multi-rect highlight.
5. The model now also returns a concise phrase label per chunk (e.g. `AMD Instinct GPUs`, `Hyperscaler demand signal`). This becomes the note shown in the annotation list. If a phrase is missing, a local heuristic keyword fallback is used.

### Limitations
* Chunk granularity is line-group based; not yet word-level.
* Rationale text is stored but not surfaced in the UI (planned).
* Errors from malformed model output are caught; minimal recovery implemented.

## Project Structure
```
readingcopilot/
  core/
    annotations.py     # Data models for highlights & persistence (+ AI fields)
    pdf_loader.py      # pypdf-based metadata/text + QtPdf rendering wrapper
    profiles.py        # (Future) extended profile structures
    text_extraction.py # pdfminer-based chunk extraction
  llm_client.py      # LLM client (Azure OpenAI only)
    llm_highlight.py   # LLM-driven highlight selection
  ui/
    pdf_viewer.py      # QGraphicsView-based renderer + highlight tool
    annotation_panel.py# List & edit notes
    profile_dialog.py  # Profile & goal + density input
    main.py            # Application entry point (menus/toolbars)
inputPDFs/
  <place your PDFs here>
```

## Navigation Features
* Toolbar arrows (◀ / ▶) and menu Navigate > Previous/Next Page.
* Page label in status bar shows current / total.
* Floating page number overlay (top-right of viewer) always visible while scrolling (e.g. `4 / 200`).
* Page jump box (enter page number + Enter) or Ctrl+G focuses the box.
* PageUp/PageDown keys navigate pages.
* Selecting a highlight in the right panel jumps to its page and centers the first rectangle.
* (Planned) optional flash animation to visually emphasize jumped highlight.

## Developer Notes
- Coordinate system for stored highlights uses native PDF points (72 dpi). Rendering uses a fixed zoom (1.3) right now—logical coordinates allow future zoom changes without migration.
- Highlights currently support one rectangle; model allows multi-rect for future text-line wrapping or text-layer mapping.
- pypdf does not expose positional word/line geometry by default; we synthesize a single full-page block. Future: integrate pdfminer.six or pdfplumber to map highlights to actual text spans and populate `extracted_text` automatically.
- Auto highlight heuristic: tokenizes profile + goal, applies simple weighted keyword scoring across paragraph-like splits, then selects top spans until target density word budget reached.
- LLM highlight path: builds JSON prompt including chunks, expects JSON list response with id/relevance/rationale.
- Density slider (1–50%) is a soft target; actual selected coverage may differ based on scoring distribution.

## Tests
Run tests (after installing dependencies):
```bash
python -m pytest -q
```

## License
TBD (add your preferred license).

## Profiles
I am an experienced software engineer who is comfortable with technical details, but I do not have a hardware engineering or chip design background. I have read about GPUs and semiconductors for a few weeks now, so I do know some of the basics, but I am still a beginner. I am well-versed in finance, accounting, and economics. I am at an intermediate, not an advanced level though. I am looking to find great, underrated investment opportunities in the tech industry.

This is AMD's annual report. I want to understand their data center or DC GPU business. I specifically want to understand key risks in their business, key opportunities, their customers, recent wins, milestones, future roadmaps, and any other information to help me evaluate their data center AI GPU business. I want to see how they compare to Nvidia or Broadcom who also make AI semiconductor chips. I want to focus the highlights on key information that will help me make a decision in whether to invest in AMD or not.


## Setup
Activate venv:
& C:/Users/saiallu/source/repos/ReadingCopilot/.venv/Scripts/Activate.ps1 

Environment variables:
$env:RC_LLM_PROVIDER = 'azure_openai'
$env:RC_AZURE_OPENAI_ENDPOINT = 'https://saialluoai.openai.azure.com'
*****$env:RC_AZURE_OPENAI_KEY = '<fill-this-in>'
$env:RC_AZURE_OPENAI_DEPLOYMENT = 'gpt-4o'
$env:RC_AZURE_OPENAI_MAX_TOKENS = '16000'


Launch application:
python -m readingcopilot.ui.main

## New Setup
Backend:

& C:/Users/saiallu/source/repos/ReadingCopilot/.venv/Scripts/Activate.ps1

Environment variables:
$env:RC_LLM_PROVIDER = 'azure_openai'
$env:RC_AZURE_OPENAI_ENDPOINT = 'https://saialluoai.openai.azure.com'
*****$env:RC_AZURE_OPENAI_KEY = '<fill-this-in>'
$env:RC_AZURE_OPENAI_DEPLOYMENT = 'gpt-4o'
$env:RC_AZURE_OPENAI_MAX_TOKENS = '16000'

python -m uvicorn backend.app.main:app --reload --reload-dir backend/app --host 0.0.0.0 --port 8000


Frontend:
curl http://localhost:8000/
cd C:\Users\saiallu\source\repos\ReadingCopilot\frontend
npm install
npm run dev

## Web Architecture (FastAPI + React)

The repository now contains an experimental web version consisting of:

* `backend/` FastAPI app
  * Document upload & listing
  * Manual highlight persistence
  * Start / status / cancel endpoints for LLM auto-highlighting (background thread)
  * Static serving of built frontend bundle (Vite) + PDF file serving
* `frontend/` React + TypeScript + Vite + pdf.js
  * Renders PDF pages via pdf.js
  * Drag-to-create manual rectangle highlights (persisted through API)
  * Displays auto-generated highlights (polling status endpoint for now)
  * Cancel button with "Cancelling…" transitional state
  * Click highlight list item to scroll & flash corresponding overlay
* Containerization with multi-stage Dockerfile combining frontend build and backend runtime

### Local (Container) Run
```powershell
# From repo root
docker build -t readingcopilot:local .
docker run -p 8000:8000 --env-file .env.local readingcopilot:local
Start-Sleep -Seconds 2
Start-Process http://localhost:8000/
```

Sample `.env.local` (DO NOT COMMIT):
```
RC_AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
RC_AZURE_OPENAI_KEY=***
RC_AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
RC_AZURE_OPENAI_MAX_TOKENS=250
```

## Azure Deployment (App Service - Container)

### Prerequisites
* Azure subscription & tenant (IDs already known to you)
* GitHub OIDC Federated Credential (recommended) or a service principal
* `az` CLI >= 2.60

### One-Time Provisioning (az CLI)
Replace names to fit naming rules (lowercase alphanumeric for ACR, etc.). The plan uses Linux Consumption (B1 / P1v3 as examples) - adjust SKU.

```powershell
$rg = "saiallu-rg"
$location = "eastus"
$acr = "rcprodacr"
$plan = "readingcopilot-plan"
$web = "readingcopilot-webapp"   # must be globally unique

az group create -n $rg -l $location

# Container Registry
az acr create -n $acr -g $rg --sku Basic --admin-enabled false

# App Service Plan (Linux)
az appservice plan create -g $rg -n $plan --is-linux --sku B1

# Web App (initial dummy image)
az webapp create -g $rg -n $web -p $plan \
  -i mcr.microsoft.com/azuredocs/containerapps-helloworld:latest

# Grant Web App pull permission from ACR (using managed identity)
az webapp identity assign -g $rg -n $web
$principalId = az webapp identity show -g $rg -n $web --query principalId -o tsv
az role assignment create --assignee $principalId \
  --scope $(az acr show -n $acr --query id -o tsv) \
  --role "AcrPull"

# App settings (placeholders; Key Vault references optional later)
az webapp config appsettings set -g $rg -n $web --settings \
  RC_AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com \
  RC_AZURE_OPENAI_KEY=__ROTATED_KEY__ \
  RC_AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini \
  RC_AZURE_OPENAI_MAX_TOKENS=250
```

### GitHub OIDC Federated Credentials
1. Create an App Registration (if not already) to act as federated identity.
2. In Azure Portal > App Registration > Certificates & Secrets > Federated credentials -> Add credential.
3. Choose GitHub Actions, set:
   * Organization: your GitHub user/org
   * Repository: `saiallu2020/ReadingCopilot`
   * Entity Type: Branch
   * Branch: `main`
   * Name: `readingcopilot-main`
4. Record Application (client) ID, Tenant ID, Subscription ID, and store in GitHub repo secrets:
   * `AZURE_CLIENT_ID`
   * `AZURE_TENANT_ID`
   * `AZURE_SUBSCRIPTION_ID`

### CI/CD Workflow
`/.github/workflows/deploy-appservice.yml` builds the Docker image, pushes to ACR, updates the Web App container, and sets app settings. Trigger: push to `main` or manual dispatch.

### Required GitHub Secrets
| Secret | Purpose |
|--------|---------|
| `AZURE_CLIENT_ID` | App registration client ID for OIDC login |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Subscription containing resources |
| `RC_AZURE_OPENAI_ENDPOINT` | Endpoint (used as app setting) |
| `RC_AZURE_OPENAI_KEY` | API key (consider moving to Key Vault) |
| `RC_AZURE_OPENAI_DEPLOYMENT` | Deployment name |

Optional (override defaults): `RC_AZURE_OPENAI_MAX_TOKENS`.

### Deployment Flow Summary
1. Developer merges to `main`.
2. Workflow logs into Azure via OIDC, ensures ACR & Web App exist.
3. Builds multi-stage image, pushes to ACR.
4. Updates Web App to new image tag.
5. Applies env settings and restarts.

### Production Hardening Suggestions
* Move API key to Azure Key Vault and reference via `@Microsoft.KeyVault(SecretUri=...)` in App Settings.
* Enable logging & Application Insights.
* Add staging slot and swap strategy.
* Add CDN or Azure Front Door for global caching (optional).

## GitHub Actions Local Dry Run (Optional)
You can test Docker build locally identically to CI:
```powershell
docker build -t rc-test .
docker run -p 8000:8000 rc-test
```

## Persistence Roadmap (Current vs Proposed)
Current:
* Documents and highlights stored as JSON sidecar files (desktop) or in-memory + JSON index (web prototype).
Limitations: Not multi-user safe, no concurrency control, ephemeral in container.

Proposed Evolution:
1. Azure Blob Storage (or Azure Files) for original PDFs & annotation JSON snapshots.
2. Relational metadata (Azure PostgreSQL Flexible Server or Azure SQLite in Azure Files) for: documents, profiles, highlight rows, run history, audit.
3. Optional Redis (Azure Cache) for: streaming run progress, cancellation flags, ephemeral highlight batches.
4. Background tasks queue (Azure Storage Queues) if LLM highlight generation moves off-request.
5. Signed URL pattern (SAS) for direct browser PDF fetch if blobs not proxied.

Data Model Sketch (relational):
* documents(id PK, filename, blob_uri, pages, created_at)
* profiles(id PK, user_id FK, global_text, updated_at)
* document_profiles(id PK, document_id FK, goal_text, density_target)
* highlights(id PK, document_id FK, page, rects(jsonb), note, source(enum: manual|llm), relevance REAL NULL, created_at)
* highlight_runs(id PK, document_id FK, status, started_at, finished_at, cancelled_at, params(jsonb))

Migration Path:
* Phase 1: Introduce DB write-through while keeping JSON export for backup.
* Phase 2: Remove JSON except for explicit export feature.
* Phase 3: Add per-user isolation + auth (Azure Entra ID / OAuth) and row-level scoping.

## Streaming Upgrade Plan (SSE / WebSocket)
Current: Client polls `/api/documents/{id}/auto/status` until `completed` or `cancelled`, then fetches results.

Target (SSE):
* Endpoint: `GET /api/documents/{id}/auto/stream` returning `text/event-stream`.
* Events:
  * `run-start` { run_id }
  * `highlight` { id, page, rects, note, source, relevance }
  * `progress` { processed_chunks, total_chunks }
  * `cancelled` { reason }
  * `completed` { total_highlights, duration_ms }
* Client: `const es = new EventSource(...)`; mutate state on events without full redraw.
* Cancellation: `DELETE /api/documents/{id}/auto/run` sets cancellation flag; server emits `cancelled` then closes stream.

Alternative (WebSocket):
* Single bi-directional channel allows client to send `cancel` message instead of separate REST call.
* Slightly more infra overhead on App Service (requires WebSockets enabled) but supports future interactive refinements.

Server Implementation Sketch:
```python
@router.get("/documents/{doc_id}/auto/stream")
async def auto_stream(doc_id: str):
    # Validate run or start new
    async def event_gen():
        yield sse_event("run-start", {"run_id": run_id})
        for batch in highlighter.stream_chunks(...):
            for h in batch.highlights:
                yield sse_event("highlight", serialize(h))
            yield sse_event("progress", {"processed_chunks": batch.i, "total_chunks": batch.total})
            if cancellation.is_set():
                yield sse_event("cancelled", {"reason": "user"})
                return
        yield sse_event("completed", {...})
    return EventSourceResponse(event_gen())
```

Browser Flash / Scroll Enhancement:
* On `highlight` event, if highlight list panel is open and related page in viewport, briefly pulse border (CSS animation) without re-rendering entire page canvas.

Fallback Strategy:
* If SSE unsupported (old browsers), automatically revert to existing polling path.

## Security & Compliance Considerations
* Secrets: move keys to Key Vault; avoid printing in logs; rotate at least every 90 days.
* PII: current PDFs assumed non-sensitive; if sensitive add encryption at rest & access logs.
* Dependency Scanning: Enable Dependabot & CodeQL in repo.
* Rate Limiting: Add simple token bucket (e.g. in Redis) before exposing publicly.

## Monitoring & Observability
* Integrate Application Insights: request duration, exceptions, custom events for `highlight_run_start` / `highlight_run_complete`.
* Log correlation ID (traceparent) injected per request to link highlight run logs.

## Next Steps (Suggested)
1. Implement SSE endpoint & React event handling.
2. Introduce persistence layer (SQLite/SQLAlchemy) and migration tool (Alembic).
3. Add auth & multi-user isolation.
4. Add integration tests hitting containerized image in CI.
5. Export annotated summary (Markdown) endpoint.
