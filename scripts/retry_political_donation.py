#!/usr/bin/env python3
"""Step 3.6 (political donations/data privacy/countries-of-concern gaps):
retry political_donation_transparency for every company currently
confidence=None. process_batch.py's original proxy-text fallback
(r"political (contribut|spending|donation)") only matches a company that uses
one of those three exact nouns -- investigating the 180 gaps found a broader,
still-precise set of real disclosure phrasings it misses entirely: a named
"[Company] Political Action Committee" (spelled out, never the bare
abbreviation "PAC" -- which produced one real false positive, "PHM": Putnam
Advisory Company LLC, abbreviated "PAC" in an unrelated section), a
"Corporate Political Activities Policy" heading, "trade association and
political activities" language, and an explicit negative disclosure
("Grainger does not maintain a political action committee" -- a real,
sourced fact that should count as Disclosed just as a positive one would,
since this field measures disclosure, not any particular giving level).

Tested against the 13 companies in this set with ANY broader political-
related mention: 11 real hits, 2 correctly excluded (PHM's unrelated "PAC"
abbreviation; INTU's quote of a third-party "political bias" characterization,
a different topic from political spending/PAC disclosure).

Only touches records currently confidence=None. Checkpoints every 20, resumable."""
import json
import os
import re
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, match_company_to_fec_pac, field, none_field, save_json, FEC_CYCLE  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20

POLITICAL_PATTERN = re.compile(
    r"political (?:contribut|spending|donation)|"
    r"political action committees?|"
    r"corporate political (?:and lobbying )?activit|"
    r"trade association.{0,60}political activit",
    re.IGNORECASE)


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    candidates = [r for r in dataset if r["political_donation_transparency"]["confidence"] == "None"]
    print(f"{len(dataset)} companies loaded; {len(candidates)} political_donation_transparency gaps to retry.", flush=True)

    fec_hits = 0
    text_hits = 0
    still_none = 0
    processed = 0
    for i, rec in enumerate(candidates):
        ticker = rec["ticker"]
        cik = rec["cik"]
        name = rec["company_name"]

        try:
            fec_match = match_company_to_fec_pac(name)
        except Exception:
            fec_match = None
        if fec_match:
            total_receipts = sum(float(s["TTL_RECEIPTS"]) for _, _, _, s in fec_match if s and s.get("TTL_RECEIPTS"))
            total_disb = sum(float(s["TTL_DISB"]) for _, _, _, s in fec_match if s and s.get("TTL_DISB"))
            cmte_names = "; ".join(cmte_nm for _, cmte_nm, _, _ in fec_match)
            rec["political_donation_transparency"] = field(
                "Disclosed", f"FEC committee master + committee summary bulk data, {FEC_CYCLE} election cycle",
                f"https://www.fec.gov/data/committee/{fec_match[0][0]}/?cycle={FEC_CYCLE}", "High",
                f"Matched to registered corporate PAC(s): {cmte_names}. Cycle totals: ${total_receipts:,.2f} receipts / "
                f"${total_disb:,.2f} disbursements. Matched by company name against FEC's CONNECTED_ORG_NM/committee-name "
                "fields (FEC does not publish a CIK crosswalk) -- verify the matched committee is this company, not a "
                "similarly-named one. (Retried 2026-11-10.)")
            fec_hits += 1
            processed += 1
            print(f"{ticker}: FEC match", flush=True)
            continue

        try:
            subs = get_submissions(cik)
            proxy = latest_filing(subs, "DEF 14A")
            if not proxy:
                rec["political_donation_transparency"] = none_field("No DEF 14A found/fetchable on EDGAR")
                processed += 1
                continue
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            text = fetch_filing_text(purl)
        except Exception as e:
            print(f"{ticker}: fetch failed ({e}), leaving for next retry", flush=True)
            continue

        processed += 1
        m = POLITICAL_PATTERN.search(text)
        if m:
            rec["political_donation_transparency"] = field(
                "Disclosed", f"DEF 14A political spending disclosure, filed {proxy['filing_date']}", purl, "Medium",
                f"Matched broader political-activity disclosure language: \"{m.group(0)}\". Retried 2026-11-10 with "
                "an expanded pattern (named political action committees, corporate political-activity policies, "
                "trade-association political spending, and explicit negative disclosures) beyond the original "
                "narrow 'political contribut/spending/donation' phrase match.")
            text_hits += 1
            print(f"{ticker}: text match ({m.group(0)!r})", flush=True)
        else:
            still_none += 1
            rec["political_donation_transparency"] = none_field(
                "No FEC-registered corporate PAC name-matched and no political-spending/PAC/lobbying disclosure "
                "language found in proxy text scan (retried 2026-11-10 with an expanded pattern); opensecrets.org "
                "blocked by Cloudflare, cii.org unavailable in this environment")

        if (processed % CHECKPOINT_EVERY) == 0:
            save_json(DATA_PATH, dataset)
            print(f"[{processed}/{len(candidates)}] checkpoint saved | fec={fec_hits} text={text_hits} still_none={still_none}", flush=True)

    save_json(DATA_PATH, dataset)
    print(f"Done. fec={fec_hits} text={text_hits} still_none={still_none} (of {processed} processed, {len(candidates)} candidates).", flush=True)


if __name__ == "__main__":
    main()
