#!/usr/bin/env python3
"""Step 3.1 (parent/subsidiary + better-matching retry) for
environmental_pollution_violations, EPA ECHO only.

OSHA's establishment-search endpoint now returns a site-wide HTTP 403 for
this project's descriptive, compliant User-Agent (confirmed 2026-11-10,
even against www.osha.gov's own homepage, not just the establishment
search path) -- a new access block since the dataset was first built, not
something to route around. worker_safety_record retries are not possible
this session; see logs/manual_review_needed.md.

EPA ECHO, however, is reachable. Investigation found process_batch.py's
original EPA ECHO call already used the correct SEC EDGAR *legal* registrant
name (entity_name = submissions['name'], e.g. "3M CO" not "3M") -- so this
is not a name-matching bug. Spot-testing 15 of the 94 current gaps with the
exact same method just now succeeded for 14/15 (echo.epa.gov's own
Message=="Success"), strongly suggesting the EPA ECHO API was transiently
degraded on 2026-08-19/20 when this dataset was first populated, and a
clean re-run today recovers most of it.

Pass 1 (this script, cheap): plain re-run of epa_echo_summary(SEC legal
name) for every company whose environmental_pollution_violations is
currently a genuine gap (confidence None, not "No applicable facility
records"). Never touches a record that already has real data.

Pass 2 (retry_epa_echo_subsidiaries.py, more expensive): for whatever is
STILL a miss after pass 1, fall back to each company's SEC Exhibit 21
subsidiary list and retry under US-jurisdiction subsidiary names -- the
real "resolve to subsidiaries" step, for companies where even the correct
parent legal name genuinely doesn't match (e.g. a holding company whose
operating subsidiaries are the ones that actually hold EPA permits)."""
import sys

sys.path.insert(0, ".")
from lib import get_submissions, epa_echo_summary, field, none_field, save_json  # noqa: E402
import json

DATA_PATH = "../data/sp500_full_dataset.json"
CHECKPOINT_EVERY = 20


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset
                  if r["environmental_pollution_violations"]["confidence"] == "None"
                  and r["environmental_pollution_violations"]["value"] != "No applicable facility records"]
    print(f"{len(candidates)} companies to retry.", flush=True)

    filled = 0
    still_missing = 0
    processed = 0
    for i, rec in enumerate(candidates):
        ticker = rec["ticker"]
        cik = rec["cik"]
        try:
            subs = get_submissions(cik)
            entity_name = subs.get("name", rec["company_name"])
            echo = epa_echo_summary(entity_name)
        except Exception as e:
            print(f"{ticker}: request failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        if echo and echo.get("Message") == "Success":
            rec["environmental_pollution_violations"] = field(
                {
                    "matched_facility_query_rows": int(echo.get("QueryRows", 0)),
                    "caa_case_rows": int(echo.get("CAARows", 0)),
                    "cwa_case_rows": int(echo.get("CWARows", 0)),
                    "rcra_case_rows": int(echo.get("RCRRows", 0)),
                    "total_penalties_usd": echo.get("TotalPenalties"),
                },
                "EPA ECHO facility search (name-matched, retried)",
                f"https://echodata.epa.gov/echo/echo_rest_services.get_facilities?p_fn={entity_name}",
                "Medium",
                f"Retried 2026-11-10 using the SEC EDGAR legal registrant name ('{entity_name}') -- the original "
                "2026-08-19/20 run used the same method but came up empty, most likely because the EPA ECHO API "
                "was transiently degraded then. Aggregated across all EPA-regulated facilities whose name matches "
                "this name substring; may include unrelated facilities with similar names, and may miss facilities "
                "filed under subsidiary names (see retry_epa_echo_subsidiaries.py for that follow-up pass).")
            filled += 1
            print(f"{ticker}: FILLED ({echo.get('QueryRows')} rows)", flush=True)
        else:
            still_missing += 1
            rec["environmental_pollution_violations"] = none_field(
                f"No EPA ECHO facilities matched by SEC legal registrant name ('{entity_name}'); retried 2026-11-10, "
                "still no match -- candidate for subsidiary-name retry.")

        if (processed % CHECKPOINT_EVERY) == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{processed}/{len(candidates)}] checkpoint saved | filled={filled} still_missing={still_missing}", flush=True)

    save_json(DATA_PATH, dataset)
    print(f"Done. {filled} filled, {still_missing} still missing (of {processed} processed, {len(candidates)} candidates).", flush=True)


if __name__ == "__main__":
    main()
