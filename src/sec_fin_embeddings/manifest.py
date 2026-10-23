"""Append-only embedding manifest (CIK, accession, available_at, model, dim)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_done_accessions(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    done: set[str] = set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            acc = row.get("accession")
            if acc:
                done.add(str(acc))
    return done


def append_manifest(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
