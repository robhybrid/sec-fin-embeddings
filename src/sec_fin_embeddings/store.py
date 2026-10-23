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
        # LanceDB expects a list of row dicts (vector + metadata).
        data = []
        for r in rows:
            row = {k: v for k, v in r.items()}
            # Ensure vector is a plain list[float]
            row["vector"] = list(row["vector"])
            data.append(row)
        if self._tbl is None:
            self._tbl = self._db.create_table(self.table, data=data, mode="overwrite")
        else:
            self._tbl.add(data)
        return len(rows)

    def count(self) -> int:
        if self._tbl is None:
            return 0
        return int(self._tbl.count_rows())

    def _refresh(self) -> None:
        names = set(self._db.list_tables()) if hasattr(self._db, "list_tables") else set(self._db.table_names())
        if self.table in names:
            self._tbl = self._db.open_table(self.table)


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


class DualStore(VectorStore):
    """Write JSONL (portable) + best-effort LanceDB (local disk / object storage)."""

    def __init__(self, primary: VectorStore, secondary: VectorStore | None = None):
        self.primary = primary
        self.secondary = secondary

    def upsert(self, rows: list[dict[str, Any]]) -> int:
        n = self.primary.upsert(rows)
        if self.secondary is not None:
            try:
                self.secondary.upsert(rows)
            except Exception as e:
                # Don't lose embeddings if LanceDB FS lacks rename (FUSE/NFS quirks).
                print(f"WARN secondary store upsert failed: {e}", flush=True)
        return n

    def count(self) -> int:
        return self.primary.count()


def open_store(backend: str | None = None, **kwargs) -> VectorStore:
    backend = (backend or os.environ.get("VECTOR_STORE_BACKEND") or "jsonl+lancedb").lower()
    jsonl_path = kwargs.get("jsonl") or os.environ.get("VECTOR_JSONL", "artifacts/vectors.jsonl")
    lance_uri = kwargs.get("uri") or os.environ.get(
        "LANCEDB_URI",
        # Prefer local disk — some project stores block atomic rename Lance needs.
        os.path.join(os.environ.get("TMPDIR", "/tmp"), "sec-fin-embeddings-lancedb"),
    )
    table = kwargs.get("table") or os.environ.get("LANCEDB_TABLE", "filings_chunks")

    if backend in ("jsonl", "jsonl+lancedb", "dual"):
        primary = JsonlFallbackStore(jsonl_path)
        if backend == "jsonl":
            return primary
        try:
            secondary: VectorStore | None = LanceStore(lance_uri, table)
        except Exception as e:
            print(f"WARN LanceDB unavailable ({e}); JSONL only", flush=True)
            secondary = None
        return DualStore(primary, secondary)
    if backend == "lancedb":
        return LanceStore(lance_uri, table)
    if backend in ("pinecone", "supabase"):
        raise NotImplementedError(
            f"{backend} backend selected — set credentials and implement adapter, "
            "or keep jsonl+lancedb until maintainers vote (see GOVERNANCE.md)."
        )
    raise ValueError(f"unknown vector store backend: {backend}")
