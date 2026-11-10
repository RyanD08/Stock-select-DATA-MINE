#!/usr/bin/env python3
"""Step 3.4 (DEF 14A governance gaps): retry ceo_pay_ratio for every company
currently confidence=None, using the newly-added find_pay_ratio() patterns (see
lib.py) for two phrasings the original pattern set missed:
  - "...median employee was $X, resulting in a ratio of 166:1" (Abbott) -- the
    compensation/median/employee context word comes BEFORE "ratio" with no
    "is/was/were" governing the ratio itself.
  - "...resulting in a ratio of those amounts of 1-to-51" (Amazon) -- an inverted
    employee:CEO "1 to N" order instead of the far more common CEO:employee "N to 1".

Regression-tested against a 40-company sample of already-populated records before
this script was written: 1 disagreement found (AMCR, stored 119 vs. a freshly-
verified-correct 246 -- a pre-existing mis-extraction from an unrelated country
employee-headcount table, logged to manual_review_needed.md, NOT auto-corrected).
Per this project's "never overwrite an existing value" rule, this script -- like
every other retry script here -- only ever touches records currently confidence=None.
Checkpoints every 20, resumable."""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, find_pay_ratio, field, none_field, save_json  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset if r["ceo_pay_ratio"]["confidence"] == "None"]
    print(f"{len(dataset)} companies loaded; {len(candidates)} ceo_pay_ratio gaps to retry.", flush=True)

    filled = 0
    still_none = 0
    processed = 0
    for i, rec in enumerate(candidates):
        ticker = rec["ticker"]
        cik = rec["cik"]
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["ceo_pay_ratio"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        pay_ratio = find_pay_ratio(text)
        if pay_ratio:
            rec["ceo_pay_ratio"] = field(pay_ratio, f"DEF 14A Pay Ratio Disclosure, filed {proxy['filing_date']}", purl, "High")
            filled += 1
            print(f"{ticker}: {pay_ratio}", flush=True)
        else:
            still_none += 1
            rec["ceo_pay_ratio"] = none_field("Pay ratio pattern not found in proxy text scan (retried 2026-11-10 with expanded phrasing patterns)")

        if (processed % CHECKPOINT_EVERY) == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{processed}/{len(candidates)}] checkpoint saved | filled={filled} still_none={still_none}", flush=True)

    save_json(DATA_PATH, dataset)
    print(f"Done. filled={filled} still_none={still_none} (of {processed} processed, {len(candidates)} candidates).", flush=True)


if __name__ == "__main__":
    main()
