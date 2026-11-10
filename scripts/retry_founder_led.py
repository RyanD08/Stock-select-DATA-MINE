#!/usr/bin/env python3
"""Step 3.5 (founder-led/family-owned/women-led gaps): re-resolve founder_led for
every company currently confidence=None, using the reversed Title-then-Name CEO/
Executive-Chair identification added to lib.py (see _CEO_TITLE_NAME_REV /
_EXEC_CHAIR_TITLE_NAME_REV). Regression-tested against a 40-company sample of
already-resolved companies with 0 disagreements before this script was written.

Only touches records currently confidence=None. Checkpoints every 20, resumable."""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, resolve_founder_led_field, none_field, save_json  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset if r["founder_led"]["confidence"] == "None"]
    print(f"{len(dataset)} companies loaded; {len(candidates)} founder_led gaps to retry.", flush=True)

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
                rec["founder_led"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        result = resolve_founder_led_field(text, rec.get("company_name"), purl, proxy["filing_date"])
        rec["founder_led"] = result
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
