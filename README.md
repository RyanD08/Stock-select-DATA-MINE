# Stock-select-DATA-MINE

Dataset-only repository for **TrueNorth**, a values-guided investing tool. This
repo's sole purpose is producing `data/sp500_full_dataset.json`: a sourced,
confidence-rated dataset covering every current S&P 500 constituent, answering
the 27 client survey questions used by the TrueNorth app
(github.com/RyanD08/Stockselect). It does **not** contain the website/app --
it is kept independent so long-running research batches can't affect the live
site, and so the dataset can be versioned and swapped independently.

## What's here

```
/schema/company_schema.json        Data dictionary: every field, its survey
                                    question mapping, value type, and sources.
/data/sp500_full_dataset.json      The dataset. One record per company.
/data/candidate_additional_criteria.json
                                    Well-documented data points found during
                                    research that aren't part of the official
                                    27 questions -- logged for review, not
                                    auto-added to the survey.
/scripts/                          The collection pipeline (Python).
/logs/progress.json                Checkpoint tracker: which tickers are
                                    complete / pending / need manual review.
/logs/manual_review_needed.md      Companies or systemic issues that needed
                                    a human decision instead of a forced answer.
/logs/suggested_sources.md         Non-approved sources spotted during
                                    research, not accessed, flagged for
                                    review before future use.
```

## Data model

Every scored field on a company record is an object:

```json
{
  "value": "...",
  "source": "SEC 10-K Item 1 Business description, filed 2026-...",
  "source_url": "https://www.sec.gov/Archives/edgar/data/...",
  "confidence": "High | Medium | Low | None",
  "notes": "optional caveats / interpretation notes",
  "last_updated": "YYYY-MM-DD"
}
```

`confidence: "None"` with `value: "No verifiable data found"` is used whenever
no approved source could answer a field -- this is intentional and preferred
over a fabricated placeholder. Confidence levels are for internal/app use;
per the TrueNorth background document they are not shown directly to survey
respondents.

See `schema/company_schema.json` for the full field-by-field data dictionary
mapping each of the 27 survey questions to its dataset field(s) and sources.

## Running the pipeline

```bash
pip install requests beautifulsoup4 lxml
cd scripts

# Pull the current S&P 500 constituent list from Wikipedia and (re)build the
# skeleton dataset. Safe to re-run; it does not touch already-populated
# scored fields for existing tickers beyond what a fresh Wikipedia pull adds.
python3 fetch_sp500_list.py

# Process the next N pending companies (checkpoints every 5 companies):
python3 process_batch.py --count 50

# Or force-(re)process specific tickers:
python3 process_batch.py --tickers AAPL,MSFT,XOM
```

Each run updates `data/sp500_full_dataset.json` and `logs/progress.json` in
place, and appends to `logs/manual_review_needed.md` for anything that needed
a human decision. A new session can resume immediately by re-running
`process_batch.py --count N` with no arguments beyond `--count` -- it
auto-selects the next `processing_status: "pending"` companies.

## Sources actually used

Per the approved source list (see founding prompt / background doc), with
what actually worked from this environment as of 2026-08-19:

| Source | Status | Used for |
|---|---|---|
| en.wikipedia.org | Working | Company list, sector, HQ, CIK, date added, founding year |
| data.sec.gov / www.sec.gov / efts.sec.gov | Working | SIC code, 10-K/DEF 14A text, XBRL company facts, full-text search |
| echo.epa.gov / echodata.epa.gov | Working | Environmental/pollution violation aggregates (Q3) |
| www.osha.gov | Working | Worker safety establishment records (Q8) |
| www.nlrb.gov | **Blocked** -- JS-rendered search widget, no reachable API | Labor disputes (Q6) left `None` |
| finnhub.io | Reachable, but no API key available | Growth/Stability financial inputs -- see below |
| alphavantage.co | Reachable, but `demo` key doesn't serve real symbols | Growth/Stability financial inputs -- see below |
| stooq.com | **Blocked** -- JS proof-of-work challenge | Historical price data |
| violationtracker.goodjobsfirst.org | **Blocked** -- Cloudflare challenge | Fraud/corruption history (Q11) -- fell back to SEC full-text search |
| securities.stanford.edu | **Blocked** -- Cloudflare challenge | Securities fraud cases (Q11) |
| www.bcorporation.net | **Blocked** -- 403/bot protection | B-Corp discovery (additional criteria) |
| gunfreefunds.org (bare domain) | Working | Weapons/defense exposure context (Q16) |
| api.gunfreefunds.org / www.gunfreefunds.org | **Blocked** -- proxy policy denial | -- |
| fossilfreefunds.org | Working | Fossil-fuel exposure context (Q1) |
| justcapital.com | Working (not yet integrated into the pipeline) | Worker-treatment rankings |
| sciencebasedtargets.org | Working (not yet integrated into the pipeline) | Verified climate commitments (Q1/Q2) |
| www.bls.gov | Working (not yet integrated into the pipeline) | Industry benchmarking context |
| cii.org | Reachable, minimal integration | Political spending context (Q20) |

Full detail, including exactly how each was tested, is in
`logs/manual_review_needed.md`. **Growth Potential / Stability (Q26/27) is
the field most affected**: with Finnhub, Alpha Vantage, and Stooq all
unavailable in this environment, there is currently no working free price-
history source, so 5-year total return and beta/volatility are `None`.
Revenue growth and debt-to-equity/dividend-consistency *are* available from
SEC EDGAR XBRL data and are populated. If a Finnhub or Alpha Vantage API key
becomes available (env vars `FINNHUB_API_KEY` / `ALPHAVANTAGE_API_KEY`), a
future pipeline run can fill in the missing pieces.

## Known pipeline limitations (see logs for detail)

- Sin-stock screens (Q13-17) and interest-based-finance (Q19) use only the
  registrant's top-line SEC SIC code -- a conglomerate with a relevant
  segment under a different primary SIC would be missed.
- Environmental/labor qualitative fields (Q1, Q2, Q4, Q5, Q7) are keyword
  scans of 10-K text, not verified emissions/labor figures -- confidence is
  capped at Medium/Low accordingly. Science Based Targets integration for a
  stronger Q1/Q2 signal is reachable but not yet wired into the pipeline.
  EPA ECHO / OSHA name-matching (Q3, Q8) can pick up unrelated facilities
  that share a word in their name, or miss facilities filed under a
  subsidiary's name.
- CEO pay ratio / board independence / founder-family ownership (Q9, Q10,
  Q24) are regex text scans of the latest DEF 14A -- real, sourced hits when
  found, but recall is imperfect; a `None` here often just means the
  disclosure used unanticipated phrasing, not that no disclosure exists.
- Country-of-operations (Q21) and SEC-Litigation-Release-based data privacy
  enforcement (Q22) are stubbed to `None` -- flagged in
  `logs/suggested_sources.md` as good next tasks (the XBRL Frames API is
  already-approved and reachable, just not yet implemented).
- Companies whose current SEC CIK has no 10-K/DEF 14A filing history
  (typically a very recent holding-company reorganization, e.g. an `8-K12B`
  successor-registrant event) are flagged via
  `recent_corporate_action_flag` and logged to manual review rather than
  scored on stale/absent data.
