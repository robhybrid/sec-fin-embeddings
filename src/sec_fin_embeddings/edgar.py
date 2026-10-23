"""EDGAR fetch with User-Agent and ≤10 req/s pacing."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

_DEFAULT_UA = "sec-fin-embeddings/0.1 (open collaborative research; contact via GitHub issues)"
_lock = threading.Lock()
_last_req = 0.0


@dataclass
class FilingRef:
    cik: str
    accession: str
    form: str
    filing_date: str
    available_at: str
    url: str
    symbols: str
    primary_doc: str = ""


def _pace(max_rps: float = 8.0) -> None:
    global _last_req
    min_gap = 1.0 / max(0.1, max_rps)
    with _lock:
        now = time.time()
        wait = min_gap - (now - _last_req)
        if wait > 0:
            time.sleep(wait)
        _last_req = time.time()


def fetch_text(url: str, *, user_agent: str = _DEFAULT_UA, max_rps: float = 8.0, timeout: float = 60.0) -> str:
    _pace(max_rps)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def accession_to_index_url(cik: str, accession: str) -> str:
    cik_i = str(int(str(cik).lstrip("0") or "0"))
    acc = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{accession}-index.htm"


def resolve_primary_url(ref: FilingRef, *, user_agent: str = _DEFAULT_UA, max_rps: float = 8.0) -> str:
    """Prefer explicit URL / primary_doc; else parse filing index."""
    if ref.url and ref.url.endswith((".htm", ".html", ".txt")):
        return ref.url
    if ref.primary_doc:
        cik_i = str(int(str(ref.cik).lstrip("0") or "0"))
        acc = ref.accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{ref.primary_doc}"
    index_url = accession_to_index_url(ref.cik, ref.accession)
    html = fetch_text(index_url, user_agent=user_agent, max_rps=max_rps)
    # Prefer primary HTML document link
    m = re.search(r'href="([^"]+\.htm)"[^>]*>\s*[^<]*(?:10-[KQ]|FORM)', html, re.I)
    if not m:
        m = re.search(r'href="(\d+/[^"]+\.htm)"', html, re.I)
    if not m:
        raise FileNotFoundError(f"no primary HTML for {ref.accession}")
    href = m.group(1)
    if href.startswith("http"):
        return href
    cik_i = str(int(str(ref.cik).lstrip("0") or "0"))
    acc = ref.accession.replace("-", "")
    if "/" in href:
        return f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{href.lstrip('/')}"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_i}/{acc}/{href}"


def html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
