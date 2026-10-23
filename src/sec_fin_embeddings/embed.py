"""Google AI Studio / Gemini embedContent client."""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from typing import Sequence

from .quota import acquire_embed_turn


def _estimate_tokens(texts: Sequence[str]) -> int:
    # Rough char/4 heuristic; used only for TPM pacing.
    return max(1, sum(max(1, len(t) // 4) for t in texts))


def _normalize_768(values: list[float]) -> list[float]:
    """gemini-embedding-001 truncated dims need manual L2 normalize."""
    n = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / n for v in values]


def embed_batch(
    texts: Sequence[str],
    *,
    model: str = "gemini-embedding-001",
    output_dimensionality: int = 768,
    task_type: str = "RETRIEVAL_DOCUMENT",
    api_key: str | None = None,
) -> list[list[float]]:
    """Embed up to N texts in one batchEmbedContents call (1 RPD)."""
    if not texts:
        return []
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    model_id = model if model.startswith("models/") else f"models/{model}"
    acquire_embed_turn(estimated_tokens=_estimate_tokens(texts))

    requests = []
    for t in texts:
        req: dict = {
            "model": model_id,
            "content": {"parts": [{"text": t}]},
            "taskType": task_type,
        }
        if output_dimensionality:
            req["outputDimensionality"] = int(output_dimensionality)
        requests.append(req)

    body = json.dumps({"requests": requests}).encode("utf-8")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"{model_id}:batchEmbedContents?key={key}"
    )
    last_err: Exception | None = None
    for attempt in range(6):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.load(resp)
            embs = out.get("embeddings") or []
            vectors: list[list[float]] = []
            for e in embs:
                vals = list(e.get("values") or [])
                if output_dimensionality and output_dimensionality != 3072:
                    vals = _normalize_768(vals)
                vectors.append(vals)
            if len(vectors) != len(texts):
                raise RuntimeError(f"expected {len(texts)} embeddings, got {len(vectors)}")
            return vectors
        except urllib.error.HTTPError as e:
            payload = e.read().decode("utf-8", "replace")
            last_err = RuntimeError(f"HTTP {e.code}: {payload[:500]}")
            if e.code in (429, 500, 503):
                time.sleep(min(120.0, 2.0 ** attempt + 1.0))
                continue
            raise last_err from e
    raise last_err or RuntimeError("embed failed")
