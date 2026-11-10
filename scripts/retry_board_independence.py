#!/usr/bin/env python3
"""Step 3.4 (DEF 14A governance gaps): re-resolve board_transparency_independence
for every company currently confidence=None, using resolve_board_independence_field()
(see lib.py), which adds two new recovery paths beyond the original prose-percentage
scan: the universal NYSE/Nasdaq exchange-compliance sentence ("the Board has determined
that all directors, other than <NAME>, are independent") computed against the proxy's
own director-nominee-table row count, and a named-positive-list house style (AT&T-style).

Investigation (2026-11-10) found the dominant cause of the original 348 gaps is
structural, not a missed phrasing: most proxies render their director table's
"Independent" column as a bare checkmark <img> with no text/alt equivalent at all
(confirmed on Apple's own table) -- unrecoverable from text, and not something this
project will guess at via image analysis. So a meaningful fraction of these 348 will
stay a genuine, honest None even after this retry; this is expected, not a bug.

Never touches a record that already has real (non-None) data. Checkpoints every 20,
resumable."""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, resolve_board_independence_field, none_field, save_json  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset if r["board_transparency_independence"]["confidence"] == "None"]
    print(f"{len(dataset)} companies loaded; {len(candidates)} board_transparency_independence gaps to retry.", flush=True)

    numeric = 0
    qualitative = 0
    still_none = 0
    processed = 0
    for i, rec in enumerate(candidates):
        ticker = rec["ticker"]
        cik = rec["cik"]
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["board_transparency_independence"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        result = resolve_board_independence_field(text, cik, purl, proxy["filing_date"])
        rec["board_transparency_independence"] = result
        if result["confidence"] == "None":
            still_none += 1
        elif result["value"].get("pct_independent_directors") is not None:
            numeric += 1
            print(f"{ticker}: {result['value']['pct_independent_directors']}%", flush=True)
        else:
            qualitative += 1
            print(f"{ticker}: qualitative", flush=True)

        if (processed % CHECKPOINT_EVERY) == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{processed}/{len(candidates)}] checkpoint saved | numeric={numeric} qualitative={qualitative} still_none={still_none}", flush=True)

    save_json(DATA_PATH, dataset)
    print(f"Done. numeric={numeric} qualitative={qualitative} still_none={still_none} (of {processed} processed, {len(candidates)} candidates).", flush=True)


if __name__ == "__main__":
    main()
