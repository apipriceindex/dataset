#!/usr/bin/env python3
"""sync_hf.py — snapshot quotidien de l'index vers Hugging Face Datasets.

Tire all.json + pricing-history.csv depuis apipriceindex.com, aplatit les
modèles en models.csv (le viewer HF affiche un tableau → vitrine), génère la
carte dataset (YAML licence cc-by-4.0), pousse le tout vers le repo dataset
apipriceindex/llm-api-prices (créé automatiquement s'il n'existe pas).

Zéro maintenance : lancé par GitHub Actions (cron quotidien), auth par le
secret HF_TOKEN du repo — jamais dans le code. Garde-fous : index injoignable
ou incohérent (count=0, as_of absent) → exit 1, on ne pousse JAMAIS un
snapshot douteux ; le snapshot précédent reste en place sur HF.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

BASE = os.environ.get("APIPRICEINDEX_URL_BASE", "https://apipriceindex.com")
HF_REPO = os.environ.get("HF_DATASET_REPO", "apipriceindex/llm-api-prices")
UA = "apipriceindex-dataset-sync (+https://github.com/apipriceindex/dataset)"

CSV_FIELDS = [
    "id", "name", "provider_id", "provider_name", "base_model", "category",
    "context_window", "max_output", "release_date", "license", "open_weights",
    "input_usd_per_mtok", "output_usd_per_mtok", "cached_input_usd_per_mtok",
    "price_confidence", "price_verified_at", "price_source_url",
    "no_credit_card", "page",
]


def fetch(path: str) -> bytes:
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def flatten(models: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    for m in models:
        p = m.get("pricing") or {}
        w.writerow({
            "id": m["id"],
            "name": m["name"],
            "provider_id": m["provider"]["id"],
            "provider_name": m["provider"]["name"],
            "base_model": m.get("base_model") or "",
            "category": m.get("category") or "",
            "context_window": m.get("context_window") or "",
            "max_output": m.get("max_output") or "",
            "release_date": m.get("release_date") or "",
            "license": m.get("license") or "",
            "open_weights": m.get("open_weights") if m.get("open_weights") is not None else "",
            "input_usd_per_mtok": p.get("input_per_mtok", ""),
            "output_usd_per_mtok": p.get("output_per_mtok", ""),
            "cached_input_usd_per_mtok": p.get("cached_input_per_mtok") or "",
            "price_confidence": p.get("confidence") or "",
            "price_verified_at": p.get("verified_at") or "",
            "price_source_url": p.get("source_url") or "",
            "no_credit_card": m.get("no_credit_card", False),
            "page": m.get("page") or "",
        })
    return buf.getvalue()


def card(index: dict, n_history_rows: int) -> str:
    as_of = index.get("as_of") or "unknown"
    count = index.get("count", 0)
    return f"""---
license: cc-by-4.0
pretty_name: LLM API Price Index
language:
- en
tags:
- llm
- api
- pricing
- tokens
- costs
size_categories:
- n<1K
---

# LLM API Price Index — daily snapshot

Live, verified LLM API prices from [apipriceindex.com](https://apipriceindex.com).
**{count} tracked endpoints, index as of {as_of}.** Updated daily by an
automated sync ([source](https://github.com/apipriceindex/dataset)).

Every price is read from the provider's official pricing page, cross-checked,
and carries its verification date and source URL — no hand-waved numbers.

## Files

| File | Contents |
|---|---|
| `models.csv` | One row per tracked endpoint: provider, model, USD per 1M input/output/cached-input tokens, context window, license, verification date and source URL |
| `pricing-history.csv` | Price ledger: one row per (endpoint, date), a point recorded **only when the price actually changed** ({n_history_rows} rows) — grows more valuable every day |
| `all.json` | Full nested dataset with stability contract (`schema_version`) |

## Live sources (always fresher than this snapshot)

- Dataset endpoint: <https://apipriceindex.com/api/all.json>
- OpenAPI spec: <https://apipriceindex.com/openapi.json>
- MCP server for agents: `pip install apipriceindex-mcp` ([registry](https://registry.modelcontextprotocol.io): `io.github.apipriceindex/mcp`)
- Docs & stability contract: <https://apipriceindex.com/use-this-data/>

## License & attribution

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — free to use,
remix and republish, with attribution to
**API Price Index (apipriceindex.com)**.

Third-party benchmark scores (LMArena, Artificial Analysis, MTEB) are **not**
included: that data is not ours to redistribute.
"""


def main() -> int:
    # 1. Tirer et valider — jamais de push si la source est douteuse.
    try:
        index = json.loads(fetch("/api/all.json"))
        history = fetch("/api/pricing-history.csv")
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: index unreachable, keeping previous snapshot: {e}", file=sys.stderr)
        return 1
    models = index.get("models") or []
    if not index.get("as_of") or len(models) < 100:
        print(f"ERROR: index looks wrong (as_of={index.get('as_of')}, count={len(models)}), not pushing", file=sys.stderr)
        return 1
    n_history = max(0, history.decode("utf-8", "replace").count("\n") - 1)

    # 2. Construire le snapshot localement.
    tmp = Path(tempfile.mkdtemp())
    (tmp / "all.json").write_bytes(json.dumps(index, indent=1).encode())
    (tmp / "pricing-history.csv").write_bytes(history)
    (tmp / "models.csv").write_text(flatten(models), encoding="utf-8")
    (tmp / "README.md").write_text(card(index, n_history), encoding="utf-8")

    if os.environ.get("DRY_RUN"):
        print(f"DRY_RUN ok: {len(models)} models, as_of {index['as_of']}, {n_history} history rows → {tmp}")
        return 0

    # 3. Pousser vers HF (token: env HF_TOKEN, fourni par le secret Actions).
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(HF_REPO, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        folder_path=str(tmp),
        repo_id=HF_REPO,
        repo_type="dataset",
        commit_message=f"snapshot {index['as_of']} — {len(models)} endpoints",
    )
    print(f"pushed {HF_REPO}: {len(models)} models, as_of {index['as_of']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
