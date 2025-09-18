from readingcopilot.core.keywords import extract_keywords

def test_extract_keywords_basic():
    text = "AMD data center GPU revenue accelerating with hyperscaler adoption and multi-year cloud commitments."
    kws = extract_keywords(text, max_keywords=4)
    assert 1 <= len(kws) <= 4
    # Expect at least one domain term present
    lowered = [k.lower() for k in kws]
    assert any(term in lowered for term in ["gpu", "center", "revenue", "hyperscaler"])  # heuristic

def test_extract_keywords_fallback():
    # Text that will mostly be stopwords -> fallback to first words
    text = "The and if or but the and"
    kws = extract_keywords(text, max_keywords=4)
    assert len(kws) <= 4
    # With no valid tokens we fall back to first tokens capitalized (may be empty if regex filters all)
    # Ensure function still returns a list (possibly empty) and doesn't raise.
    assert isinstance(kws, list)