#!/usr/bin/env python3
"""One-off backfill: populate Q21 (countries_of_concern_operations) and Q22
(data_privacy_practices), both previously stubbed to None, across all
already-processed companies.

Q21: reads each company's latest 10-K for (a) SEC Section 13(r) of the
Exchange Act, a purpose-built mandatory disclosure item for Iran/Syria-
connected dealings whose mere presence is high-precision (see
find_countries_of_concern() in lib.py), and (b) an OFAC-comprehensively-
sanctioned-country name sitting near real operational-presence language.

Q22: searches EDGAR full-text search, scoped to the company's own CIK, for
8-K Item 1.05 filings (material cybersecurity incidents, SEC rule
effective December 2023) -- see cybersecurity_incident_search() in lib.py.

Both only ever fill an unset field; already-populated records are skipped
so this script is resumable.
"""
import json
import sys

sys.path.insert(0, ".")
from lib import (  # noqa: E402
    get_submissions, latest_filing, filing_document_url, fetch_filing_text,
    find_countries_of_concern, cybersecurity_incident_search, field, none_field, save_json,
)

DATA_PATH = "data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def do_q21(rec, cik, submissions):
    tenk = latest_filing(submissions, "10-K")
    if not tenk:
        rec["countries_of_concern_operations"] = none_field("No 10-K found/fetchable on EDGAR")
        return
    url = filing_document_url(cik, tenk["accession"], tenk["primary_doc"])
    text = fetch_filing_text(url)
    coc = find_countries_of_concern(text)
    if coc:
        countries = list(coc["countries"])
        if coc["section_13r"] and "Iran" not in countries:
            countries = sorted(countries + ["Iran (Section 13(r) disclosure)"])
        notes = ("Section 13(r) of the Exchange Act (Iran Threat Reduction and Syria Human Rights Act) "
                  "disclosure present in this filing -- a company only includes this section when it has "
                  "actual Iran/Syria-connected activity to report. " if coc["section_13r"] else "")
        if coc["evidence"]:
            notes += ("Country name(s) matched near operational-presence language (subsidiary/facility/"
                       "revenue/etc.), not a bare mention: " +
                       "; ".join(f"{c}: \"...{ev[:150]}...\"" for c, ev in coc["evidence"].items()))
        rec["countries_of_concern_operations"] = field(
            countries, f"10-K Item 1/1A text scan + Section 13(r) disclosure, filed {tenk['filing_date']}",
            url, "High" if coc["section_13r"] else "Medium", notes)
    else:
        rec["countries_of_concern_operations"] = field(
            [], f"10-K text scan, filed {tenk['filing_date']}", url, "Low",
            "No OFAC-comprehensively-sanctioned-country name found near operational-presence language, and "
            "no Section 13(r) Iran/Syria disclosure in this filing. Scope is deliberately narrow (Russia, "
            "Iran, North Korea, Syria, Cuba, Belarus, Venezuela) -- does not cover countries under only "
            "sectoral/targeted sanctions (e.g. China).")


def do_q22(rec, cik):
    cyber = cybersecurity_incident_search(cik)
    if cyber is None:
        rec["data_privacy_practices"] = none_field("SEC EDGAR full-text search (Item 1.05) request failed")
    elif cyber["incident_count"] > 0:
        rec["data_privacy_practices"] = field(
            {"item_1_05_incident_count": cyber["incident_count"], "examples": cyber["examples"]},
            "SEC EDGAR full-text search (efts.sec.gov), 8-K Item 1.05 filings", cyber["search_url"], "Medium",
            f"{cyber['incident_count']} material-cybersecurity-incident 8-K(s) (SEC Item 1.05, rule effective "
            "December 2023) filed under this company's own CIK -- self-disclosed, not a third-party finding.")
    else:
        rec["data_privacy_practices"] = field(
            {"item_1_05_incident_count": 0}, "SEC EDGAR full-text search (efts.sec.gov), 8-K Item 1.05 filings",
            cyber["search_url"], "Low",
            "No Item 1.05 (material cybersecurity incident) 8-K filed under this company's own CIK. Item 1.05 "
            "only exists for incidents from December 2023 onward, so this does not rule out an incident before "
            "the rule took effect, or one judged immaterial.")


def main():
    dataset = load()

    def q21_is_stub(r):
        d21 = r.get("countries_of_concern_operations")
        return d21 is None or "not yet implemented" in (d21.get("notes") or "")

    def q22_is_stub(r):
        d22 = r.get("data_privacy_practices")
        return d22 is None or "not yet implemented" in (d22.get("notes") or "")

    already_done = sum(1 for r in dataset if not q21_is_stub(r) and not q22_is_stub(r))
    print(f"Resuming: {already_done}/{len(dataset)} already have both fields populated by this script, will skip those.", flush=True)

    processed_this_run = 0
    q21_hits = 0
    q22_hits = 0
    for i, rec in enumerate(dataset):
        needs_q21 = q21_is_stub(rec)
        needs_q22 = q22_is_stub(rec)
        if not needs_q21 and not needs_q22:
            continue

        cik = rec.get("cik")
        ticker = rec["ticker"]
        try:
            subs = get_submissions(cik) if needs_q21 else None
            if needs_q21:
                do_q21(rec, cik, subs)
                if rec["countries_of_concern_operations"]["value"]:
                    q21_hits += 1
                    print(f"{ticker}: Q21 -> {rec['countries_of_concern_operations']['value']}", flush=True)
            if needs_q22:
                do_q22(rec, cik)
                if isinstance(rec["data_privacy_practices"]["value"], dict) and rec["data_privacy_practices"]["value"].get("item_1_05_incident_count"):
                    q22_hits += 1
                    print(f"{ticker}: Q22 -> {rec['data_privacy_practices']['value']}", flush=True)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving unset for a future retry", flush=True)
            continue

        processed_this_run += 1
        if (processed_this_run % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved (Q21 hits: {q21_hits}, Q22 hits: {q22_hits})", flush=True)

    save(dataset)
    print(f"Done. Q21: {q21_hits} companies with a country flagged. Q22: {q22_hits} companies with a disclosed "
          f"incident. ({processed_this_run} companies processed this run.)")


if __name__ == "__main__":
    main()
