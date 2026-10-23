"""Vector store backends. Default: LanceDB (local / object storage).

Governance (GOVERNANCE.md) can outvote the default; keep config pluggable.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, rows: list[dict[str, Any]]) -> int:
        ...

    @abstractmethod
    def count(self) -> int:
        ...


class LanceStore(VectorStore):
    def __init__(self, uri: str, table: str = "filings_chunks"):
        self.uri = uri
        self.table = table
        Path(uri).mkdir(parents=True, exist_ok=True)
        import lancedb

        self._db = lancedb.connect(uri)
        self._tbl = None
        if table in self._db.table_names():
            self._tbl = self._db.open_table(table)

    def upsert(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        import pyarrow as pa

        # Flatten vector + metadata
        vectors = [r["vector"] for r in rows]
        meta = [{k: v for k, v in r.items() if k != "vector"} for r in rows]
        data = {k: [m.get(k) for m in meta] for k in meta[0]}
        data["vector"] = vectors
        if self._tbl is None:
            self._tbl = self._db.create_table(self.table, data=data, mode="overwrite")
        else:
            self._tbl.add(data)
        return len(rows)

    def count(self) -> int:
        if self._tbl is None:
            return 0
        return int(self._tbl.count_rows())


class JsonlFallbackStore(VectorStore):
    """Cheap local fallback if LanceDB unavailable: vectors as JSONL sidecar."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def upsert(self, rows: list[dict[str, Any]]) -> int:
        with self.path.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        return len(rows)

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open(encoding="utf-8") as f:
            return sum(1 for _ in f)


def open_store(backend: str | None = None, **kwargs) -> VectorStore:
    backend = (backend or os.environ.get("VECTOR_STORE_BACKEND") or "lancedb").lower()
    if backend == "lancedb":
        try:
            return LanceStore(
                kwargs.get("uri") or os.environ.get("LANCEDB_URI", "artifacts/lancedb"),
                kwargs.get("table") or os.environ.get("LANCEDB_TABLE", "filings_chunks"),
            )
        except Exception:
            return JsonlFallbackStore(
                kwargs.get("jsonl") or "artifacts/vectors.jsonl",
            )
    if backend == "jsonl":
        return JsonlFallbackStore(kwargs.get("jsonl") or "artifacts/vectors.jsonl")
    if backend in ("pinecone", "supabase"):
        # Placeholders: require secrets; fail loudly so governance switch is intentional.
        raise NotImplementedError(
            f"{backend} backend selected — set credentials and implement adapter, "
            "or keep lancedb until maintainers vote (see GOVERNANCE.md)."
        )
    raise ValueError(f"unknown vector store backend: {backend}")
