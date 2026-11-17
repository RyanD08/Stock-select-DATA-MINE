#!/usr/bin/env python3
"""Rebuild the industry ("sin stock") screens and the headquarters country
from the official GICS sub-industry plus two documented reference lists.

Why: the original screens used only each registrant's SEC SIC code, which
files most of the industry under codes the screens didn't include --
casino operators under "hotels and motels", most defense contractors under
"aircraft" or "search and navigation equipment", investment banks and
brokers under "security brokers and dealers". Las Vegas Sands, Wynn, MGM,
Northrop Grumman, General Dynamics, RTX, Goldman Sachs and Morgan Stanley
were all marked "not involved" with High confidence. Separately, the
website's headquarters field defaulted to "United States" for every
company.

Rules (decided by the project owner, 2026-11-17):
  tobacco_involvement      GICS sub-industry "Tobacco" (or a tobacco SIC code).
  alcohol_involvement      Producers only: GICS "Brewers" or "Distillers &
                           Vintners". Companies with alcohol partnerships or
                           distribution deals (e.g. PepsiCo, Keurig Dr Pepper)
                           are not flagged.
  gambling_casino_...      GICS "Casinos & Gaming" (or SIC 7993).
  weapons_defense_...      On the SIPRI Top 100 arms producers list
                           (data/reference/sipri_top100_2024.json) OR weapons
                           is the primary business by SEC SIC code (ordnance,
                           guided missiles, tanks -- e.g. Lockheed, Axon).
  interest_based_...       Lenders and brokers: GICS "Diversified Banks",
                           "Regional Banks", "Consumer Finance" or "Investment
                           Banking & Brokerage", OR an SEC lending/banking SIC
                           code (keeps custody banks such as BNY and State
                           Street, which are chartered banks). Insurers,
                           payment networks and asset managers are not flagged.
  hq_country / domestic_hq Where the company is actually run from; see the
                           rule in data/reference/hq_country_overrides.json.

The SIC code is re-read from each field's existing notes ("SIC code NNNN"),
and this script writes it back into the new notes, so re-running it is safe.

Usage: python3 scripts/fix_industry_screens.py [--dry-run]
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import ALCOHOL_SIC, FINANCE_LENDING_SIC, GAMBLING_SIC, TOBACCO_SIC, WEAPONS_SIC  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(ROOT, "data", "sp500_full_dataset.json")
SIPRI = os.path.join(ROOT, "data", "reference", "sipri_top100_2024.json")
HQ = os.path.join(ROOT, "data", "reference", "hq_country_overrides.json")
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

GICS = {
    "tobacco": {"Tobacco"},
    "alcohol": {"Brewers", "Distillers & Vintners"},
    "gambling": {"Casinos & Gaming"},
    "interest": {"Diversified Banks", "Regional Banks", "Consumer Finance", "Investment Banking & Brokerage"},
}
US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
    "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
    "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas",
    "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "D.C.",
    "District of Columbia",
}


def sic_of(record):
    for key in ("tobacco_involvement", "alcohol_involvement", "gambling_casino_involvement",
                "weapons_defense_involvement", "interest_based_financial_products"):
        field = record.get(key)
        notes = field.get("notes") if isinstance(field, dict) else None
        match = re.search(r"SIC code (\d{4})", notes or "")
        if match:
            return match.group(1)
    return None


def screen_field(value, source, source_url, notes, today):
    return {"value": value, "source": source, "source_url": source_url, "confidence": "High",
            "notes": notes, "last_updated": today}


def wiki_country(location):
    if not location or location.strip().lower() == "none":
        return None
    last = re.sub(r"\[\d+\]", "", location.split(",")[-1]).strip()
    return "United States" if last in US_STATES else last


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    today = datetime.date.today().isoformat()

    with open(DATASET) as f:
        records = json.load(f)
    with open(SIPRI) as f:
        sipri = json.load(f)
    with open(HQ) as f:
        hq = json.load(f)
    sipri_by_ticker = {c["ticker"]: c for c in sipri["companies"]}
    tickers = {r["ticker"] for r in records}
    missing = [t for t in list(sipri_by_ticker) + list(hq["companies"]) if t not in tickers]
    if missing:
        sys.exit(f"Reference lists name tickers not in the dataset: {missing}")

    changes = {k: [] for k in ("tobacco", "alcohol", "gambling", "weapons", "interest", "hq")}
    for r in records:
        sub = r.get("gics_sub_industry")
        sic = sic_of(r)
        sic_text = f"SEC SIC code {sic}" if sic else "no SEC SIC code on file"
        gics_text = f"GICS sub-industry '{sub}'"

        def apply(key, label, value, source, source_url, why):
            old = (r.get(key) or {}).get("value") if isinstance(r.get(key), dict) else r.get(key)
            notes = f"{why} Checked: {gics_text}; {sic_text}."
            r[key] = screen_field(value, source, source_url, notes, today)
            if old is not value:
                changes[label].append((r["ticker"], old, value))

        gics_src = "GICS sub-industry (Wikipedia S&P 500 constituents table) + SEC EDGAR registrant SIC code"
        sec_url = f"https://data.sec.gov/submissions/CIK{r['cik']}.json" if r.get("cik") else WIKI_URL

        tob = sub in GICS["tobacco"] or sic in TOBACCO_SIC
        apply("tobacco_involvement", "tobacco", tob, gics_src, WIKI_URL,
              "Flagged when the company's official industry is Tobacco." if tob else "Industry is not tobacco.")

        alc = sub in GICS["alcohol"]
        apply("alcohol_involvement", "alcohol", alc, gics_src, WIKI_URL,
              "Producers only: flagged when the official industry is Brewers or Distillers & Vintners."
              if alc else "Not an alcohol producer by official industry (partnerships and distribution are not counted).")

        gam = sub in GICS["gambling"] or sic in GAMBLING_SIC
        apply("gambling_casino_involvement", "gambling", gam, gics_src, WIKI_URL,
              "Flagged when the official industry is Casinos & Gaming." if gam else "Industry is not casinos or gaming.")

        s = sipri_by_ticker.get(r["ticker"])
        primary = sic in WEAPONS_SIC
        weap = bool(s) or primary
        if s:
            why = (f"On the SIPRI Top 100 arms producers list for 2024 (rank {s['sipri_rank']}, arms revenue "
                   f"${s['arms_revenue_usd_m']:,}m, {s['arms_share_of_revenue_pct']}% of total revenue).")
            source, url = "SIPRI Top 100 arms-producing and military services companies, 2024", sipri["source_url"]
        elif primary:
            why = "Weapons is the primary business by SEC industry code (ordnance, guided missiles or tanks)."
            source, url = "SEC EDGAR registrant SIC code", sec_url
        else:
            why = "Not on the SIPRI Top 100 arms producers list, and weapons is not the primary business by SEC industry code."
            source, url = "SIPRI Top 100 (2024) + SEC EDGAR registrant SIC code", sipri["source_url"]
        apply("weapons_defense_involvement", "weapons", weap, source, url, why)

        lend_gics = sub in GICS["interest"]
        lend_sic = sic in FINANCE_LENDING_SIC
        intr = lend_gics or lend_sic
        apply("interest_based_financial_products", "interest", intr, gics_src, WIKI_URL,
              "Lender or broker: flagged by official industry (banks, consumer finance, investment banking & brokerage)"
              " or an SEC banking/lending industry code." if intr
              else "Not a lender or broker by official industry or SEC industry code.")

        override = hq["companies"].get(r["ticker"])
        country = override["country"] if override else wiki_country(r.get("headquarters_location"))
        old_country = r.get("hq_country")
        r["hq_country"] = country
        domestic_old = (r.get("domestic_hq") or {}).get("value") if isinstance(r.get("domestic_hq"), dict) else None
        r["domestic_hq"] = {
            "value": country == "United States" if country else None,
            "source": "Company annual report / SEC registration" if override else "Wikipedia S&P 500 constituents table (Headquarters Location column)",
            "source_url": override["source_url"] if override else WIKI_URL,
            "confidence": "High" if country else "None",
            "notes": (override["evidence"] if override else None),
            "last_updated": today,
        }
        if domestic_old is not r["domestic_hq"]["value"] or (old_country and old_country != country):
            changes["hq"].append((r["ticker"], f"domestic={domestic_old}", f"{country} (domestic={r['domestic_hq']['value']})"))

    for label, rows in changes.items():
        print(f"{label}: {len(rows)} changed")
        for ticker, old, new in rows[:40]:
            print(f"  {ticker:6s} {old} -> {new}")
    if args.dry_run:
        print("Dry run: nothing written.")
        return
    with open(DATASET, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Wrote {DATASET}")


if __name__ == "__main__":
    main()
