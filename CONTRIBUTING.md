# Contributing — claim a shard, embed more financials

Thanks for helping embed SPY ∪ Nasdaq-100 (and eventually broader) SEC filings.

## Help embed more financials; claim a shard

1. **Fork / get invited** to this private repo (public after 2026-10-24).
2. Pick an unclaimed shard — ticker range **or** year range — and open a PR that adds:

```markdown
<!-- data/shards/YYYY-claim-yourhandle.md -->
# Shard claim

- **Claimant:** @yourhandle
- **Tickers:** AAPL-AMZN  (or list)
- **Forms:** 10-K, 10-Q
- **Years:** 2024-2025
- **Status:** claimed | in-progress | done
- **Started:** 2026-10-24
```

3. Run the job locally or in Actions with your own `GEMINI_API_KEY` (free AI Studio).
4. Open a PR that **only** adds lines to `manifests/embedded.jsonl` (and optional
   shard status update). Do **not** commit vector blobs / LanceDB directories.
5. Maintainers merge manifests; vectors upsert into the **current default store**
   (see GOVERNANCE.md — community can outvote the paid default later).

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=...          # AI Studio key
export GEMINI_EMBED_QUOTA_FRACTION=0.8
export GEMINI_EMBED_QUOTA_FILE=/tmp/gemini-embed-quota.json
python scripts/run_job.py --max-filings 10
```

## Rules of the road

| Rule | Why |
|---|---|
| ≤80% of free embedding RPM/RPD/TPM | Leave headroom; documented in `config/free_tier_limits.yaml` |
| Separate quota file from chat/PM jobs | Avoid starving other Gemini workloads |
| EDGAR User-Agent + ≤10 req/s | SEC fair-access |
| Manifest required | Dedup + PIT (`available_at`) |
| No paid Google without vote | Free AI Studio only by default |

## Priority order

1. Recent **10-K / 10-Q** MD&A (Item 7 / Item 2) + risk (Item 1A)
2. SPY ∪ Nasdaq-100 tickers in `data/universe/`
3. Then older years (2008+) and optional 8-K item 2.02

## Code of conduct (short)

Be excellent. No scraping abuse. No leaking API keys. Disagreements about the
vector DB go through GOVERNANCE.md — not drive-by force-pushes.
