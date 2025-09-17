import os, json, tempfile, shutil
from readingcopilot.core.llm_highlight import LLMHighlighter
from readingcopilot.core.llm_client import BaseLLMClient, ScoredChunk
from readingcopilot.core.annotations import AnnotationDocument
from readingcopilot.core.text_extraction import TextChunk

class _FakeClient(BaseLLMClient):
    def score_chunks(self, *, chunks, global_profile: str, document_goal: str):
        # deterministic ascending scores
        return [ScoredChunk(id=c['id'], relevance=0.5, rationale='test') for c in chunks]

def _fake_extract(monkeypatch):
    # Patch the symbol used inside llm_highlight (imported directly there)
    import readingcopilot.core.llm_highlight as hl_mod
    def _mock_extract(path):
        return [
            TextChunk(id=0, page_index=0, text='alpha beta', rects=[(0,0,10,10)], char_count=10),
            TextChunk(id=1, page_index=0, text='gamma delta', rects=[(0,15,10,25)], char_count=11),
        ]
    monkeypatch.setattr(hl_mod, 'extract_chunks', _mock_extract)


def test_incremental_log_naming(monkeypatch, tmp_path):
    # point RC_LOG_DIR to temp dir
    log_dir = tmp_path / 'logs'
    os.environ['RC_LOG_DIR'] = str(log_dir)
    _fake_extract(monkeypatch)
    dummy_pdf = tmp_path / 'dummy.pdf'
    dummy_pdf.write_bytes(b'%PDF-1.4\n%EOF')
    doc = AnnotationDocument(pdf_path=str(dummy_pdf), global_profile='x', document_goal='y')
    highlighter = LLMHighlighter(client=_FakeClient())
    # First run
    highlighter.generate(doc, str(dummy_pdf), density_target=0.1)
    files = sorted(os.listdir(log_dir))
    assert 'llm_run_1.json' in files
    # Second run
    highlighter2 = LLMHighlighter(client=_FakeClient())
    highlighter2.generate(doc, str(dummy_pdf), density_target=0.1)
    files = sorted(os.listdir(log_dir))
    assert 'llm_run_2.json' in files
    # Counter file should exist
    assert (log_dir / 'llm_run_counter.txt').exists()
