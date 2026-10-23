"""Fetch → chunk → embed → upsert one filing (or a shard)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .chunk import filing_chunks
from .edgar import FilingRef, fetch_text, html_to_text, resolve_primary_url
from .embed import embed_batch
from .manifest import append_manifest
from .quota import snapshot
from .store import VectorStore


def _chunk_id(accession: str, section: str, idx: int) -> str:
    raw = f"{accession}:{section}:{idx}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def process_filing(
    ref: FilingRef,
    store: VectorStore,
    *,
    manifest_path: str,
    model: str = "gemini-embedding-001",
    dim: int = 768,
    max_chars: int = 6000,
    batch_size: int = 4,
    user_agent: str = "sec-fin-embeddings/0.1 (filings@robhybrid.dev)",
    max_rps: float = 8.0,
) -> dict[str, Any]:
    url = resolve_primary_url(ref, user_agent=user_agent, max_rps=max_rps)
    html = fetch_text(url, user_agent=user_agent, max_rps=max_rps)
    text = html_to_text(html)
    chunks = filing_chunks(text, max_chars=max_chars)
    rows: list[dict[str, Any]] = []
    api_calls = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vectors = embed_batch(
            [c.text for c in batch],
            model=model,
            output_dimensionality=dim,
        )
        api_calls += 1
        for c, vec in zip(batch, vectors):
            rows.append(
                {
                    "id": _chunk_id(ref.accession, c.section, c.chunk_index),
                    "cik": str(ref.cik),
                    "accession": ref.accession,
                    "form": ref.form,
                    "filing_date": str(ref.filing_date),
                    "available_at": str(ref.available_at),
                    "symbols": ref.symbols,
                    "section": c.section,
                    "chunk_index": c.chunk_index,
                    "model": model,
                    "dim": dim,
                    "url": url,
                    "text": c.text[:2000],
                    "vector": vec,
                }
            )
    store.upsert(rows)
    meta = {
        "cik": str(ref.cik),
        "accession": ref.accession,
        "form": ref.form,
        "filing_date": str(ref.filing_date),
        "available_at": str(ref.available_at),
        "symbols": ref.symbols,
        "model": model,
        "dim": dim,
        "n_chunks": len(rows),
        "api_calls": api_calls,
        "embedded_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
    }
    append_manifest(manifest_path, [meta])
    return {**meta, "quota": snapshot()}
