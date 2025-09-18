import os, sys, pathlib, json
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from readingcopilot.core.llm_client import AzureOpenAIClient, ScoredChunk, parse_scores

REQUIED_VARS = ["RC_AZURE_OPENAI_ENDPOINT", "RC_AZURE_OPENAI_KEY"]

def test_azure_client_basic():
    """Runs Azure scoring test if environment variables are present.

    This is now treated as a normal test (no custom integration mark). It will
    skip cleanly when either the provider is not set to azure_openai or the
    required env vars are missing, allowing `pytest -q` to run without warnings.
    """
    if os.environ.get("RC_LLM_PROVIDER", "").lower() != "azure_openai":
        pytest.skip("RC_LLM_PROVIDER not set to azure_openai")
    missing = [v for v in REQUIED_VARS if not os.environ.get(v)]
    if missing:
        pytest.skip(f"Missing Azure env vars: {missing}")
    try:
        client = AzureOpenAIClient()
    except RuntimeError as e:
        pytest.skip(f"Azure client init failed (likely dependency missing): {e}")
    print("[azure-test] Initializing Azure client and preparing chunks")
    # Expanded set of 10 chunks (mix of relevant / irrelevant)
    chunks = [
        {"id": 0, "text": "AMD data center GPU revenue accelerating with hyperscaler adoption and multi-year cloud commitments."},
        {"id": 1, "text": "Company sponsored a local beach cleanup event with employees volunteering."},
        {"id": 2, "text": "EPYC CPU market share gains reported in enterprise and cloud workloads."},
        {"id": 3, "text": "Quarter featured an executive leadership training program for internal staff development."},
        {"id": 4, "text": "Instinct accelerator design wins expanding across AI training clusters for Fortune 100 customers."},
        {"id": 5, "text": "General discussion of corporate social responsibility without product specifics."},
        {"id": 6, "text": "Strong backlog for next-gen data center GPU platform targeting inference efficiency improvements."},
        {"id": 7, "text": "Retail channel sales of legacy desktop APUs remained stable year-over-year."},
        {"id": 8, "text": "Roadmap outlines upcoming multi-die GPU architecture focused on memory bandwidth scaling."},
        {"id": 9, "text": "Team members participated in a holiday charity fundraiser event."},
    ]
    print(f"[azure-test] Prepared {len(chunks)} chunks")
    profile = "Investor with technical finance background seeking data center GPU growth, hyperscaler traction, architectural roadmap, and competitive positioning."
    goal = "Identify chunks signaling data center GPU acceleration, design wins, roadmap differentiation, or market share gains relevant to investment thesis."
    print("[azure-test] Sending scoring request to Azure...")
    scores = client.score_chunks(chunks=chunks, global_profile=profile, document_goal=goal)
    print(f"[azure-test] Received {len(scores)} scored entries")
    assert scores, "Expected at least one scored chunk"
    # Validate structure
    for sc in scores:
        assert isinstance(sc, ScoredChunk)
        assert 0 <= sc.relevance <= 1
    by_id = {s.id: s.relevance for s in scores}
    # Print ordered list (descending relevance)
    ordered = sorted(scores, key=lambda x: x.relevance, reverse=True)
    print("[azure-test] Ranked chunks (id | relevance | snippet):")
    for sc in ordered:
        text = next(c['text'] for c in chunks if c['id'] == sc.id)
        tag = "RELEVANT" if any(k in text.lower() for k in ["gpu", "hyperscaler", "instinct", "data center", "roadmap", "accelerator", "market share"]) else "other"
        print(f"  id={sc.id} rel={sc.relevance:.3f} [{tag}] :: {text[:100]}")
    # Expect at least one of the explicitly relevant GPU-centric chunks to rank above a CSR/event chunk
    likely_relevant = [i for i in [0,2,4,6,8] if i in by_id]
    noise = [i for i in [1,3,5,9] if i in by_id]
    if likely_relevant and noise:
        assert max(by_id[i] for i in likely_relevant) >= max(by_id[i] for i in noise), "Expected at least one GPU/roadmap/design win chunk to outrank generic CSR/event content"


def test_parse_scores_direct():
    raw = "Some wrapper text [ {\"id\":0, \"relevance\":0.9, \"rationale\":\"focuses on GPUs\", \"phrase\":\"GPU focus\"} ] tail"
    out = parse_scores(raw)
    assert out and out[0].id == 0 and out[0].relevance == 0.9 and out[0].phrase == "GPU focus"
