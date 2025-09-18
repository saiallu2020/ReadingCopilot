from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any
import json
import os
import requests

@dataclass
class ScoredChunk:
    id: int
    relevance: float
    rationale: str
    phrase: str | None = None  # short cohesive label (1-4 words)

class BaseLLMClient(ABC):
    @abstractmethod
    def score_chunks(self, *, chunks: List[Dict[str, Any]], global_profile: str, document_goal: str) -> List[ScoredChunk]:
        ...

class AzureOpenAIClient(BaseLLMClient):
    """Azure OpenAI chat-based scorer using raw REST API (no SDK dependency).

    Env Vars:
      RC_AZURE_OPENAI_ENDPOINT      (required, e.g. https://<resource>.openai.azure.com)
      RC_AZURE_OPENAI_KEY           (required)
      RC_AZURE_OPENAI_DEPLOYMENT    (deployment name, default gpt-4o-mini)
      RC_AZURE_OPENAI_API_VERSION   (optional api-version, default 2024-05-01-preview)
      RC_AZURE_OPENAI_MAX_TOKENS    (max completion tokens, default 250)
    """
    def __init__(self):
        self.endpoint = os.environ.get("RC_AZURE_OPENAI_ENDPOINT")
        self.key = os.environ.get("RC_AZURE_OPENAI_KEY")
        if not self.endpoint or not self.key:
            raise RuntimeError("Missing RC_AZURE_OPENAI_ENDPOINT or RC_AZURE_OPENAI_KEY")
        self.deployment = os.environ.get("RC_AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        self.api_version = os.environ.get("RC_AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
        self.max_tokens = int(os.environ.get("RC_AZURE_OPENAI_MAX_TOKENS", "250"))

    def _build_messages(self, *, global_profile: str, document_goal: str, chunks: List[Dict[str, Any]]):
        payload = {
            "global_profile": global_profile.strip(),
            "document_goal": document_goal.strip(),
            "chunks": [{"id": c['id'], "text": c['text'][:1600]} for c in chunks]
        }
        system = (
            "You score provided PDF text chunks for relevance to the user's background and stated document goal. "
            "Return ONLY a JSON list of objects with keys: id (int), relevance (float 0-1), rationale (string <=25 words), phrase (string). "
            "phrase = ONE short cohesive human-friendly label 1-4 words (no quotes, no trailing punctuation) summarizing the chunk (e.g. AMD Instinct GPUs, Hyperscaler demand signal, Roadmap differentiation). "
            "No commentary before or after JSON."
        )
        user = json.dumps(payload, ensure_ascii=False)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def score_chunks(self, *, chunks: List[Dict[str, Any]], global_profile: str, document_goal: str) -> List[ScoredChunk]:
        if not chunks:
            return []
        messages = self._build_messages(global_profile=global_profile, document_goal=document_goal, chunks=chunks)
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
        body = {
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "n": 1,
        }
        headers = {
            "api-key": self.key,
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=60)
        except requests.RequestException as e:
            raise RuntimeError(f"Azure OpenAI network error: {e}")
        if resp.status_code != 200:
            raise RuntimeError(f"Azure OpenAI error {resp.status_code}: {resp.text[:400]}")
        try:
            j = resp.json()
            content = j['choices'][0]['message']['content']
        except Exception as e:
            raise RuntimeError(f"Unexpected Azure response format: {e}\nRaw: {resp.text[:400]}")
        try:
            return parse_scores(content)
        except Exception as e:
            raise RuntimeError(f"Failed to parse Azure JSON: {e}\nContent: {content[:400]}")


def build_llm_client() -> BaseLLMClient:
    """Factory retained for API stability; now always returns AzureOpenAIClient.

    Environment must provide RC_AZURE_OPENAI_ENDPOINT and RC_AZURE_OPENAI_KEY.
    """
    return AzureOpenAIClient()


def parse_scores(raw: str) -> List[ScoredChunk]:
    """Parse a raw JSON (or wrapped) string of scored chunks into ScoredChunk list.

    Exposed separately for unit testing robustness of JSON extraction.
    Accepts either a direct JSON list or text containing exactly one JSON list substring.
    """
    import json as _json
    first = raw.find('[')
    last = raw.rfind(']')
    if first != -1 and last != -1 and last > first:
        snippet = raw[first:last+1]
    else:
        snippet = raw
    try:
        arr = _json.loads(snippet)
    except Exception as e:
        # Fallback: attempt to recover partial / truncated JSON array produced by model
        # by incrementally extracting completed top-level objects while ignoring the rest.
        # This handles cases where generation stops mid-object due to token limits.
        recovered = []
        in_string = False
        escape = False
        brace_depth = 0
        collecting = False
        buf_chars: List[str] = []  # type: ignore
        # Work only on the portion after the first '[' (if any) to reduce noise.
        work = raw[first+1:] if first != -1 else raw
        for ch in work:
            if collecting:
                buf_chars.append(ch)
            if ch == '"' and not escape:
                in_string = not in_string
            if in_string and ch == '\\' and not escape:
                escape = True
            else:
                escape = False
            if not in_string:
                if ch == '{':
                    if not collecting:
                        collecting = True
                        buf_chars = ['{']  # restart buffer including this brace
                        brace_depth = 1
                        continue
                    else:
                        brace_depth += 1
                elif ch == '}' and collecting:
                    brace_depth -= 1
                    if brace_depth == 0:
                        # Completed one object
                        obj_text = ''.join(buf_chars)
                        collecting = False
                        try:
                            obj = _json.loads(obj_text)
                            recovered.append(obj)
                        except Exception:
                            # Ignore malformed object
                            pass
            # Early exit optimization: if a closing ']' is hit outside a string and not collecting.
            if ch == ']' and not in_string and not collecting:
                break
        if not recovered:
            raise ValueError(f"Unable to parse scores JSON: {e}")
        arr = recovered
    out: List[ScoredChunk] = []
    for item in arr:
        try:
            out.append(ScoredChunk(
                id=int(item['id']),
                relevance=float(item['relevance']),
                rationale=str(item.get('rationale','')),
                phrase=(str(item.get('phrase')).strip() if item.get('phrase') else None)
            ))
        except Exception:
            continue
    return out
