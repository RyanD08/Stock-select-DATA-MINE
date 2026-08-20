# Suggested Additional Sources

Sources identified during research that are **not** on the approved list and
were **not** accessed. Logged here for manual review/approval before any
future session is allowed to use them.

*(None yet accessed or fetched -- entries below are proposals only.)*

## SEC EDGAR XBRL Frames API for a possible NLRB alternative

Not actually a new domain, but noting: the founding materials list
`www.nlrb.gov` as the approved source for labor-dispute history (Q6), but
NLRB's public case-search UI is a JavaScript-rendered Drupal widget with no
discoverable server-rendered results or public JSON/REST endpoint reachable
by a plain HTTP client from this environment (confirmed 2026-08-19 -- see
`logs/manual_review_needed.md`). If NLRB does publish a bulk case-data
download (CSV/XML) at a stable URL under `www.nlrb.gov` itself, that would
still be in-scope (same domain) and worth a follow-up session investigating
`nlrb.gov`'s "Reports & Guidance" / open-data pages specifically for a
downloadable dataset rather than the search widget.

## data.dol.gov for worker safety / enforcement data (Q8) -- new domain to request

`enforcedata.dol.gov` was added to the allowlist 2026-08-20 but is not directly
usable: it 301-redirects to `data.dol.gov`, a *different* subdomain, which was
not itself added -- the proxy denies it. `data.dol.gov` is DOL's actual public
enforcement-data portal (OSHA, WHD, MSHA case-level data), which would meaningfully
supplement/replace the current OSHA establishment-search scrape for Q8 (currently
36.8% coverage). Suggesting `data.dol.gov` specifically be added to the allowlist
for a future session to investigate its bulk-download/API structure.

## data.sec.gov XBRL Frames for country-of-operations (already approved, just unimplemented)

Not a new source -- `data.sec.gov` is already approved and used elsewhere in
this pipeline. Flagging here only as a to-do: the XBRL Frames API
(`data.sec.gov/api/xbrl/frames/...`) can pull geographic-segment revenue
tags (e.g. `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` with
an `srt:StatementGeographicalAxis` dimension) across all filers for a given
period, which would give real per-company country-of-operations data for Q21
instead of the current `None` placeholder. Left unimplemented in this session
for time; a good first task for the next batch-processing session.
