#!/usr/bin/env python3
"""Step 3.5 (founder-led/family-owned/women-led gaps): re-resolve women_led for
every company currently confidence=None, using find_ceo_gender_signal() now that
it also tries the reversed Title-then-Name CEO identification (see lib.py).
Regression-tested against a 40-company sample with 1 disagreement, traced to the
exact same proxy/filing already on file (not caused by this change -- the
reversed pattern contributed zero matches for that company) and left as-is since
this script never touches an already-real record anyway.

Only touches records currently confidence=None. Checkpoints every 20, resumable."""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, find_ceo_gender_signal, field, none_field, save_json  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset if r["women_led"]["confidence"] == "None"]
    print(f"{len(dataset)} companies loaded; {len(candidates)} women_led gaps to retry.", flush=True)

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
                rec["women_led"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        sig = find_ceo_gender_signal(text)
        if sig:
            is_woman, surname, evidence = sig
            rec["women_led"] = field(
                is_woman, f"DEF 14A proxy statement, filed {proxy['filing_date']}", purl, "Low",
                f"CEO surname identified as '{surname}' via name+title adjacency in the proxy text; gender "
                f"determined from the filing's own honorific (Mr./Ms./Mrs.) or, where none was used, a "
                f"majority of pronoun references (she/her vs he/his) describing that person -- not inferred "
                f"from the first name. Not a manual bio read -- verify. Evidence: \"...{evidence[:200]}...\"")
            if is_woman:
                true_hits += 1
                print(f"{ticker}: WOMAN ({surname})", flush=True)
            else:
                false_hits += 1
        else:
            still_none += 1
            rec["women_led"] = none_field("No consistent CEO-name/honorific-or-pronoun pairing found in DEF 14A proxy text scan (retried 2026-11-10 with reversed Title-then-Name pattern too)")

        if (processed % CHECKPOINT_EVERY) == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{processed}/{len(candidates)}] checkpoint saved | true={true_hits} false={false_hits} still_none={still_none}", flush=True)

    save_json(DATA_PATH, dataset)
    print(f"Done. true={true_hits} false={false_hits} still_none={still_none} (of {processed} processed, {len(candidates)} candidates).", flush=True)


if __name__ == "__main__":
    main()
