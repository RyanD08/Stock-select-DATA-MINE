#!/usr/bin/env python3
"""One-off backfill: populate the non-canonical `women_led` additional-
criteria field (proposed survey question "Supporting women-run companies",
see data/candidate_additional_criteria.json) across all already-processed
companies.

Not one of the 27 official survey questions -- per the founding materials
those are fixed, so this is logged/built as an additional-criteria field
rather than squeezed into schema/company_schema.json's numbered list.

Sourcing method: reads each company's latest DEF 14A proxy statement and
identifies which honorific (Mr./Ms./Mrs.) or, failing that, which pronoun
(she/her vs he/his) the filing itself consistently uses for whoever holds
the "Chief Executive Officer" title -- see find_ceo_gender_signal() in
lib.py for the full heuristic and its false-positive guards. This reads a
gendered reference the filing itself makes about a specific named person;
it never guesses gender from a first name. Confidence is Low (a flattened-
text regex heuristic, same class as founder_led/family_owned), with the
CEO's surname and the matched evidence text always shown in `notes` so a
result can be spot-checked quickly.
"""
import json
import sys

sys.path.insert(0, ".")
from lib import (  # noqa: E402
    get_submissions, latest_filing, filing_document_url, fetch_filing_text,
    find_ceo_gender_signal, field, none_field, save_json,
)

DATA_PATH = "data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def main():
    dataset = load()

    already_done = sum(1 for r in dataset if "women_led" in r)
    print(f"Resuming: {already_done}/{len(dataset)} already have a women_led field, will skip those.", flush=True)

    found = 0
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        if "women_led" in rec:
            continue

        cik = rec.get("cik")
        ticker = rec["ticker"]
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["women_led"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed_this_run += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving unset for a future retry", flush=True)
            continue

        sig = find_ceo_gender_signal(text)
        processed_this_run += 1
        if sig is None:
            rec["women_led"] = none_field(
                "No consistent CEO-name/honorific-or-pronoun pairing found in DEF 14A proxy text scan")
        else:
            is_woman, surname, evidence = sig
            rec["women_led"] = field(
                is_woman,
                f"DEF 14A proxy statement, filed {proxy['filing_date']}", purl, "Low",
                f"CEO surname identified as '{surname}' via name+title adjacency in the proxy text; gender "
                f"determined from the filing's own honorific (Mr./Ms./Mrs.) or, where none was used, a "
                f"majority of pronoun references (she/her vs he/his) describing that person -- not inferred "
                f"from the first name. Not a manual bio read -- verify. Evidence: \"...{evidence[:200]}...\"")
            if is_woman:
                found += 1
                print(f"{ticker}: women_led -> True ({surname})", flush=True)

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved (women-led found so far: {found})", flush=True)

    save(dataset)
    print(f"Done. {found} companies identified as women-led this run ({processed_this_run} companies processed).")


if __name__ == "__main__":
    main()
