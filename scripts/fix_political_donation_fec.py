#!/usr/bin/env python3
"""One-off corrector: backfill political_donation_transparency (Q20) across
all already-processed companies using FEC bulk committee data (cm.zip +
committee_summary.csv), newly reachable in this environment. A real,
name-matched FEC-registered corporate PAC with filed financial totals is a
stronger signal than the existing DEF 14A keyword scan, so it's scored High
confidence and takes priority -- but this script only ever upgrades a
record: if no FEC PAC match is found, the existing field (DEF 14A hit or
None) is left untouched rather than being cleared."""
import json
import sys

sys.path.insert(0, ".")
from lib import match_company_to_fec_pac, field, FEC_CYCLE  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    matched = 0
    for rec in dataset:
        name = rec["company_name"]
        try:
            fec_match = match_company_to_fec_pac(name)
        except Exception as e:
            print(f"{rec['ticker']}: FEC lookup failed ({e}), leaving as-is")
            continue
        if not fec_match:
            continue
        total_receipts = sum(float(s["TTL_RECEIPTS"]) for _, _, _, s in fec_match if s and s.get("TTL_RECEIPTS"))
        total_disb = sum(float(s["TTL_DISB"]) for _, _, _, s in fec_match if s and s.get("TTL_DISB"))
        cmte_names = "; ".join(cmte_nm for _, cmte_nm, _, _ in fec_match)
        rec["political_donation_transparency"] = field(
            "Disclosed",
            f"FEC committee master + committee summary bulk data, {FEC_CYCLE} election cycle",
            f"https://www.fec.gov/data/committee/{fec_match[0][0]}/?cycle={FEC_CYCLE}", "High",
            f"Matched to registered corporate PAC(s): {cmte_names}. Cycle totals: ${total_receipts:,.2f} receipts / "
            f"${total_disb:,.2f} disbursements. Matched by company name against FEC's CONNECTED_ORG_NM/committee-name "
            "fields (FEC does not publish a CIK crosswalk) -- verify the matched committee is this company, not a "
            "similarly-named one.")
        matched += 1
        print(f"{rec['ticker']}: political_donation_transparency -> Disclosed (High, FEC) via {cmte_names}")

    with open(DATA_PATH, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"Done. {matched}/{len(dataset)} companies upgraded to High-confidence FEC-sourced data.")


if __name__ == "__main__":
    main()
