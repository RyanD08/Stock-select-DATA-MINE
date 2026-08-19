#!/usr/bin/env python3
"""Fetch the current S&P 500 constituent list from Wikipedia and build the
skeleton dataset (ticker + name + sector + sub-industry + HQ populated, all
scored fields pending). Approved source: en.wikipedia.org only."""
import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UA = "TrueNorth-DataMine/1.0 (research@truenorth.example; contact ryan.delp08@gmail.com)"
OUT_PATH = "data/sp500_full_dataset.json"


def none_field():
    return {
        "value": "No verifiable data found",
        "source": None,
        "source_url": None,
        "confidence": "None",
        "notes": None,
        "last_updated": None,
    }


def pending_field():
    return {
        "value": None,
        "source": None,
        "source_url": None,
        "confidence": None,
        "notes": None,
        "last_updated": None,
    }


SCORED_FIELDS = [
    "carbon_fossil_fuel_involvement",
    "renewable_clean_tech_involvement",
    "environmental_pollution_violations",
    "sustainable_agriculture_resource_use",
    "fair_wages_labor_practices",
    "labor_disputes_exploitation_history",
    "workplace_diversity_equity_inclusion",
    "worker_safety_record",
    "board_transparency_independence",
    "ceo_pay_ratio",
    "fraud_corruption_scandal_history",
    "shareholder_rights_voting_structure",
    "tobacco_involvement",
    "alcohol_involvement",
    "gambling_casino_involvement",
    "weapons_defense_involvement",
    "adult_entertainment_involvement",
    "religious_investment_compliance",
    "interest_based_financial_products",
    "political_donation_transparency",
    "countries_of_concern_operations",
    "data_privacy_practices",
    "domestic_hq",
    "founder_led",
    "family_owned",
    "growth_potential",
    "stability",
]


def fetch_table():
    resp = requests.get(WIKI_URL, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table", {"id": "constituents"})
    if table is None:
        raise RuntimeError("Could not find constituents table on Wikipedia page")
    rows = table.find_all("tr")
    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    companies = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 7:
            continue
        vals = [c.get_text(strip=True) for c in cells]
        row = dict(zip(header_cells, vals))
        companies.append(row)
    return companies, resp.url


def build_skeleton(companies, source_url):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dataset = []
    for row in companies:
        ticker = row.get("Symbol", "").strip().replace(".", "-")
        name = row.get("Security", "").strip()
        sector = row.get("GICS Sector", "").strip()
        sub_industry = row.get("GICS Sub-Industry", "").strip()
        hq = row.get("Headquarters Location", "").strip()
        date_added = row.get("Date added", "").strip() or None
        cik_raw = row.get("CIK", "").strip()
        cik = cik_raw.zfill(10) if cik_raw.isdigit() else None
        founded = row.get("Founded", "").strip() or None

        record = {
            "ticker": ticker,
            "company_name": name,
            "gics_sector": sector,
            "gics_sub_industry": sub_industry,
            "headquarters_location": hq,
            "cik": cik,
            "date_added_to_sp500": date_added,
            "founded_year": founded,
            "recent_corporate_action_flag": {
                "value": False,
                "notes": None,
            },
            "processing_status": "pending",
            "_wikipedia_source_url": source_url,
            "_wikipedia_fetch_date": now,
        }
        for f in SCORED_FIELDS:
            record[f] = pending_field()
        dataset.append(record)
    return dataset


def main():
    companies, source_url = fetch_table()
    if len(companies) < 490:
        print(f"WARNING: only parsed {len(companies)} rows, expected ~500", file=sys.stderr)
    dataset = build_skeleton(companies, source_url)
    with open(OUT_PATH, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"Wrote {len(dataset)} companies to {OUT_PATH}")


if __name__ == "__main__":
    main()
