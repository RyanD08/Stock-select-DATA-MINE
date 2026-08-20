# Manual Review Needed

This file logs companies or systemic issues that need human follow-up rather than
a forced/guessed answer.
## Background document vs. founding prompt: conflicts found
The founding prompt (`claude_code_new_repo_founding_prompt.md`) lists 27 survey
questions and gives Q17 as "no verifiable per-company religious compliance data
source available." The `TrueNorth_Background_Info.pdf` (authoritative per its own
text) confirms the same 27-question list and numbering, and additionally notes:
- An original 28th question (avoiding animal testing) was **permanently removed**
  from the survey. It is not present in either source's active question list, so
  no field is being built for it. No conflict, just confirming exclusion.
- Q18/Q19 numbering in the background doc matches "Religious/Values-Based" =
  18 (religious compliance) and 19 (interest-based products), consistent with
  the founding prompt's Q17/Q18 content description (the prompt's step-3 section
  labels these "Q17-18" using a slightly different running count than the
  background doc's absolute 1-27 numbering, since the founding prompt's own
  internal section counters drift after combining Q9-11 as "Q8-11" etc.). This is
  a numbering/formatting difference only, not a content conflict -- the
  `schema/company_schema.json` data dictionary uses the background doc's
  authoritative 1-27 numbering and descriptive field names (not "Qn") as the
  source of truth to avoid ambiguity.
- Background doc section 4 (scoring/portfolio logic), section 5 (What-If
  simulation), and sections 6-10 (disclaimers, tech setup, brand, key
  principles) are all **app/website repo concerns**, not dataset-repo concerns.
  They are recorded here for context only since this repo does not build the
  website. No action needed in this repo beyond keeping the dataset schema
  compatible with them (e.g. keeping growth_potential/stability unblended,
  flagging recent corporate actions) -- which `company_schema.json` already does.
No unresolved conflicts requiring a data decision were found between the two
source documents.
## Approved sources that are unreachable from this environment
Tested 2026-08-19 with a descriptive `TrueNorth-DataMine/1.0 (research@...)`
User-Agent (per SEC guidance) and, for the sites that still 403'd, a standard
browser User-Agent as a second attempt:
| Source | Status | Detail |
|---|---|---|
| `violationtracker.goodjobsfirst.org` | **Blocked** | Cloudflare JS challenge ("Just a moment...") on every request; not a proxy-policy denial, the origin itself returns the challenge page to this environment's egress IP regardless of headers. |
| `securities.stanford.edu` | **Blocked** | Same Cloudflare JS challenge behavior as above. |
| `www.bcorporation.net` | **Blocked** | Returns 403 with a bot-protection page; same class of issue. |
| `api.gunfreefunds.org` | **Blocked (proxy policy)** | The environment's outbound proxy returns "gateway answered 502 to CONNECT (policy denial or upstream failure)" specifically for this subdomain. |
| `www.gunfreefunds.org` (with `www.`) | **Blocked (proxy policy)** | Same CONNECT-tunnel 403 as above; the bare domain `gunfreefunds.org` (no `www.`) **does** work (HTTP 200), so that's used instead. |
| `cii.org` | Reachable but only returns a redirect (301) in quick testing; needs a follow-up fetch with `-L` to confirm real content access. |
**Consequence for scoring:** Q11 (fraud/corruption/scandal history) and Q20
(political donation transparency) lose their two richest intended sources
(Violation Tracker's parent-company rollups, and cii.org's political-spending
context) and Q16 (weapons/defense) loses the Gun Free Funds API's structured
exposure data. These questions are **not** left blank -- they fall back to the
other approved sources already listed in the schema (SEC Litigation Releases
full-text search via `efts.sec.gov` for Q11; DEF 14A political-spending
disclosures for Q20; SIC codes 3480-3489/3760-3769 plus the `gunfreefunds.org`
bare-domain HTML pages for Q16) -- but coverage and depth will be lower than if
the blocked sources were reachable. Flagging so a human can decide whether to
retry from a different network/IP, or accept the SIC-code/EDGAR-only fallback
as final.
## Finnhub free tier requires an API key not available in this environment
`finnhub.io` is network-reachable (HTTP 401 "Please use an API key" on an
unauthenticated request), but the founding materials do not include a Finnhub
API key, and this agent has no way to self-register for one. Q26/27 (Growth
Potential / Stability derived profile) financial inputs that were meant to come
from Finnhub (market cap, beta, dividend yield) will instead be sourced from
SEC EDGAR company-facts XBRL data and Alpha Vantage's free tier (which works
with the public `demo` key for limited symbols, but a real free-tier key would
give full coverage). **Action needed:** if the user has or can obtain a free
Finnhub API key, provide it (e.g. as an environment variable `FINNHUB_API_KEY`)
so future sessions can use it for richer coverage.
## Alpha Vantage free tier also requires a self-registered API key
Confirmed 2026-08-19: Alpha Vantage's public `demo` key only serves a small set
of fixed demo symbols/functions -- calling `OVERVIEW` or
`TIME_SERIES_MONTHLY_ADJUSTED` for a real ticker (tested with AAPL) returns
`{"Information": "The demo API key is for demo purposes only. Please claim
your free API key..."}` rather than data. Getting a working key requires
submitting an email address on alphavantage.co's signup form, which this
agent should not do on the user's behalf. **Net effect: with neither a
Finnhub nor an Alpha Vantage key available, and Stooq blocked (see below),
there is currently no working free source of historical price data**, so the
five-year-total-return component of Q26/27's Growth Potential tier cannot be
populated (confidence None) until a key is supplied. Revenue growth (also
part of Growth Potential) and debt-to-equity/dividend-consistency (Stability)
*can* still be derived from SEC EDGAR XBRL company facts and are not blocked.
**Action needed:** if the user can register a free Finnhub or Alpha Vantage
API key (both take under a minute per their own docs) and supply it as an
environment variable (`FINNHUB_API_KEY` / `ALPHAVANTAGE_API_KEY`), a future
session can immediately fill in the price-return and beta/volatility data for
all companies.
## Stooq.com is behind a JavaScript proof-of-work challenge
`stooq.com` (on the approved list, no-API-key historical price source) returns
a client-side proof-of-work challenge page to this environment instead of CSV
data, for both the HTML and `/q/d/l/` CSV-download endpoints. This is not
solvable by a headless HTTP client. Historical price data for the
Growth Potential / 5-year-return field is being sourced from Alpha Vantage's
free tier instead. Flagging in case a different egress IP/environment resolves
this.
---
*(Per-company sourcing difficulty entries -- foreign private issuers, recent
IPOs, name/ticker changes -- will be appended below as batches are processed.)*
- **XOM** (2026-08-19): CIK 0002115436 ('ExxonMobil Holdings Corp') has no 10-K or DEF 14A filing history on EDGAR -- likely a recent holding-company reorganization/successor-registrant event (check for a predecessor CIK). Filing types on record: ['10-Q', '8-K', '8-K12B', 'POSASR', 'S-8 POS'].
