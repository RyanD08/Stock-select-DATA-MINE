#!/usr/bin/env python3
"""Step 2 of the coverage-update task: distinguish "no regulated facilities
exist for this kind of business" from "a facility search failed to find a
real match" for environmental_pollution_violations (EPA ECHO) and
worker_safety_record (OSHA), which are both facility-presence-dependent.

Only touches records that are ALREADY confidence="None" (a genuine search
miss) -- never touches a record that already has real Medium/Low-confidence
data, even if that data came from a borderline name-match (e.g. JPMorgan's
single OSHA establishment hit). Reclassification changes `value` to the
literal "No applicable facility records" (confidence stays "None" -- this
is still "no real data", just distinguishing WHY, per the task's own
instruction to mark this "distinct from 'No verifiable data found'" without
changing the schema/confidence vocabulary).

Scope, verified against this dataset's actual SIC codes (not just the GICS
sector label, since a sector label alone could mask an outlier with real
physical operations):
  - Financials: every SIC code actually present among this dataset's 76
    Financials companies is pure banking/insurance/brokerage/investment-
    advice/financial-business-services (banks 60xx, brokers 62xx, insurance
    63xx/64xx, investment offices, fintech/ratings/payments business
    services 7320/7370-7389) -- none implies a manufacturing plant or other
    OSHA/EPA-regulated industrial site.
  - Communication Services: narrower -- only the sub-industries that are
    genuinely office/software-based (computer services 7370-7379,
    advertising agencies 7311). Deliberately EXCLUDES telecom (48xx, real
    physical plant/linemen), broadcasting/cable (48xx, transmission
    infrastructure), publishing (27xx, some operators still run physical
    printing plants), and amusement/recreation (79xx, physical venues) --
    all of which can have real OSHA/EPA exposure and should stay genuine
    gaps, not be waved off.
  - Real Estate: deliberately NOT reclassified. The actual coverage data
    doesn't support the "few regulated facilities" premise for this sector
    (73%/40% coverage, mid-pack, not a standout low) -- REITs by definition
    own/operate physical property and can have real OSHA/EPA exposure. See
    the coverage report for this finding."""
import sys

sys.path.insert(0, ".")
from lib import get_submissions, save_json  # noqa: E402
import json

DATA_PATH = "../data/sp500_full_dataset.json"

FINANCIALS_FACILITY_LIGHT_SIC_PREFIXES = ("60", "61", "62", "63", "64", "67", "73")
COMM_SERVICES_FACILITY_LIGHT_SICS = {"7370", "7371", "7372", "7373", "7374", "7375", "7379", "7311"}


def is_facility_light(sector, sic):
    if not sic:
        return False
    sic = str(sic)
    if sector == "Financials":
        return sic[:2] in FINANCIALS_FACILITY_LIGHT_SIC_PREFIXES
    if sector == "Communication Services":
        return sic in COMM_SERVICES_FACILITY_LIGHT_SICS
    return False


def reclassify(rec, field_key, sic, sic_desc, reg_name):
    f = rec[field_key]
    if f.get("confidence") != "None":
        return False  # already has real data, never touch it
    if f.get("value") == "No applicable facility records":
        return False  # already reclassified, idempotent re-run
    f["value"] = "No applicable facility records"
    f["notes"] = (
        f"SIC {sic} ({sic_desc}) -- a {rec['gics_sector']} company in this line of business has no "
        f"{reg_name}-regulated industrial/physical-hazard facilities to search for in the first place; "
        f"this is a structural non-applicability, not a failed search. (Original search note: {f.get('notes')!r})"
    )
    return True


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    env_reclassified = 0
    work_reclassified = 0
    for rec in dataset:
        sector = rec.get("gics_sector")
        if sector not in ("Financials", "Communication Services"):
            continue
        try:
            subs = get_submissions(rec["cik"])
        except Exception as e:
            print(f"{rec['ticker']}: SIC lookup failed ({e}), skipping", flush=True)
            continue
        sic = subs.get("sic")
        sic_desc = subs.get("sicDescription")
        if not is_facility_light(sector, sic):
            continue
        if reclassify(rec, "environmental_pollution_violations", sic, sic_desc, "EPA ECHO"):
            env_reclassified += 1
        if reclassify(rec, "worker_safety_record", sic, sic_desc, "OSHA"):
            work_reclassified += 1

    save_json(DATA_PATH, dataset)
    print(f"Done. {env_reclassified} environmental_pollution_violations and "
          f"{work_reclassified} worker_safety_record fields reclassified to "
          f"'No applicable facility records'.", flush=True)


if __name__ == "__main__":
    main()
