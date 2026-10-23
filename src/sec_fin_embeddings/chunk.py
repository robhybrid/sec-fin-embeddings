"""Extract MD&A / risk sections and chunk under model input limits."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    section: str  # mda | risk | other
    chunk_index: int
    text: str


# Heuristic Item markers common in HTML→text EDGAR filings.
_MDA_START = re.compile(
    r"(?:item\s*7[\.\s:\-]+|item\s*2[\.\s:\-]+)\s*"
    r"(?:management.?s?\s+discussion|md\s*&\s*a)",
    re.I,
)
_RISK_START = re.compile(
    r"item\s*1a[\.\s:\-]+\s*risk\s+factors",
    re.I,
)
_ITEM_BOUNDARY = re.compile(r"\n\s*item\s+\d+[a-z]?[\.\s:\-]", re.I)


def _slice_section(text: str, start_re: re.Pattern, max_chars: int = 120_000) -> str:
    m = start_re.search(text)
    if not m:
        return ""
    start = m.start()
    rest = text[start : start + max_chars]
    # Cut at next Item boundary after ~2k chars so we keep body
    bounds = list(_ITEM_BOUNDARY.finditer(rest))
    end = len(rest)
    for b in bounds:
        if b.start() > 800:
            end = b.start()
            break
    return rest[:end].strip()


def extract_sections(text: str) -> dict[str, str]:
    mda = _slice_section(text, _MDA_START)
    risk = _slice_section(text, _RISK_START)
    # Fallback: take head of document if markers missing (short 10-Q / iXBRL oddities)
    if not mda and not risk:
        return {"other": text[:40_000]}
    out = {}
    if mda:
        out["mda"] = mda
    if risk:
        out["risk"] = risk
    return out


def chunk_text(text: str, *, max_chars: int = 6000, overlap: int = 200) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + max_chars)
        # Prefer break on paragraph
        if j < n:
            cut = text.rfind("\n\n", i + max_chars // 2, j)
            if cut > i:
                j = cut
        piece = text[i:j].strip()
        if piece:
            chunks.append(piece)
        if j >= n:
            break
        i = max(i + 1, j - overlap)
    return chunks


def filing_chunks(
    full_text: str,
    *,
    sections: list[str] | None = None,
    max_chars: int = 6000,
    max_chunks_per_section: int = 3,
) -> list[Chunk]:
    sections = sections or ["mda", "risk"]
    extracted = extract_sections(full_text)
    out: list[Chunk] = []
    for sec in sections:
        body = extracted.get(sec) or ""
        if not body and sec == "mda":
            body = extracted.get("other") or ""
        parts = chunk_text(body, max_chars=max_chars)[:max_chunks_per_section]
        for idx, p in enumerate(parts):
            out.append(Chunk(section=sec, chunk_index=idx, text=p))
    # Ensure at least one chunk
    if not out:
        parts = chunk_text(full_text[: max_chars * 2], max_chars=max_chars)[:2]
        for idx, p in enumerate(parts):
            out.append(Chunk(section="other", chunk_index=idx, text=p))
    return out
