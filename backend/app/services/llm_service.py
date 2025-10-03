from __future__ import annotations
from typing import List, Dict
import threading, time
from readingcopilot.core.llm_client import AzureOpenAIClient
from readingcopilot.core.llm_highlight import DEFAULT_MIN_THRESHOLD
from ..models import AnnotationDocument, Highlight

# Simple registry of background highlight runs

class HighlightRun:
    def __init__(self, run_id: str, doc: AnnotationDocument):
        self.run_id = run_id
        self.doc = doc
        self.state = 'running'
        self.generated: int = 0
        self.highlights: List[Highlight] = []
        self.cancel_event = threading.Event()

_RUNS: Dict[str, HighlightRun] = {}
_RUNS_LOCK = threading.RLock()


def start_auto_highlight(doc: AnnotationDocument, density: float, min_threshold: float, page_filter: set[int] | None):
    run_id = f"run_{int(time.time()*1000)}"
    run = HighlightRun(run_id, doc)
    with _RUNS_LOCK:
        _RUNS[run_id] = run
    thread = threading.Thread(target=_worker, args=(run, density, min_threshold, page_filter), daemon=True)
    thread.start()
    return run

def cancel_run(run_id: str):
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if run:
            run.cancel_event.set()
    return run is not None

def get_run(run_id: str) -> HighlightRun | None:
    return _RUNS.get(run_id)

def _worker(run: HighlightRun, density: float, min_threshold: float, page_filter: set[int] | None):
    try:
        client = AzureOpenAIClient()
        from readingcopilot.core.llm_highlight import LLMHighlighter
        highlighter = LLMHighlighter(client)

        def on_highlight(hl: Highlight):
            run.highlights.append(hl)
            run.generated += 1
            run.doc.highlights.append(hl)

        def should_stop():
            return run.cancel_event.is_set()

        highlighter.generate_streaming(
            annotation_doc=run.doc,
            pdf_path=run.doc.pdf_path,
            density_target=density,
            on_highlight=on_highlight,
            should_stop=should_stop,
            min_threshold=min_threshold if min_threshold is not None else DEFAULT_MIN_THRESHOLD,
            page_filter=page_filter
        )
        run.state = 'cancelled' if run.cancel_event.is_set() else 'completed'
    except Exception as e:
        run.state = 'error:' + str(e)
