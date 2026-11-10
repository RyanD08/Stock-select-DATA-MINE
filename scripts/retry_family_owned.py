#!/usr/bin/env python3
"""Step 3.5 (founder-led/family-owned/women-led gaps): re-resolve family_owned for
every company currently confidence=None, using the widened
_BENEFICIAL_OWNERSHIP_SECTION heading patterns (see lib.py) that now also
recognize "Stock Ownership of ... Beneficial Owners" (Alphabet), "Persons Owning
More than 5% of <Company>" (Air Products), "Security ownership of executive
officers and directors" (Abbott), and "Ownership of Voting Securities" (Alliant
Energy) as valid Item 403 disclosure headings. Regression-tested against a
40-company sample with 0 disagreements.

Only touches records currently confidence=None. Checkpoints every 20, resumable."""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, resolve_family_owned_field, none_field, save_json  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset if r["family_owned"]["confidence"] == "None"]
    print(f"{len(dataset)} companies loaded; {len(candidates)} family_owned gaps to retry.", flush=True)

    true_hits = 0
    false_hits = 0
    still_none = 0
    processed = 0
    for i, rec in enumerate(candidates):
        ticker = rec["ticker"]
        cik = rec["cik"]
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["family_owned"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        result = resolve_family_owned_field(text, purl, proxy["filing_date"])
        rec["family_owned"] = result
        if result["confidence"] == "None":
            still_none += 1
        elif result["value"] is True:
            true_hits += 1
            print(f"{ticker}: TRUE", flush=True)
        else:
            false_hits += 1

        if (processed % CHECKPOINT_EVERY) == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{processed}/{len(candidates)}] checkpoint saved | true={true_hits} false={false_hits} still_none={still_none}", flush=True)

    save_json(DATA_PATH, dataset)
    print(f"Done. true={true_hits} false={false_hits} still_none={still_none} (of {processed} processed, {len(candidates)} candidates).", flush=True)


if __name__ == "__main__":
    main()
