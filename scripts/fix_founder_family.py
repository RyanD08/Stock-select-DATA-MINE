#!/usr/bin/env python3
"""(Re)populate founder_led and family_owned for every company, using
resolve_founder_led_field()/resolve_family_owned_field() (see lib.py).

These resolvers write an explicit False -- not just None -- whenever the
registrant's own CEO/Executive Chair (for founder_led) or its mandatory
Item 403 beneficial-ownership disclosure (for family_owned) was
successfully identified/located but no founder or family claim was found
tied to it. That's real, sourced negative evidence given how extensively
DEF 14A proxies narrate executive backgrounds and how completely Item 403
must disclose every 5%-or-greater owner -- not just an absence of a match,
and not the same as a genuine "couldn't verify" None (no CEO/Chair could
be identified by name at all; no beneficial-ownership section was found).

Targets every record so already-True values get re-validated against the
current code too (cheap, and catches drift if lib.py changes again), not
just the ones currently None. Always writes an explicit result for both
fields, never leaves either key silently unset."""
import json
import sys

sys.path.insert(0, ".")
from lib import (  # noqa: E402
    get_submissions, latest_filing, filing_document_url, fetch_filing_text,
    resolve_founder_led_field, resolve_family_owned_field, none_field, save_json,
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
    print(f"{len(dataset)} companies to (re)check.", flush=True)

    counts = {"founder_led": {True: 0, False: 0, "None": 0}, "family_owned": {True: 0, False: 0, "None": 0}}
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        cik = rec.get("cik")
        ticker = rec["ticker"]
        company_name = rec.get("company_name")
        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["founder_led"] = none_field("No DEF 14A found/fetchable on EDGAR")
                rec["family_owned"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed_this_run += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving unset for a future retry", flush=True)
            continue

        processed_this_run += 1

        fl = resolve_founder_led_field(text, company_name, purl, proxy["filing_date"])
        rec["founder_led"] = fl
        key = fl["value"] if fl["confidence"] != "None" else "None"
        counts["founder_led"][key] += 1
        if key is True:
            print(f"{ticker}: founder_led -> True", flush=True)

        fo = resolve_family_owned_field(text, purl, proxy["filing_date"])
        rec["family_owned"] = fo
        key = fo["value"] if fo["confidence"] != "None" else "None"
        counts["family_owned"][key] += 1
        if key is True:
            print(f"{ticker}: family_owned -> True", flush=True)

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved | "
                  f"founder_led T/F/None: {counts['founder_led'][True]}/{counts['founder_led'][False]}/{counts['founder_led']['None']} | "
                  f"family_owned T/F/None: {counts['family_owned'][True]}/{counts['family_owned'][False]}/{counts['family_owned']['None']}",
                  flush=True)

    save(dataset)
    print(f"Done. founder_led T/F/None: {counts['founder_led'][True]}/{counts['founder_led'][False]}/{counts['founder_led']['None']} | "
          f"family_owned T/F/None: {counts['family_owned'][True]}/{counts['family_owned'][False]}/{counts['family_owned']['None']} "
          f"({processed_this_run} companies checked this run).")


if __name__ == "__main__":
    main()
