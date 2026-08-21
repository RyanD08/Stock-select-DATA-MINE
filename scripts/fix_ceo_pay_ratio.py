#!/usr/bin/env python3
"""One-off backfill: re-run the corrected find_pay_ratio() (see lib.py)
against every company currently at ceo_pay_ratio confidence None with
notes "Pay ratio pattern not found in proxy text scan" -- the old regex
required "is <number> to 1" immediately, which missed the dominant real
phrasing ("was ... estimated to be ...", "N times that of the median
employee", abbreviations like "Mr." breaking the character-budget regex).
Only ever upgrades a record; already-High records are left untouched."""
import json
import sys

sys.path.insert(0, ".")
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, find_pay_ratio, field, save_json  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20
_STUB_NOTE = "Pay ratio pattern not found in proxy text scan"


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def main():
    dataset = load()

    targets = [r for r in dataset if (r.get("ceo_pay_ratio", {}) or {}).get("notes") == _STUB_NOTE]
    print(f"{len(targets)}/{len(dataset)} companies to re-check (ceo_pay_ratio None, pattern not found previously).", flush=True)

    recovered = 0
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        if (rec.get("ceo_pay_ratio", {}) or {}).get("notes") != _STUB_NOTE:
            continue

        cik = rec.get("cik")
        ticker = rec["ticker"]
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                processed_this_run += 1
                continue
            url = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(url)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving unset for a future retry", flush=True)
            continue

        processed_this_run += 1
        ratio = find_pay_ratio(text)
        if ratio is not None:
            rec["ceo_pay_ratio"] = field(
                ratio, f"DEF 14A Pay Ratio Disclosure, filed {proxy['filing_date']}", url, "High")
            recovered += 1
            print(f"{ticker}: ceo_pay_ratio -> {ratio}", flush=True)

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved (recovered so far: {recovered})", flush=True)

    save(dataset)
    print(f"Done. {recovered} companies newly recovered ({processed_this_run} companies re-checked this run).")


if __name__ == "__main__":
    main()
