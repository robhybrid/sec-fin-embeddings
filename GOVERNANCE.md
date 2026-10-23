# Governance — vector store & project direction

## Default store

Until maintainers vote otherwise, the **default vector database** is the one operated
(and paid for) by the founding maintainer:

| Setting | Default |
|---|---|
| Backend | LanceDB (local / object-storage URI), syncable to a paid host |
| Paid option | Founding maintainer may point `VECTOR_STORE_BACKEND` / URI at a paid Pinecone, Supabase pgvector, or hosted LanceDB |
| Git | Holds **code + manifests only** — not bulk vectors (no git-LFS bloat) |

Contributors keep working against the same embedding model (`gemini-embedding-001`,
768-d by default) and the append-only `manifests/embedded.jsonl` schema so shards
remain mergeable after a store migration.

## Changing the default store

Maintainers can **outvote** the founding default and move vectors to a community-paid
or alternate store.

1. Open an issue titled `GOVERNANCE: change vector store` with:
   - proposed backend + hosting
   - who pays
   - migration plan for existing manifests (re-upsert vs re-embed)
   - cutover date
2. Discussion period: **≥7 days**.
3. Vote among **maintainers** listed in `CODEOWNERS` / GitHub team (1 person = 1 vote).
4. Passes with **simple majority** (>50% of maintainers who vote). Ties keep the current default.
5. Merging the config PR that switches `config/defaults.yaml` + docs is the formal cutover.

The founding maintainer’s paid DB remains the default **until** such a vote passes.
A failed vote does not obligate anyone to keep paying for a rejected store.

## Shards & claims

Ticker ranges and year ranges are claimed in `data/shards/*.md` (see CONTRIBUTING).
Claims are social convention + CI manifest checks, not a blockchain. Duplicate
accessions are skipped via the shared manifest.

## Quotas

- Embedding traffic uses Google AI Studio **free** embedding limits at **≤80%**
  (`config/free_tier_limits.yaml`).
- Do not burn paid Google quota without an explicit maintainer decision.
- EDGAR: identify via User-Agent; stay ≤10 requests/second.

## Making the repo public

This repository starts **private**. Visibility flips to **public** on **2026-10-24**
(see `.github/workflows/make-public.yml` and `scripts/make_public_when_due.py`).
