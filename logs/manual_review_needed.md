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
## SIC 2080 ("Beverages") does not distinguish alcohol from soft-drink makers

Found and fixed 2026-08-20: SEC EDGAR assigns the generic SIC code 2080
("Beverages") to soft-drink companies (Coca-Cola, PepsiCo, Keurig Dr Pepper)
just as often as to alcohol producers (Constellation Brands, Brown-Forman) --
it is not a reliable signal on its own. The pipeline now disambiguates SIC
2080 registrants with a 10-K business-description keyword scan (wine/beer/
spirits/etc.) at Medium confidence instead of auto-flagging every 2080
registrant as an alcohol producer, which had incorrectly flagged Coca-Cola,
PepsiCo, and Keurig Dr Pepper as True. That keyword scan has its own known
false-positive mode worth flagging: Keurig Dr Pepper's alcohol_involvement
is currently True because its 10-K mentions "beer wholesalers, wine and
spirit distributors" as a category of *third-party distributor it sells
through*, not a description of KDP's own products -- the keyword match
can't currently tell "we distribute via X-type wholesalers" apart from "we
produce X." Left as Medium confidence with the matched text visible in the
field's notes for a human to judge; a similar-scale distribution-channel
false positive is possible (but not confirmed) at other SIC-2080 companies.

## Similarly, SIC 7990 ("Amusement & Recreation, NEC") does not mean gambling

Found and fixed 2026-08-20: SIC 7990 is Disney's own registrant code (theme
parks), not a gambling-specific classification -- it had been included in
the gambling/casino SIC set and incorrectly flagged Disney as a casino
company. Removed; only SIC 7993 (Coin-Operated Amusement Devices) remains,
which is itself an imperfect proxy for pure-play casino operators (who are
often coded under Hotels, SIC 7011, instead). No S&P 500 company currently
in the dataset is flagged for gambling as a result -- worth a manual check
if the app team knows of a casino operator that should be in the S&P 500
list and isn't showing up here.

## Recent-corporate-action flag was ~80% false-positive before a regex fix

Found and fixed 2026-08-20: the original keyword scan (bare "merger" or
"spin-off" anywhere in the 10-K) matched routine risk-factor/strategy
boilerplate present in nearly every 10-K (e.g. Coca-Cola's flag fired on a
sentence about IT systems mentioning "mergers and acquisitions" as a
business-process category, unrelated to any actual event). Replaced with a
regex requiring completion language ("completed the merger," "the spin-off
was completed," "spun off," "became an independent public company").
Verified against the real EXE (Expand Energy) case from the background doc
as a true positive. This field still has no explicit trailing-12-months
date check -- a 10-K's MD&A section often recaps M&A history from more than
a year back, so a True here should be read as "a completed merger/
acquisition/spin-off is discussed in the filing," not strictly "within the
last 12 months" -- the field's own notes say to verify recency for exactly
this reason.

## New domains added to the allowlist 2026-08-20 -- reachability results

The user added `api.gunfreefunds.org`, `www.gunfreefunds.org`, `enforcedata.dol.gov`,
`opensecrets.org`/`www.opensecrets.org`, `fec.gov`/`www.fec.gov`, `ftc.gov`/`www.ftc.gov`,
and `catalog.data.gov` to the allowlist specifically to fill known coverage gaps.
Tested with the same descriptive User-Agent as the rest of the pipeline:

| Domain | Result | Detail |
|---|---|---|
| `www.fec.gov` / `fec.gov` | **Working -- integrated** | HTTP 200. Bulk committee-master (`cm.zip`) and committee-summary (`.csv`) downloads under `/files/bulk-downloads/<cycle>/` give real, filed corporate-PAC data (sponsor org + cycle receipts/disbursements). Wired into the pipeline for Q20 -- see git history 2026-08-20 "Add FEC bulk-data integration". Note: these bulk files are served via a 302 redirect from `www.fec.gov` to an FEC-managed S3 bucket in GovCloud (`cg-*.s3-us-gov-west-1.amazonaws.com`); the request still originates at the approved domain and `requests`' default redirect-following resolves it transparently, same pattern already used elsewhere in `lib.py` (`allow_redirects=True`). |
| `www.ftc.gov` / `ftc.gov` | **Working -- integrated** | HTTP 200. The Legal Library case search (`/legal-library/browse/cases-proceedings?search=<name>`) is real server-rendered HTML (not JS-only) and gives named enforcement-action hits. Wired into the pipeline as a Q11 supplement to the existing SEC full-text search -- see git history 2026-08-20 "Add FTC Legal Library integration". Its own search matches on full text, not just party name, so the pipeline additionally filters to results whose URL has a real numeric case-docket prefix AND whose title contains the company's own name (as whole words) -- both checks were needed after testing surfaced real false positives (e.g. an "Apple Inc." query returning cases with no relation to Apple; a "Home Depot" query's naive first-token match hitting "Home Matters USA"). |
| `www.opensecrets.org` / `opensecrets.org` | **Blocked** | HTTP 403, Cloudflare "Just a moment..." JS challenge on every request, both with and without `www.`. Not usable from this environment. |
| `enforcedata.dol.gov` | **Blocked (indirectly)** | The domain itself resolves (301) but redirects to `data.dol.gov`, a *different* subdomain that was not added to the allowlist -- the proxy denies it (403). `enforcedata.dol.gov` as configured is therefore not usable; if DOL enforcement data is wanted for Q8, a future session should ask the user to allowlist `data.dol.gov` specifically. |
| `api.gunfreefunds.org` | **Blocked (proxy policy)** | Same as previously documented: proxy returns a 502 CONNECT-tunnel denial for this specific subdomain. No change from the prior session's finding. |
| `www.gunfreefunds.org` | **Reachable, but no new capability** | HTTP 200 (redirects to the same client-rendered React SPA as the already-working bare `gunfreefunds.org` domain). Checked for server-side-rendered data (`window.__data`) -- present but empty; the actual search results are fetched client-side via XHR calls to `api.gunfreefunds.org`, which is blocked. So `www.gunfreefunds.org` doesn't unblock anything beyond what was already true of the bare domain (static page content only, no structured fund-level exposure data reachable). Q16 remains SIC-code-only. |
| `catalog.data.gov` | **Reachable, but search is non-functional here** | HTTP 200 for the homepage and for direct `/dataset/<slug>` pages, but both the CKAN API (`/api/3/action/package_search` etc. -- real 404s, not a proxy block) and the HTML search listing (`/dataset?q=...` 301-redirects to the homepage, dropping the query, for any query string) are unusable for keyword search from this environment. Tried several guessed NLRB dataset/org slugs (`nlrb-case-data`, `national-labor-relations-board`, etc.) directly -- all 404. **No NLRB bulk dataset was found or confirmed to exist on data.gov.** Q6 labor disputes remains at 0% coverage; this specific avenue is exhausted absent a known exact dataset URL. |

**Headless-browser retest of the four sites already known to be Cloudflare/bot-protection-blocked**
(`violationtracker.goodjobsfirst.org`, `securities.stanford.edu`, `www.bcorporation.net`, `stooq.com`):
tried real headless Chromium (Playwright, pre-installed in this environment) instead of a plain HTTP
client, per the user's suggestion that a real browser might get through where `curl`/`requests` can't.
No improvement -- three of the four (`violationtracker`, `securities.stanford.edu`, `stooq.com`) now
fail at the network/proxy level itself (`ERR_TUNNEL_CONNECTION_FAILED`, matching a plain `curl`
retest showing HTTP 000 on the same three), and `www.bcorporation.net` still hits its bot-protection
403 (`ERR_CONNECTION_RESET` in the browser). These are not solvable from this environment by any HTTP
client, headless-browser or otherwise; no further avenue is known for these four sources.

## Founder-led / family-owned detection is a flattened-text regex heuristic

Iterated extensively against real proxy-statement phrasing (see git history
2026-08-19/20 for the specific false positives found and fixed: Baker
Hughes, Adobe, Air Products, Allegion, Alphabet, Amphenol, Best Buy, Amazon,
Altria). Precision improved substantially but Air Products (APD) remains a
known, documented false positive (a director's bio mentions founding an
unrelated firm, "Mantle Ridge," with no company-suffix marker for the
filter to catch), which is why both fields are scored at Low rather than
Medium confidence project-wide. Each True hit includes the exact matched
text in its `notes` field specifically so it can be spot-checked quickly.

---
*(Per-company sourcing difficulty entries -- foreign private issuers, recent
IPOs, name/ticker changes -- will be appended below as batches are processed.)*
- **XOM** (2026-08-19): CIK 0002115436 ('ExxonMobil Holdings Corp') has no 10-K or DEF 14A filing history on EDGAR -- likely a recent holding-company reorganization/successor-registrant event (check for a predecessor CIK). Filing types on record: ['10-Q', '8-K', '8-K12B', 'POSASR', 'S-8 POS'].
- **HONA** (2026-08-20): CIK 0002089271 ('Honeywell Aerospace Inc.') has no 10-K or DEF 14A filing history on EDGAR -- likely a recent holding-company reorganization/successor-registrant event (check for a predecessor CIK). Filing types on record: ['10-12B', '10-12B/A', '10-Q', '3', '4', '424B3', '8-K', 'CERT', 'DRS', 'DRS/A', 'EFFECT', 'S-4', 'S-8', 'SCHEDULE 13G', 'SEC STAFF ACTION'].
