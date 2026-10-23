# sec-fin-embeddings

**Collaborative, free-tier pipeline:** fetch EDGAR 10-K/10-Q text for **SPY ∪ Nasdaq-100**,
chunk MD&A + risk, embed with **Google AI Studio** (`gemini-embedding-001`), upsert into a
vector store the founding maintainer can pay for — until maintainers **outvote** that default
([GOVERNANCE.md](./GOVERNANCE.md)).

> **Visibility:** private until **2026-10-24**, then public (scheduled workflow /
> `scripts/make_public_when_due.py`).

## Help embed more financials; claim a shard

We cannot burn the whole free embedding quota alone. **Claim a ticker range or year range**,
run the job with your own AI Studio key (≤80% of free embedding RPM/RPD/TPM), and PR only
the manifest lines.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the claim file format under `data/shards/`.

```text
Example claims:
  data/shards/2026-claim-alice-aapl-amzn.md   # tickers AAPL–AMZN, 2024–2025
  data/shards/2026-claim-bob-year-2019.md     # all universe tickers, year 2019
```

## What this does

```
EDGAR HTML  →  MD&A/risk chunks  →  gemini-embedding-001 (768-d)  →  LanceDB / paid store
                     ↓
              manifests/embedded.jsonl   (CIK, accession, available_at, model, dim)
```

- **Rate limit:** 80% of documented free embedding tier (100 RPM / 1000 RPD / 30k TPM →
  **80 / 800 / 24k**). Lock file: `/tmp/gemini-embed-quota.json` (separate from chat/PM
  `generateContent` quotas).
- **EDGAR:** User-Agent required; ≤10 req/s (we pace ~8).
- **No git-LFS vectors:** git keeps code + manifests; vectors live in the DB (or a private
  HF dataset export).

## Vector store & cost

| Backend | Role | Cost note |
|---|---|---|
| **JSONL + LanceDB** (default) | JSONL always; LanceDB on local/object URI | Free locally; object storage ≈ **$0.01–0.02/GB-mo** |
| Pinecone serverless | Optional paid default | Free starter then usage-based; switch via governance |
| Supabase pgvector | Optional paid default | Free 500 MB → Pro ~**$25/mo** |

Founding maintainer pays for the hosted default until a maintainer vote changes it.
Some FUSE volumes block Lance atomic rename — JSONL is the portable primary; point
`LANCEDB_URI` at paid object storage when ready.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=your_ai_studio_key
export GEMINI_EMBED_QUOTA_FRACTION=0.8
python scripts/run_job.py --filings-parquet /path/to/filings.parquet
```

Universe tickers: `data/universe/spy_ndx_tickers.txt`.

## Counts (order of magnitude)

See the project-store plan doc (linked from the Algo-trader store) for filings / chunks /
API calls / days at 80% free tier. Roughly:

| Scope | Priority 10-K/10-Q | API calls (≈1 batch/filing) | Days @ 800 RPD |
|---|---|---|---|
| SPY∪NDX last ~2y (arena window) | ~5.5k | ~5.5k–11k | **~7–14 days** |
| Same, richer chunking (~3 batches/filing) | ~5.5k | ~16k | **~21 days** |
| Union 2008+ estimate | ~40–45k | ~40k–135k | **~2–6 months** one key |

Many contributors claiming shards → wall clock drops linearly with keys/projects.

## License

Apache-2.0. Filing text remains subject to SEC / company copyright — we store short
excerpts for research embeddings, not full redistribution mirrors.
