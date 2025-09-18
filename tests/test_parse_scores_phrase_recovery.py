from readingcopilot.core.llm_client import parse_scores

def test_parse_scores_phrase_optional():
    raw = '[{"id":1,"relevance":0.8,"rationale":"good","phrase":"Instinct GPUs"}, {"id":2,"relevance":0.2,"rationale":"low"}]'
    out = parse_scores(raw)
    by_id = {s.id: s for s in out}
    assert by_id[1].phrase == "Instinct GPUs"
    assert by_id[2].phrase is None