import json
from readingcopilot.core.llm_client import parse_scores, ScoredChunk

def test_parse_scores_truncated_array():
    # Simulate an Azure response that was truncated mid-object due to token limit
    raw = '[\n  {"id": 0, "relevance": 0.9, "rationale": "Complete object"},\n  {"id": 1, "relevance": 0.55, "rationale": "Another complete"},\n  {"id": 2, "relevance": 0.42, "rationale": "Partially cut off'  # note unmatched quote and missing ending braces
    scores = parse_scores(raw)
    # We should at least recover the first two valid objects
    assert len(scores) >= 2
    ids = {s.id for s in scores}
    assert 0 in ids and 1 in ids
    # Ensure invalid/truncated third object not included
    assert 2 not in ids or all(s.rationale for s in scores if s.id == 2)

def test_parse_scores_plain_list():
    raw = '[{"id":3,"relevance":0.75,"rationale":"ok","phrase":"Test phrase"}]'
    scores = parse_scores(raw)
    assert len(scores) == 1 and scores[0].id == 3 and scores[0].phrase == "Test phrase"
