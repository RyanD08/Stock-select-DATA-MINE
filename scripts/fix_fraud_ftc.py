#!/usr/bin/env python3
"""One-off corrector: supplement fraud_corruption_scandal_history (Q11)
across all already-processed companies with FTC Legal Library case-search
hits, newly reachable in this environment. Only ever upgrades a record --
if no FTC case is name-matched, the existing SEC-full-text-search-only
field (or None) is left untouched."""
import json
import sys

sys.path.insert(0, ".")
from lib import get_submissions, ftc_case_search, field, save_json  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20
_FTC_MARKER = "FTC Legal Library case search ("


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def main():
    dataset = load()

    already_done = sum(1 for r in dataset
                        if _FTC_MARKER in (r.get("fraud_corruption_scandal_history", {}) or {}).get("notes", "") or "")
    print(f"Resuming: {already_done}/{len(dataset)} already carry an FTC-sourced note, will skip those.", flush=True)

    matched = 0
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        existing = rec.get("fraud_corruption_scandal_history", {}) or {}
        if _FTC_MARKER in (existing.get("notes") or ""):
            continue  # already has FTC data from a prior (resumed) run

        cik = rec.get("cik")
        name = rec["company_name"]
        entity_name = name
        if cik:
            try:
                sub = get_submissions(cik)
                entity_name = sub.get("name", name)
            except Exception:
                pass

        try:
            ftc_hits = ftc_case_search(entity_name)
        except Exception as e:
            print(f"{rec['ticker']}: FTC search failed ({e}), leaving as-is", flush=True)
            processed_this_run += 1
            continue

        processed_this_run += 1
        if not ftc_hits:
            if (processed_this_run % CHECKPOINT_EVERY) == 0:
                save(dataset)
                print(f"[{i + 1}/{len(dataset)}] checkpoint saved (matched so far: {matched})", flush=True)
            continue

        existing_value = existing.get("value") if isinstance(existing.get("value"), dict) else {}
        n_hits = existing_value.get("sec_fulltext_search_hits")

        value = {"ftc_case_count": ftc_hits["case_count"], "ftc_example_cases": ftc_hits["examples"]}
        notes = (f"FTC Legal Library case search ({ftc_hits['search_url']}) name-matched to {ftc_hits['case_count']} "
                 "case(s) -- see ftc_example_cases for titles/links, verify each is this company and not a "
                 "same-named unrelated party.")
        if n_hits:
            value["sec_fulltext_search_hits"] = n_hits
            notes += f" Also {n_hits} SEC EDGAR full-text search hit(s) across 8-K filings (name-matched, not confirmed litigation releases)."
        rec["fraud_corruption_scandal_history"] = field(
            value, "FTC Legal Library case search (ftc.gov) + SEC EDGAR full-text search (efts.sec.gov)",
            ftc_hits["search_url"], "Medium", notes)
        matched += 1
        print(f"{rec['ticker']}: fraud_corruption_scandal_history -> {ftc_hits['case_count']} FTC case(s) (Medium)", flush=True)

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved (matched so far: {matched})", flush=True)

    save(dataset)
    print(f"Done. {matched} newly upgraded this run with FTC-sourced data ({processed_this_run} companies processed).")


if __name__ == "__main__":
    main()
