#!/usr/bin/env python3
"""(Re)populate founder_led and family_owned for every company missing
either field, using the corrected find_founder_led()/find_family_owned()
(see lib.py). Targets any record where either field is absent entirely
(used after clearing both for a full re-run following a precision fix) --
not just a None-confidence stub, since the prior version of these
functions had real, confirmed false positives (an outside director's own
unrelated company bio; a large asset manager's controlling family showing
up in a beneficial-ownership footnote) as well as false negatives (a
verb-form founding bio the old noun-only regex could never match), so a
wrong previously-written value needs reprocessing, not skipping. Always
writes an explicit result for both fields, never leaves either key
silently unset, matching the rest of the dataset's convention of every
record having every field."""
import json
import sys

sys.path.insert(0, ".")
from lib import (  # noqa: E402
    get_submissions, latest_filing, filing_document_url, fetch_filing_text,
    find_founder_led, find_family_owned, field, none_field, save_json,
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

    targets = [r for r in dataset if "founder_led" not in r or "family_owned" not in r]
    print(f"{len(targets)}/{len(dataset)} companies to (re)check.", flush=True)

    founder_found = 0
    family_found = 0
    processed_this_run = 0
    for i, rec in enumerate(dataset):
        if "founder_led" in rec and "family_owned" in rec:
            continue

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

        founder_hit = find_founder_led(text, company_name)
        if founder_hit:
            rec["founder_led"] = field(
                True, f"DEF 14A officer/director bios, filed {proxy['filing_date']}", purl, "Low",
                f"Name-anchored regex match on the registrant's own identified CEO/Executive Chair having "
                f"founder language tied to their name: '{founder_hit.strip()[:300]}'. Not a manual bio read "
                f"-- verify.")
            founder_found += 1
            print(f"{ticker}: founder_led -> True", flush=True)
        else:
            rec["founder_led"] = none_field(
                "No founder claim tied to the registrant's own identified CEO/Executive Chair found in proxy text scan")

        family_hit = find_family_owned(text)
        if family_hit:
            name, window = family_hit
            rec["family_owned"] = field(
                True, f"DEF 14A beneficial ownership section, filed {proxy['filing_date']}", purl, "Low",
                f"Text mentions '{name}' near ownership/voting-power language, not near a large asset manager "
                f"marker; percentage not automatically extracted -- verify manually. Context: "
                f"\"...{window.strip()[:200]}...\"")
            family_found += 1
            print(f"{ticker}: family_owned -> True ({name})", flush=True)
        else:
            rec["family_owned"] = none_field(
                "No '<Name> family' + ownership-context pattern (excluding large asset managers) found in proxy text scan")

        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved "
                  f"(founder_led so far: {founder_found}, family_owned so far: {family_found})", flush=True)

    save(dataset)
    print(f"Done. founder_led: {founder_found} True, family_owned: {family_found} True "
          f"({processed_this_run} companies checked this run).")


if __name__ == "__main__":
    main()
