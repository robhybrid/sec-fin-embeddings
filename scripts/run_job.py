#!/usr/bin/env python3
"""Burn today's 80% embedding budget on SPY∪NDX priority filings."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sec_fin_embeddings.edgar import FilingRef  # noqa: E402
from sec_fin_embeddings.manifest import load_done_accessions  # noqa: E402
from sec_fin_embeddings.pipeline import process_filing  # noqa: E402
from sec_fin_embeddings.quota import limits_from_env, snapshot  # noqa: E402
from sec_fin_embeddings.store import open_store  # noqa: E402


def _norm_ticker(t: str) -> set[str]:
    t = t.strip().upper()
    return {t, t.replace(".", "-"), t.replace("-", ".")}


def load_universe(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out |= _norm_ticker(line)
    return out


def symbol_hit(symbols: str, universe: set[str]) -> bool:
    if not isinstance(symbols, str) or not symbols:
        return False
    parts = [p.strip().upper() for p in symbols.replace(";", ",").split(",") if p.strip()]
    return any(p in universe for p in parts)


def load_priority(parquet: Path, universe: set[str], forms: set[str]):
    import pandas as pd

    df = pd.read_parquet(
        parquet,
        columns=["cik", "form", "accession", "filing_date", "available_at", "url", "symbols", "primary_doc"],
    )
    df = df[df["form"].isin(forms)]
    df = df[df["symbols"].map(lambda s: symbol_hit(s, universe))]
    df = df.sort_values(["filing_date", "available_at"], ascending=False)
    return df


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "---\n"
    body += 'cursor:\n  subagentId: "bc-11d75004-1dff-560c-b333-c0232130c2f2"\n'
    body += f"updated: {payload.get('updated')}\n"
    body += "---\n\n"
    body += "# OSS embed job status\n\n"
    body += f"- **Updated (UTC):** {payload.get('updated')}\n"
    body += f"- **Repo:** {payload.get('repo_url', '(pending)')}\n"
    body += f"- **Model:** `{payload.get('model')}` dim={payload.get('dim')}\n"
    body += f"- **Quota:** {payload.get('calls_today')}/{payload.get('rpd_cap')} RPD today "
    body += f"(cap = {int(float(os.environ.get('GEMINI_EMBED_QUOTA_FRACTION', '0.8')) * 100)}% free tier)\n"
    body += f"- **Filings embedded this run:** {payload.get('filings_ok')}\n"
    body += f"- **Chunks upserted this run:** {payload.get('chunks')}\n"
    body += f"- **API calls this run:** {payload.get('api_calls')}\n"
    body += f"- **Errors this run:** {payload.get('errors')}\n"
    body += f"- **Stop reason:** {payload.get('stop_reason')}\n"
    body += f"- **Vector store:** {payload.get('store')}\n"
    body += f"- **Manifest:** `{payload.get('manifest')}`\n"
    if payload.get("last_accession"):
        body += f"- **Last accession:** `{payload.get('last_accession')}`\n"
    path.write_text(body, encoding="utf-8")
    # also machine-readable
    path.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--filings-parquet",
        default=os.environ.get(
            "FILINGS_PARQUET",
            "/cursor/stores/bc-01a152a9-5123-77cd-8241-728cc4fe5036/code/arena/data/pit/filings.parquet",
        ),
    )
    ap.add_argument("--universe", default=str(ROOT / "data/universe/spy_ndx_tickers.txt"))
    ap.add_argument("--manifest", default=str(ROOT / "manifests/embedded.jsonl"))
    ap.add_argument("--status", default="")
    ap.add_argument("--store-uri", default=str(ROOT / "artifacts/lancedb"))
    ap.add_argument("--max-filings", type=int, default=0, help="0 = until daily quota")
    ap.add_argument("--model", default="gemini-embedding-001")
    ap.add_argument("--dim", type=int, default=768)
    args = ap.parse_args()

    status_path = Path(
        args.status
        or os.environ.get(
            "EMBED_STATUS_PATH",
            "/cursor/stores/bc-01a152a9-5123-77cd-8241-728cc4fe5036/internal/oss-embed-job-status.md",
        )
    )

    os.environ.setdefault("GEMINI_EMBED_QUOTA_FILE", "/tmp/gemini-embed-quota.json")
    os.environ.setdefault("GEMINI_EMBED_QUOTA_FRACTION", "0.8")

    lim = limits_from_env()
    universe = load_universe(Path(args.universe))
    done = load_done_accessions(args.manifest)
    df = load_priority(Path(args.filings_parquet), universe, {"10-K", "10-Q"})
    todo = df[~df["accession"].astype(str).isin(done)]
    store = open_store("lancedb", uri=args.store_uri)

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "repo_url": os.environ.get("SEC_FIN_EMBEDDINGS_REPO", ""),
        "model": args.model,
        "dim": args.dim,
        "calls_today": snapshot()["calls_today"],
        "rpd_cap": lim.rpd,
        "filings_ok": 0,
        "chunks": 0,
        "api_calls": 0,
        "errors": 0,
        "stop_reason": "running",
        "store": f"lancedb:{args.store_uri}",
        "manifest": args.manifest,
        "last_accession": None,
        "priority_remaining": int(len(todo)),
        "priority_total": int(len(df)),
    }
    write_status(status_path, payload)

    n_ok = n_chunks = n_calls = n_err = 0
    stop = "completed_queue"
    for _, row in todo.iterrows():
        if args.max_filings and n_ok >= args.max_filings:
            stop = "max_filings"
            break
        snap = snapshot()
        if snap["remaining_rpd"] <= 0:
            stop = "daily_quota"
            break
        # Need at least 1 call headroom; leave 1 for safety if nearly empty
        ref = FilingRef(
            cik=str(row["cik"]),
            accession=str(row["accession"]),
            form=str(row["form"]),
            filing_date=str(row["filing_date"]),
            available_at=str(row["available_at"]),
            url=str(row.get("url") or ""),
            symbols=str(row["symbols"]),
            primary_doc=str(row.get("primary_doc") or ""),
        )
        try:
            meta = process_filing(
                ref,
                store,
                manifest_path=args.manifest,
                model=args.model,
                dim=args.dim,
            )
            n_ok += 1
            n_chunks += int(meta.get("n_chunks") or 0)
            n_calls += int(meta.get("api_calls") or 0)
            payload["last_accession"] = ref.accession
        except RuntimeError as e:
            if "daily budget exhausted" in str(e):
                stop = "daily_quota"
                break
            n_err += 1
            print(f"ERR {ref.accession}: {e}", flush=True)
        except Exception as e:
            n_err += 1
            print(f"ERR {ref.accession}: {e}\n{traceback.format_exc()}", flush=True)
        if (n_ok + n_err) % 5 == 0:
            payload.update(
                {
                    "updated": datetime.now(timezone.utc).isoformat(),
                    "calls_today": snapshot()["calls_today"],
                    "filings_ok": n_ok,
                    "chunks": n_chunks,
                    "api_calls": n_calls,
                    "errors": n_err,
                    "stop_reason": "running",
                    "priority_remaining": int(len(todo)) - n_ok,
                }
            )
            write_status(status_path, payload)
            print(
                f"progress filings={n_ok} chunks={n_chunks} api={n_calls} "
                f"quota={snapshot()['calls_today']}/{lim.rpd}",
                flush=True,
            )

    payload.update(
        {
            "updated": datetime.now(timezone.utc).isoformat(),
            "calls_today": snapshot()["calls_today"],
            "filings_ok": n_ok,
            "chunks": n_chunks,
            "api_calls": n_calls,
            "errors": n_err,
            "stop_reason": stop,
            "store_count": store.count(),
        }
    )
    write_status(status_path, payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
