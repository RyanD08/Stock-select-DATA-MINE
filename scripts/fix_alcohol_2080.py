#!/usr/bin/env python3
"""One-off corrector: for every already-processed company whose registrant
SIC is the generic 2080 ('Beverages') code, disambiguate alcohol_involvement
via a 10-K business-description keyword scan instead of the old blanket
True (which incorrectly flagged Coca-Cola, PepsiCo, and Keurig Dr Pepper as
alcohol producers)."""
import json
import re
import sys

sys.path.insert(0, ".")
from lib import get_submissions, latest_filing, filing_document_url, fetch_filing_text, alcohol_2080_hit, field, none_field  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"
SIC_RE = re.compile(r"Registrant SIC code (\d+)")


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    targets = []
    for rec in dataset:
        notes = rec.get("tobacco_involvement", {}).get("notes") or ""
        m = SIC_RE.search(notes)
        if m and m.group(1).zfill(4) == "2080":
            targets.append(rec)
    print(f"Found {len(targets)} companies with SIC 2080: {[r['ticker'] for r in targets]}")

    for rec in targets:
        cik = rec["cik"]
        try:
            sub = get_submissions(cik)
            tenk = latest_filing(sub, "10-K")
            if not tenk:
                rec["alcohol_involvement"] = none_field("SIC 2080 is generic and no 10-K on file to disambiguate.")
                continue
            url = filing_document_url(cik, tenk["accession"], tenk["primary_doc"])
            txt = fetch_filing_text(url)
            hit = alcohol_2080_hit(txt.lower())
            sic_note = rec["tobacco_involvement"]["notes"]
            rec["alcohol_involvement"] = field(
                hit, "SEC EDGAR registrant SIC code (2080, generic) + 10-K business description keyword scan",
                url, "Medium",
                f"{sic_note} SIC 2080 ('Beverages') does not by itself distinguish alcohol producers from soft-drink makers, so this was disambiguated by scanning the 10-K business description for alcohol-specific terms (wine/beer/spirits/etc.).")
            print(f"{rec['ticker']}: alcohol_involvement -> {hit}")
        except Exception as e:
            print(f"{rec['ticker']}: failed ({e}), leaving as-is")

    with open(DATA_PATH, "w") as f:
        json.dump(dataset, f, indent=2)
    print("Done.")


if __name__ == "__main__":
    main()
