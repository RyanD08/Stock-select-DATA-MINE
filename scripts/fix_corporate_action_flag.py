#!/usr/bin/env python3
"""One-off corrector: re-scans recent_corporate_action_flag for every company
currently flagged True under the old, overly-broad keyword match (bare
"merger"/"spin-off" mentions, which are boilerplate risk-factor language in
almost every 10-K) using the new completion-language-required regex. Only
refetches the 10-K for companies that need rechecking -- much cheaper than a
full reprocess since it skips EPA/OSHA/DEF14A/XBRL calls entirely."""
import sys
sys.path.insert(0, ".")
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, RECENT_CORPORATE_ACTION_PATTERN, save_json, TODAY  # noqa: E402
import json

DATA_PATH = "data/sp500_full_dataset.json"


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    to_check = [r for r in dataset if r["processing_status"] == "complete"
                and r.get("recent_corporate_action_flag", {}).get("value") is True
                and r.get("cik")]
    print(f"Rechecking {len(to_check)} companies flagged True under the old logic...")

    changed = 0
    for i, rec in enumerate(to_check):
        ticker = rec["ticker"]
        try:
            sub = get_submissions(rec["cik"])
            tenk = latest_filing(sub, "10-K")
            if not tenk:
                # No 10-K on file at all -- this is the XOM-style genuine flag, leave as-is.
                continue
            url = filing_document_url(rec["cik"], tenk["accession"], tenk["primary_doc"])
            txt = fetch_filing_text(url)
            low = txt.lower()
            m = RECENT_CORPORATE_ACTION_PATTERN.search(low)
            if m:
                rec["recent_corporate_action_flag"] = {
                    "value": True,
                    "notes": f"10-K (filed {tenk['filing_date']}) references a completed merger/spin-off/separation ('{m.group(0)}') -- verify recency and treat single-year financial comparisons with caution.",
                }
            else:
                rec["recent_corporate_action_flag"] = {"value": False, "notes": None}
                changed += 1
        except Exception as e:
            print(f"  {ticker}: fetch failed ({e}), leaving as-is")
        if (i + 1) % 20 == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{i+1}/{len(to_check)}] checkpoint saved, {changed} corrected so far")

    save_json(DATA_PATH, dataset)
    print(f"Done. {changed}/{len(to_check)} corrected from True to False.")


if __name__ == "__main__":
    main()
