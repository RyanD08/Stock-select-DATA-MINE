#!/usr/bin/env python3
"""(Re)populate board_transparency_independence for every company missing
the field using the corrected find_independent_directors_pct() (see
lib.py). Targets any record where the field is absent entirely (used
after clearing it for a full re-run following a precision fix) -- not
just the old None-confidence stub, since a prior buggy version of this
function may have already written a wrong Medium-confidence value that
needs reprocessing, not skipping. Always writes an explicit result
(Medium with the percentage, or an explicit None field), never leaves
the key silently unset, to match the rest of the dataset's convention
of every record having every field."""
import json
import sys

sys.path.insert(0, ".")
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, find_independent_directors_pct, field, none_field, save_json  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def main():
    dataset = load()

    targets = [r for r in dataset if "board_transparency_independence" not in r]
    print(f"{len(targets)}/{len(dataset)} companies to (re)check.", flush=True)

    recovered = 0
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        if "board_transparency_independence" in rec:
            continue

        cik = rec.get("cik")
        ticker = rec["ticker"]
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["board_transparency_independence"] = none_field("No DEF 14A found/fetchable on EDGAR")
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
        else:
            rec["board_transparency_independence"] = none_field("Independent-director percentage not found in proxy text scan")

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved (recovered so far: {recovered})", flush=True)

    save(dataset)
    print(f"Done. {recovered} companies newly recovered ({processed_this_run} companies re-checked this run).")


if __name__ == "__main__":
    main()
