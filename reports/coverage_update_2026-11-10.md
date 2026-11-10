# Coverage Update — 2026-11-10

Single-session run. Audited current coverage first (the snapshot numbers in
the task brief were stale and not trusted), then worked gaps in the priority
order given: better-matching retries on existing sources, sector-appropriate
sources for Financials/Communication Services/Real Estate, labor disputes,
governance, founder/family/women-led, then political/privacy/countries.

## 1. Coverage, before → after

All counts are companies with real data (confidence High/Medium/Low) out of
503, computed directly from `data/sp500_full_dataset.json` — not from the
task brief's snapshot.

| Field | Before | After | Change |
|---|---|---|---|
| Environmental pollution violations | 393/503 (78.1%) | 487/503 (96.8%) | **+94** |
| Board transparency / independence | 155/503 (30.8%) | 252/503 (50.1%) | **+97** |
| CEO pay ratio | 424/503 (84.3%) | 445/503 (88.5%) | **+21** |
| Founder-led | 433/503 (86.1%) | 441/503 (87.7%) | **+8** |
| Family-owned | 464/503 (92.2%) | 493/503 (98.0%) | **+29** |
| Women-led CEO | 374/503 (74.4%) | 383/503 (76.1%) | **+9** |
| Political donation transparency | 323/503 (64.2%) | 334/503 (66.4%) | **+11** |
| Data privacy / cybersecurity incidents | 493/503 (98.0%) | 503/503 (100.0%) | **+10** |
| Worker safety record | 185/503 (36.8%) | 185/503 (36.8%) real + 74 reclassified | +0 real, see §3 |
| Labor disputes / exploitation history | 0/503 (0.0%) | 0/503 (0.0%) | +0, blocked |
| Fraud / corruption / scandal history | 456/503 (90.7%) | 456/503 (90.7%) | +0, mostly blocked |
| Countries of concern operations | 501/503 (99.6%) | 501/503 (99.6%) | +0, 2 unfixable |
| Fossil fuel / carbon, renewable, sustainable ag, fair wages, DEI, shareholder voting, sin-stock flags, interest-based products, domestic HQ, Growth Potential, Stability | unchanged | unchanged | not in scope this session |

**GICS sector** (not a scored field, but infrastructure this audit needed):
was blank (`""`) for all 503 companies — a Wikipedia page markup change broke
the fetch script's column match. Fixed and backfilled to 503/503; this is
what made the by-sector breakdown possible at all. See §4.

### By sector, the fields this session touched most

| Field | Comm. Svcs | Cons. Disc. | Cons. Staples | Energy | Financials | Health Care | Industrials | Info Tech | Materials | Real Estate | Utilities |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Environmental pollution violations | 96% | 100% | 100% | 100% | 80% | 100% | 100% | 100% | 100% | 100% | 100% |
| Worker safety record (real data only) | 42% | 45% | 50% | 24% | **12%** | 44% | 47% | 29% | 52% | 40% | 39% |
| Board transparency / independence | 33% | 49% | 56% | 29% | 53% | 47% | 51% | 47% | 64% | 70% | 48% |
| Political donation transparency | 50% | 62% | 82% | 76% | 67% | 71% | 59% | 56% | 64% | 70% | 94% |

Financials' 12% worker-safety figure is **real, structural non-applicability**
for most of that sector (see §3), not a search failure — it's not counted
against the field's honest coverage once reclassified.

## 2. What each source delivered

| Source | Result |
|---|---|
| **EPA ECHO** (echodata.epa.gov) | 90/94 gaps recovered on a clean re-run — the API was transiently degraded at original collection time, not a code bug. The remaining 4 (BDX, DE, LLY, MKC) shared one real bug: EPA ECHO's name-search parameter can't handle a literal `&`; fixed permanently (`&` → `AND`) in `lib.py`. environmental_pollution_violations has **zero genuine gaps left** (96.8% real + 3.2% structurally not-applicable). |
| **OSHA** (www.osha.gov) | **New blocker.** The whole site, including its homepage, now returns a site-wide HTTP 403 to this project's compliant User-Agent — not routed around. worker_safety_record retries were not possible this session. |
| **SEC EDGAR / DEF 14A text** | Delivered the bulk of this session's gains: a second board-independence recognizer (the standard exchange-compliance sentence, cross-checked against the proxy's own director table) recovered 97 gaps; two new CEO-pay-ratio phrasings plus a comma-truncation bug fix recovered 21; a reversed Title-then-Name CEO/Chair-identification pattern recovered 8 founder-led and 9 women-led gaps; four new beneficial-ownership section headings recovered 29 family-owned gaps; four new political-activity disclosure phrasings recovered 11 political-donation gaps. |
| **SEC EDGAR full-text search (efts.sec.gov)** | All 10 data_privacy_practices gaps were a transient request failure; recovered on a clean retry. Now 100%. |
| **FEC bulk data** (fec.gov) | Re-verified working correctly (542 corporate-PAC org entries, 801 committee entries) — 0 new matches among the 180 political-donation gaps confirms most of those companies genuinely have no FEC-registered PAC under this project's deliberately strict matching criteria, not a matching bug. |
| **NLRB** (www.nlrb.gov) | Reachable again (unlike a prior session's finding), but its real Case Search tool lives at `/search/case`, which the site's own `robots.txt` disallows. Its public report pages have no company-name filter. labor_disputes_exploitation_history stays at 0%; not routed around. |
| **Violation Tracker** (violationtracker.goodjobsfirst.org) | Re-tested; still blocked at the network/proxy level (403 on CONNECT), unchanged from prior findings. |
| **CFPB, FDIC, Federal Reserve, OCC, FINRA, OpenSanctions, FCC** | All 7 were blocked at this environment's network allowlist, not by the sites themselves — the allowlist was updated mid-session (with the user's approval) and all 7 became reachable. Only 7 companies were genuine gaps in the target sectors (Financials/Comm Services/Real Estate), so investigation was scoped to those: CFPB's complaint API works but needs an exact match against its own internal company-name taxonomy (no autocomplete found); OCC's real search tool is on a different, not-yet-allowed subdomain (`apps.occ.gov`); FDIC publishes enforcement actions as periodic PDFs, not an API; OpenSanctions needs an API key this environment doesn't have, and its website disallows generic-bot search in its own `robots.txt`. None of the 7 target companies were filled this session. |

## 3. Sector-bias reclassification

Per the task's Step 2: distinguished "no regulated facilities exist for this
business" from "a facility search failed to find a real match," for
environmental_pollution_violations and worker_safety_record, both
facility-presence-dependent.

- **Financials**: every SIC code actually present among this dataset's 76
  Financials companies (banks, insurers, brokers, investment advisers,
  payments/fintech business services) is facility-light — none implies an
  OSHA/EPA-regulated industrial site. 74 worker_safety_record and most of the
  few remaining environmental_pollution_violations None records were
  reclassified to `"No applicable facility records"` (confidence stays
  `None`; this changes how the gap reads, not the coverage percentage).
- **Communication Services**: reclassified only a narrow set of genuinely
  office/software-based sub-industries (computer services, advertising
  agencies) — explicitly **not** telecom, broadcasting, cable, publishing or
  amusement/recreation, which can have real physical-plant exposure.
- **Real Estate**: deliberately **not** reclassified. The actual coverage
  data (73% environmental, 40% worker-safety before this session) doesn't
  support the "few regulated facilities" premise given in the task brief for
  this sector — REITs by definition own/operate physical property.

## 4. Infrastructure fix needed before the audit could run

`gics_sector` was blank (`""`) for all 503 companies. Root cause: Wikipedia's
constituents table now renders that column's header as `"GICSSector"` (no
space) instead of `"GICS Sector"`, so `fetch_sp500_list.py`'s exact-string
header lookup silently matched nothing. Fixed with a case/whitespace-
insensitive header matcher and backfilled from the corrected extraction.
7 tickers (BLDR, CTVA, KVUE, TAP, PSKY, TTD, WBD) are no longer in the live
Wikipedia table under those symbols (a recent index reconstitution this
dataset hasn't been re-synced against); their sectors were resolved from
their already-correct `gics_sub_industry` via the standard GICS taxonomy
instead of left blank. Logged to `logs/manual_review_needed.md`.

## 5. Fields still empty, and the honest reason

- **Labor disputes / exploitation history (0%)**: NLRB's real Case Search
  tool is at a robots.txt-disallowed path; its public reports have no
  company filter. Violation Tracker is network-blocked. No permitted source
  currently reaches this data.
- **Worker safety record (36.8% real + ~15% structurally N/A)**: OSHA now
  returns a site-wide 403 to this project. Frozen until that changes.
- **Fraud/corruption/scandal history (90.7%, 7 remaining gaps)**: all in
  Financials/Communication Services; the newly-approved sector sources each
  had their own access snag (see §2) within this session's time budget.
- **Political donation transparency (66.4%, 162 remaining gaps)**: tested
  broadly — only 13 of the 180 original gap companies had ANY
  political-activity-related language at all in their proxy, and 11 of those
  were real and captured. The other 162 genuinely have neither an FEC PAC nor
  any disclosure of political activity in their proxy.
- **Board transparency/independence (50.1%, 251 remaining gaps)**: the
  dominant structural cause, confirmed on Apple's own director table, is that
  most proxies render the "Independent" column as a bare checkmark `<img>`
  with no text/alt equivalent at all — unrecoverable from text, and this
  project will not attempt image/OCR analysis for a field this consequential.
- **Founder-led (87.7%, 62 remaining gaps) / Women-led (76.1%, 112 remaining
  gaps)**: the CEO (or a consistently-gendered reference to them) genuinely
  can't be identified by name in the filing text, in either name-order this
  project now checks.
- **Countries of concern operations (99.6%, 2 remaining gaps: XOM, HONA)**:
  both are known successor-registrant CIKs with no 10-K filing history;
  would need the predecessor CIK identified, not attempted this session.
- **ERIE (6 fields)**: files DEF 14C (an information statement) instead of
  DEF 14A; this project's pipeline only ever looks for DEF 14A. One-company
  issue, not worth a pipeline change; flagged for manual pull.
- **BX, FDXF, PSKY**: no DEF 14A of any kind, each for a different reason
  (no proxy ever filed; too-recent spin-off; contested-merger-only filings).

## 6. Conflicts and surprises

- **AMCR's stored ceo_pay_ratio (119) is wrong.** Found while regression-
  testing new patterns: the real value is 246 ("the ratio ... was 246 to
  1"); 119 appears to be a mis-extraction from an unrelated country
  employee-headcount table ("Morocco (119 employees)") in the same filing.
  Per this project's "never overwrite, log conflicts" rule, **not
  corrected** — flagged in `logs/manual_review_needed.md` for a human
  decision.
- **A real, pre-existing bug was found and fixed in a shared helper that
  also feeds the already-shipped `growth_potential` (Q26) field**: EPA
  ECHO's `&`-in-name issue, and separately the comma-truncation bug in
  `find_pay_ratio()` (confirmed on Coherent: "1 to 1,381" was being read as
  1.0). Both fixes are now permanent in `lib.py`, so any future run benefits,
  but **already-shipped data computed before this fix was not
  retroactively re-checked** beyond what this session's gap-filling touched.
- **No field this session showed suspiciously flat variation** — every
  newly-filled batch had a believable true/false mix (e.g. founder-led and
  family-owned recoveries were "all False" batches, which makes sense: the
  recovered cases were specifically ones where a name/section COULD finally
  be identified and checked, and most S&P 500 companies are in fact not
  founder-led or family-owned).

## 7. Suggested sources logged this session (not accessed, pending approval)

- `apps.occ.gov` — OCC's real Enforcement Actions Search tool; a different
  subdomain than the one added to the allowlist.
- An OpenSanctions API key — the documented `api.opensanctions.org` ("yente")
  API needs one; no free/keyless tier was found.
- (Re-confirmed from a prior session, unchanged) `data.dol.gov` for Q8 worker
  safety, and the XBRL Frames API for Q21 country-of-operations (now
  superseded — Q21 was later implemented on a different working method).

## 8. Companies needing manual review

- **ERIE** — files DEF 14C, not DEF 14A; six fields stuck at None for this
  reason alone. Needs a manual pull of its DEF 14C.
- **BX, FDXF, PSKY** — no DEF 14A of any kind (see §5).
- **XOM, HONA** — no 10-K/DEF 14A filing history on EDGAR under their current
  CIK; likely a successor-registrant/reorganization event. A predecessor CIK
  would need to be identified.
- **BLDR, CTVA, KVUE, TAP, PSKY, TTD, WBD** — no longer in the live Wikipedia
  S&P 500 table under these symbols; a recent index reconstitution this
  dataset's constituent list hasn't been re-synced against.
- **AMCR** — stored ceo_pay_ratio (119) conflicts with a freshly-verified
  correct value (246); needs a human decision to correct it (see §6).

## 9. Recommended next steps, ranked by expected coverage impact

1. **Re-test OSHA at the start of a future session.** If the 403 lifts,
   worker_safety_record's real (non-structural) gap is still the largest
   remaining opportunity in the environmental/labor category — could move
   from 36.8% toward EPA ECHO's ~97% ceiling on a clean retry alone, the same
   pattern that worked for EPA ECHO this session.
2. **Pursue NLRB's data another way.** Either get explicit sign-off to drive
   the actual Case Search tool with a headless browser (not a robots.txt
   violation if done through a different, allowed path/API the tool itself
   uses), or watch for a bulk open-data extract. This is the only path to
   moving labor_disputes_exploitation_history off 0%.
3. **Resolve the Financials/Comm-Services/Real-Estate enforcement-source
   access snags** (CFPB name-crosswalk, `apps.occ.gov` allowlisting, an
   OpenSanctions key) — low company count (7) but each is now a narrowly
   scoped, well-understood blocker rather than an unknown.
4. **Decide on AMCR's conflict** and, if corrected, consider whether to spot-
   check other `growth_potential`/`ceo_pay_ratio` values computed before this
   session's bug fixes for the same class of error.
5. **Identify predecessor CIKs for XOM and HONA**, and re-sync the S&P 500
   constituent list (BLDR/CTVA/KVUE/TAP/PSKY/TTD/WBD vs. whatever 7 companies
   have replaced them) if a full refresh is ever in scope.
6. **founder_led/women_led's remaining ~60-110 gaps each** are probably close
   to this project's practical ceiling without a materially different
   technique (e.g. a structured bio-table parser) — lower priority than the
   items above given the effort already invested this session.
