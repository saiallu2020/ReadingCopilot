from __future__ import annotations
from typing import List, Tuple, Optional, Set
from .text_extraction import extract_chunks, TextChunk
from .llm_client import BaseLLMClient, ScoredChunk
from .annotations import Highlight, Rect, AnnotationDocument
from .keywords import extract_keywords
import os, json
from datetime import datetime
from pathlib import Path

# NOTE: This module now produces a per-run log file summarizing the LLM highlight pipeline.
# Log location: ~/.readingcopilot/logs/llm_run_<timestamp>.json
# Sensitive secrets (API keys) are NEVER written.

DEFAULT_MIN_THRESHOLD = 0.60  # Updated default relevance threshold

class LLMHighlighter:
    def __init__(self, client: BaseLLMClient):
        self.client = client
        self.last_log_path: str | None = None

    def generate(self, annotation_doc: AnnotationDocument, pdf_path: str, density_target: float, min_threshold: float = DEFAULT_MIN_THRESHOLD, page_filter: Optional[Set[int]] = None):
        # Allow environment variable override (RC_MIN_RELEVANCE_THRESHOLD)
        if min_threshold == DEFAULT_MIN_THRESHOLD:  # only override if caller used default
            env_thr = os.environ.get("RC_MIN_RELEVANCE_THRESHOLD")
            if env_thr:
                try:
                    mt = float(env_thr)
                    if 0.0 <= mt <= 1.0:
                        min_threshold = mt
                except ValueError:
                    pass
        # Step 1: Extract chunks
        chunks = extract_chunks(pdf_path)
        if page_filter:
            # keep only chunks whose page_index is in filter
            chunks = [c for c in chunks if c.page_index in page_filter]
        if not chunks:
            self._write_log(pdf_path, annotation_doc, density_target, [], {}, [], [], reason="no_chunks_extracted")
            return []
        # Prepare payload for scoring (batched)
        scored_map = {}
        batch_size = 8
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            scored = self.client.score_chunks(
                chunks=[{"id": c.id, "text": c.text} for c in batch],
                global_profile=annotation_doc.global_profile or "",
                document_goal=annotation_doc.document_goal or ""
            )
            for s in scored:
                scored_map[s.id] = s
        # Assign scores; default 0 if missing
        scored_chunks: List[Tuple[TextChunk, float]] = []
        total_words = 0
        for c in chunks:
            words = len(c.text.split())
            total_words += words
            relevance = scored_map.get(c.id, ScoredChunk(id=c.id, relevance=0.0, rationale="missing")).relevance
            scored_chunks.append((c, relevance))
        if total_words == 0:
            self._write_log(pdf_path, annotation_doc, density_target, chunks, scored_map, scored_chunks, [], reason="zero_total_words")
            return []
        target_words = max(1, int(total_words * density_target))
        # Sort by relevance
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        selected: List[Highlight] = []
        accumulated = 0
        for chunk, rel in scored_chunks:
            if rel < min_threshold:
                # If we've already satisfied target words, encountering first below-threshold ends selection
                if accumulated >= target_words:
                    break
                # Otherwise skip and keep scanning for higher relevance
                continue
            rects = [Rect(x1=r[0], y1=r[1], x2=r[2], y2=r[3]) for r in chunk.rects]
            scored = scored_map.get(chunk.id)
            phrase = getattr(scored, 'phrase', None) if scored else None
            if phrase:
                note = phrase
            else:
                kw = extract_keywords(chunk.text, max_keywords=4)
                note = " ".join(kw) if kw else None
            hl = Highlight(page_index=chunk.page_index, rects=rects, extracted_text=chunk.text, auto_generated=True, profile_score=rel, color=(255, 170, 90), note=note)
            selected.append(hl)
            accumulated += len(chunk.text.split())
            if accumulated >= target_words * 2:  # soft cap
                break
        # Fallback: if no highlights selected but we have scored chunks, choose the top one (even if below threshold)
        fallback_used = False
        if not selected and scored_chunks:
            top_chunk, top_rel = scored_chunks[0]
            # Only fallback if top chunk actually meets threshold (avoid surfacing low-quality 0.4 scores)
            if top_rel >= min_threshold:
                rects = [Rect(x1=r[0], y1=r[1], x2=r[2], y2=r[3]) for r in top_chunk.rects]
                scored_top = scored_map.get(top_chunk.id)
                phrase = getattr(scored_top, 'phrase', None) if scored_top else None
                if phrase:
                    note = phrase
                else:
                    kw = extract_keywords(top_chunk.text, max_keywords=4)
                    note = " ".join(kw) if kw else None
                selected.append(Highlight(page_index=top_chunk.page_index, rects=rects, extracted_text=top_chunk.text, auto_generated=True, profile_score=top_rel, color=(255, 170, 90), note=note))
                fallback_used = True
        self._write_log(
            pdf_path,
            annotation_doc,
            density_target,
            chunks,
            scored_map,
            scored_chunks,
            selected,
            min_threshold,
            reason=("fallback_top_chunk" if (not selected and scored_chunks) else ("fallback_used" if fallback_used else "ok"))
        )
        return selected

    # ---- Internal helpers ----
    def _log_dir(self) -> str:
        # Allow override via environment variable
        env_override = os.environ.get("RC_LOG_DIR")
        if env_override:
            base = env_override
        else:
            # Default: repository-root / logs (walk upwards until we find a marker).
            # Fallback to current working directory if detection fails.
            base = self._detect_repo_root() or os.getcwd()
            base = os.path.join(base, "logs")
        os.makedirs(base, exist_ok=True)
        return base

    def _detect_repo_root(self) -> str | None:
        markers = {".git", "README.md", "requirements.txt"}
        path = os.path.abspath(os.getcwd())
        for _ in range(10):  # limit climb depth
            if any(os.path.exists(os.path.join(path, m)) for m in markers):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
        return None

    def _next_log_filename(self, base_dir: str) -> str:
        """Return next incremental log filename: llm_run_<n>.json.

        Persistence strategy:
          1. Maintain a small counter file 'llm_run_counter.txt' in the log dir.
          2. If missing/corrupt, derive next number by scanning existing llm_run_*.json files.
        Thread-safety: best-effort (single-user desktop context)."""
        counter_path = Path(base_dir) / "llm_run_counter.txt"
        n = None
        if counter_path.exists():
            try:
                raw = counter_path.read_text(encoding="utf-8").strip()
                n = int(raw)
            except Exception:
                n = None
        if n is None:
            # scan existing
            max_n = 0
            for name in os.listdir(base_dir):
                if name.startswith("llm_run_") and name.endswith(".json"):
                    mid = name[len("llm_run_"):-len(".json")]
                    if mid.isdigit():
                        max_n = max(max_n, int(mid))
            n = max_n
        n += 1
        try:
            counter_path.write_text(str(n), encoding="utf-8")
        except Exception:
            pass
        return f"llm_run_{n}.json"

    def _write_log(self, pdf_path: str, annotation_doc: AnnotationDocument, density_target: float,
                   chunks: List[TextChunk], scored_map: dict, scored_chunks: List[Tuple[TextChunk, float]],
                   selected: List[Highlight], min_threshold: float, reason: str):
        try:
            log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "pdf_path": pdf_path,
                "reason": reason,
                "density_target": density_target,
                "min_threshold": min_threshold,
                "profile_present": bool(annotation_doc.global_profile),
                "document_goal_present": bool(annotation_doc.document_goal),
                "profile_char_len": len(annotation_doc.global_profile or ""),
                "goal_char_len": len(annotation_doc.document_goal or ""),
                "chunks": [
                    {
                        "id": c.id,
                        "page_index": c.page_index,
                        "char_count": c.char_count,
                        "text_preview": c.text[:500]
                    } for c in chunks
                ],
                # Comprehensive scores: ensure every chunk appears exactly once; fill missing with 0 relevance.
                "scores": [
                    {
                        "id": c.id,
                        "page_index": c.page_index,
                        "relevance": (scored_map.get(c.id).relevance if c.id in scored_map else 0.0),
                        "rationale_preview": (scored_map.get(c.id).rationale[:300] if c.id in scored_map and getattr(scored_map.get(c.id), 'rationale', None) else "")
                    } for (c, rel) in scored_chunks
                ],
                "scored_order": [
                    {
                        "id": c.id,
                        "relevance": rel,
                        "page_index": c.page_index
                    } for (c, rel) in scored_chunks
                ],
                "selected": [
                    {
                        "id": idx,
                        "page_index": hl.page_index,
                        "relevance": hl.profile_score,
                        "text_preview": (hl.extracted_text or "")[:400]
                    } for idx, hl in enumerate(selected)
                ]
            }
            log_dir = self._log_dir()
            fname = self._next_log_filename(log_dir)
            path = os.path.join(log_dir, fname)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(log, f, indent=2)
            self.last_log_path = path
        except Exception:
            self.last_log_path = None
