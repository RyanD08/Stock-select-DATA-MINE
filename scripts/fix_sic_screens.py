#!/usr/bin/env python3
"""One-off corrector: reapply the (now-fixed) SIC-code sin-stock screens to
every company using the SIC code already recorded in each field's notes text
(re-fetching submissions.json would work too, but parsing the already-stored
SIC is cheaper and avoids ~500 more EDGAR calls for a pure re-derivation)."""
import json
import re
import sys

sys.path.insert(0, ".")
from lib import sic_screen, field, TODAY  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"

SIC_RE = re.compile(r"Registrant SIC code (\d+)")


def main():
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    changed = 0
    for rec in dataset:
        notes = rec.get("tobacco_involvement", {}).get("notes") or ""
        m = SIC_RE.search(notes)
        if not m:
            continue
        sic = m.group(1)
        screens = sic_screen(sic)
        sub_url = rec["tobacco_involvement"].get("source_url")
        sic_note = rec["tobacco_involvement"].get("notes")
        old_gambling = rec["gambling_casino_involvement"]["value"]
        rec["gambling_casino_involvement"] = field(screens["gambling"], "SEC EDGAR registrant SIC code", sub_url, "High", sic_note)
        if old_gambling != screens["gambling"]:
            changed += 1
            print(f"{rec['ticker']}: gambling {old_gambling} -> {screens['gambling']}")

    with open(DATA_PATH, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"Done. {changed} companies' gambling_casino_involvement corrected.")


if __name__ == "__main__":
    main()
