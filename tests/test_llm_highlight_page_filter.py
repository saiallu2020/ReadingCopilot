from readingcopilot.core.llm_highlight import LLMHighlighter
from readingcopilot.core.llm_client import BaseLLMClient, ScoredChunk
from readingcopilot.core.annotations import AnnotationDocument
from readingcopilot.core.text_extraction import TextChunk

class _FakeClient(BaseLLMClient):
    def score_chunks(self, *, chunks, global_profile: str, document_goal: str):
        # simple constant relevance to keep both eligible
        return [ScoredChunk(id=c['id'], relevance=0.9, rationale='r', phrase='Test Phrase') for c in chunks]

def _fake_extract(monkeypatch):
    import readingcopilot.core.llm_highlight as hl_mod
    def _mock_extract(path):
        return [
            TextChunk(id=0, page_index=0, text='first page content', rects=[(0,0,10,10)], char_count=10),
            TextChunk(id=1, page_index=1, text='second page content', rects=[(0,15,10,25)], char_count=20),
        ]
    monkeypatch.setattr(hl_mod, 'extract_chunks', _mock_extract)

def test_page_filter_limits_selection(monkeypatch, tmp_path):
    _fake_extract(monkeypatch)
    pdf = tmp_path / 'dummy.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%EOF')
    doc = AnnotationDocument(pdf_path=str(pdf), global_profile='x', document_goal='y')
    hl = LLMHighlighter(_FakeClient())
    selected = hl.generate(doc, str(pdf), density_target=0.5, page_filter={1})
    assert selected and all(h.page_index == 1 for h in selected)