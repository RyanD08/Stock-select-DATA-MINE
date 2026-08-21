#!/usr/bin/env python3
"""One-off backfill: re-run the corrected find_independent_directors_pct()
(see lib.py) against every company currently at board_transparency_
independence confidence None with notes "Independent-director percentage
not found in proxy text scan" -- the old regex only matched "N% of ...
independent" and a bare "N of M directors", missing reversed word order,
infographic-tile style, parenthetical, and "N out of M" phrasings. Only
ever upgrades a record; already-Medium records are left untouched."""
import json
import sys

sys.path.insert(0, ".")
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, find_independent_directors_pct, field, save_json  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20
_STUB_NOTE = "Independent-director percentage not found in proxy text scan"


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def main():
    dataset = load()

    targets = [r for r in dataset if (r.get("board_transparency_independence", {}) or {}).get("notes") == _STUB_NOTE]
    print(f"{len(targets)}/{len(dataset)} companies to re-check.", flush=True)

    recovered = 0
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        if (rec.get("board_transparency_independence", {}) or {}).get("notes") != _STUB_NOTE:
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
        pct = find_independent_directors_pct(text)
        if pct is not None:
            rec["board_transparency_independence"] = field(
                {"pct_independent_directors": pct}, f"DEF 14A, filed {proxy['filing_date']}", url, "Medium")
            recovered += 1
            print(f"{ticker}: board_transparency_independence -> {pct}%", flush=True)

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved (recovered so far: {recovered})", flush=True)

    save(dataset)
    print(f"Done. {recovered} companies newly recovered ({processed_this_run} companies re-checked this run).")


if __name__ == "__main__":
    main()
