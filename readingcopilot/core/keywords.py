from __future__ import annotations
from typing import List
import re

# Lightweight heuristic keyword extraction (no external deps)
# Strategy:
#  1. Tokenize on non-alphanumeric boundaries.
#  2. Lowercase, filter stopwords, numerics, very short tokens (<3 chars).
#  3. Count frequency; stable order by first appearance when frequencies tie.
#  4. Return up to max_keywords tokens (original casing capitalized) preserving ranking.

_STOPWORDS = {
    'the','and','for','with','that','this','from','are','was','were','will','shall','into','your','have','has','had',
    'but','not','can','could','would','should','a','an','of','on','in','to','as','by','it','its','at','or','be','is',
    'we','our','you','their','there','about','over','any','all','more','most','such','other','than','may','if','also'
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

def extract_keywords(text: str, max_keywords: int = 4) -> List[str]:
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text)
    order_index = {}
    freq = {}
    for idx, raw in enumerate(tokens):
        t = raw.lower().strip("'_")
        if not t or t in _STOPWORDS or len(t) < 3 or t.isdigit():
            continue
        if t not in order_index:
            order_index[t] = idx
        freq[t] = freq.get(t, 0) + 1
    if not freq:
        # fallback: first few words (cleaned)
        cleaned = [w.capitalize() for w in tokens[:max_keywords]]
        return cleaned
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], order_index[kv[0]]))
    out: List[str] = []
    for w, _ in ranked[:max_keywords]:
        out.append(w.capitalize())
    return out

__all__ = ["extract_keywords"]
