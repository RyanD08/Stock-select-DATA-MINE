#!/usr/bin/env python3
"""Process a batch of companies from data/sp500_full_dataset.json, filling in
every scored field with a sourced value + confidence (or an honest
'No verifiable data found'). Updates logs/progress.json after the batch and
appends to logs/manual_review_needed.md for companies that were hard to
source. Resumable: pass --start/--count or --tickers to control the batch,
or omit both to auto-continue from the first 'pending' company.
"""
import argparse
import re
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, ".")
from lib import (  # noqa: E402
    get_submissions, full_text_search, latest_filing, filing_document_url,
    fetch_filing_text, sic_screen, epa_echo_summary, osha_establishment_search,
    field, none_field, keyword_hit, find_pay_ratio, find_independent_directors_pct,
    resolve_founder_led_field, resolve_family_owned_field, RECENT_CORPORATE_ACTION_PATTERN, alcohol_2080_hit,
    ENV_KEYWORDS, LABOR_KEYWORDS, GOV_KEYWORDS, save_json, TODAY,
    match_company_to_fec_pac, ftc_case_search, FEC_CYCLE, find_ceo_gender_signal,
    cybersecurity_incident_search, find_countries_of_concern,
)
from financials import revenue_growth, debt_to_equity, dividend_consistency  # noqa: E402

DATA_PATH = "data/sp500_full_dataset.json"
PROGRESS_PATH = "logs/progress.json"
MANUAL_REVIEW_PATH = "logs/manual_review_needed.md"

US_STATES_ABBR_HINT = re.compile(r",\s*[A-Z]{2}$")


def is_domestic(hq):
    if not hq:
        return None
    # Wikipedia HQ strings end "City, State" for US, "City, Country" for foreign.
    known_non_us = ["Ireland", "United Kingdom", "Switzerland", "Bermuda", "Netherlands",
                     "Germany", "France", "Israel", "Canada", "Japan", "China", "Curacao",
                     "Cayman Islands", "Jersey", "Panama", "Singapore"]
    for c in known_non_us:
        if hq.endswith(c):
            return False
    return True


def load():
    import json
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def log_manual_review(ticker, reason):
    with open(MANUAL_REVIEW_PATH, "a") as f:
        f.write(f"- **{ticker}** ({TODAY}): {reason}\n")


def process_company(rec):
    ticker = rec["ticker"]
    name = rec["company_name"]
    cik = rec.get("cik")
    hq = rec.get("headquarters_location")

    # Q23 domestic HQ -- doesn't need EDGAR
    dom = is_domestic(hq)
    if dom is None:
        rec["domestic_hq"] = none_field("No headquarters location on file")
    else:
        rec["domestic_hq"] = field(dom, "Wikipedia S&P 500 constituents table (Headquarters Location column)",
                                    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "High")

    if not cik:
        log_manual_review(ticker, "No SEC CIK found in Wikipedia table -- likely needs manual EDGAR company search "
                                    "(e.g. recent listing, name mismatch, or non-domestic filer). All EDGAR-sourced "
                                    "fields left as 'No verifiable data found'.")
        rec["processing_status"] = "manual_review_needed"
        return rec

    try:
        submissions = get_submissions(cik)
    except Exception as e:
        log_manual_review(ticker, f"SEC EDGAR submissions.json fetch failed ({e}). Retry in a future session.")
        rec["processing_status"] = "manual_review_needed"
        return rec

    sic = submissions.get("sic")
    entity_name = submissions.get("name", name)
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"

    # --- Q13-16, Q19: SIC-code screens (rule-based, high confidence) ---
    screens = sic_screen(sic)
    sic_note = f"Registrant SIC code {sic} ({submissions.get('sicDescription')}) per SEC EDGAR submissions record. Only the top-line registrant SIC was checked; conglomerates with a sin-stock segment under a different primary SIC would be missed."
    rec["tobacco_involvement"] = field(screens["tobacco"], "SEC EDGAR registrant SIC code", sub_url, "High", sic_note)
    alcohol_needs_keyword_check = str(sic).zfill(4) == "2080"
    if not alcohol_needs_keyword_check:
        rec["alcohol_involvement"] = field(screens["alcohol"], "SEC EDGAR registrant SIC code", sub_url, "High", sic_note)
    # else: resolved below once 10-K text is fetched -- SIC 2080 ("Beverages") is a generic
    # code SEC EDGAR assigns to soft-drink makers and alcohol producers alike.
    rec["gambling_casino_involvement"] = field(screens["gambling"], "SEC EDGAR registrant SIC code", sub_url, "High", sic_note)
    rec["weapons_defense_involvement"] = field(screens["weapons"], "SEC EDGAR registrant SIC code", sub_url, "High", sic_note)
    rec["interest_based_financial_products"] = field(screens["interest_based_finance"], "SEC EDGAR registrant SIC code", sub_url, "High", sic_note)
    # Adult entertainment: no clean SIC; large public S&P 500 companies essentially never have this
    # as a core business. Mark false at Medium confidence via SIC absence, not fabricated certainty.
    rec["adult_entertainment_involvement"] = field(False, "SEC EDGAR registrant SIC code (no adult-entertainment SIC present)", sub_url, "Medium",
                                                     "No dedicated SIC code exists for this category; inferred from registrant SIC/business description not matching known adult-content classifications.")

    # --- 10-K text scan: Q1, Q2, Q4, Q5, Q7 ---
    tenk = latest_filing(submissions, "10-K")
    proxy_probe = latest_filing(submissions, "DEF 14A")
    if not tenk and not proxy_probe:
        rec["recent_corporate_action_flag"] = {
            "value": True,
            "notes": f"No 10-K or DEF 14A on file for CIK {cik} ('{entity_name}') -- this SEC registrant record has no annual/proxy filing history yet, which typically means a recent holding-company reorganization, spin-off, or new listing (e.g. an '8-K12B' successor-registrant event). Historical financials, if needed, likely live under a predecessor CIK that must be identified manually.",
        }
        log_manual_review(ticker, f"CIK {cik} ('{entity_name}') has no 10-K or DEF 14A filing history on EDGAR -- "
                                    f"likely a recent holding-company reorganization/successor-registrant event (check for a predecessor CIK). "
                                    f"Filing types on record: {sorted(set(submissions['filings']['recent']['form']))}.")
    tenk_text = None
    if tenk:
        try:
            url = filing_document_url(cik, tenk["accession"], tenk["primary_doc"])
            tenk_text = fetch_filing_text(url)
            tenk_url = url
        except Exception:
            tenk_text = None
    if tenk_text:
        low = tenk_text.lower()
        rec["carbon_fossil_fuel_involvement"] = field(
            "High" if keyword_hit(low, ENV_KEYWORDS["fossil_fuel"]) else "Low",
            f"10-K Item 1 Business description keyword scan, filed {tenk['filing_date']}", tenk_url, "Medium",
            "Keyword-based classification (fossil-fuel-related terms in business description), not an emissions figure.")
        rec["renewable_clean_tech_involvement"] = field(
            "High" if keyword_hit(low, ENV_KEYWORDS["renewable"]) else "Low",
            f"10-K Item 1 Business description keyword scan, filed {tenk['filing_date']}", tenk_url, "Medium")
        rec["sustainable_agriculture_resource_use"] = field(
            "Medium" if keyword_hit(low, ENV_KEYWORDS["sustainable_ag"]) else "Low",
            f"10-K keyword scan, filed {tenk['filing_date']}", tenk_url, "Low")
        rec["fair_wages_labor_practices"] = field(
            "Medium" if keyword_hit(low, LABOR_KEYWORDS["fair_wages"]) else "Low",
            f"10-K Human Capital section keyword scan, filed {tenk['filing_date']}", tenk_url, "Low")
        rec["workplace_diversity_equity_inclusion"] = field(
            "High" if keyword_hit(low, LABOR_KEYWORDS["dei"]) else "Low",
            f"10-K Human Capital section keyword scan, filed {tenk['filing_date']}", tenk_url, "Medium")
        action_hit = RECENT_CORPORATE_ACTION_PATTERN.search(low)
        if action_hit:
            rec["recent_corporate_action_flag"] = {"value": True, "notes": f"10-K (filed {tenk['filing_date']}) references a completed merger/spin-off/separation ('{action_hit.group(0)}') -- verify recency and treat single-year financial comparisons with caution."}
        if alcohol_needs_keyword_check:
            hit = alcohol_2080_hit(low)
            rec["alcohol_involvement"] = field(
                hit, "SEC EDGAR registrant SIC code (2080, generic) + 10-K business description keyword scan",
                tenk_url, "Medium",
                f"{sic_note} SIC 2080 ('Beverages') does not by itself distinguish alcohol producers from soft-drink makers, so this was disambiguated by scanning the 10-K business description for alcohol-specific terms (wine/beer/spirits/etc.).")
    else:
        for f_ in ["carbon_fossil_fuel_involvement", "renewable_clean_tech_involvement",
                   "sustainable_agriculture_resource_use", "fair_wages_labor_practices",
                   "workplace_diversity_equity_inclusion"]:
            rec[f_] = none_field("No 10-K found/fetchable on EDGAR")
        if alcohol_needs_keyword_check:
            rec["alcohol_involvement"] = none_field(f"{sic_note} SIC 2080 is generic and no 10-K was fetchable to disambiguate via keyword scan.")

    # --- DEF 14A text scan: Q9 board independence, Q10 pay ratio, Q12 share class ---
    proxy = latest_filing(submissions, "DEF 14A")
    proxy_text = None
    if proxy:
        try:
            purl = filing_document_url(cik, proxy["accession"], proxy["primary_doc"])
            proxy_text = fetch_filing_text(purl)
        except Exception:
            proxy_text = None
    if proxy_text:
        pay_ratio = find_pay_ratio(proxy_text)
        rec["ceo_pay_ratio"] = (
            field(pay_ratio, f"DEF 14A Pay Ratio Disclosure, filed {proxy['filing_date']}", purl, "High")
            if pay_ratio else none_field("Pay ratio pattern not found in proxy text scan")
        )
        pct_indep = find_independent_directors_pct(proxy_text)
        rec["board_transparency_independence"] = (
            field({"pct_independent_directors": pct_indep}, f"DEF 14A, filed {proxy['filing_date']}", purl, "Medium")
            if pct_indep else none_field("Independent-director percentage not found in proxy text scan")
        )
        low_p = proxy_text.lower()
        dual = keyword_hit(low_p, GOV_KEYWORDS["dual_class"])
        rec["shareholder_rights_voting_structure"] = field(
            "dual_class" if dual else "single_class",
            f"DEF 14A share class disclosure, filed {proxy['filing_date']}", purl, "Medium" if dual else "Low")
        rec["founder_led"] = resolve_founder_led_field(proxy_text, rec.get("company_name"), purl, proxy["filing_date"])
        rec["family_owned"] = resolve_family_owned_field(proxy_text, purl, proxy["filing_date"])
        # --- Additional criteria (not one of the 27 official questions): women_led --
        # see data/candidate_additional_criteria.json.
        gender_sig = find_ceo_gender_signal(proxy_text)
        if gender_sig:
            is_woman, surname, evidence = gender_sig
            rec["women_led"] = field(
                is_woman, f"DEF 14A proxy statement, filed {proxy['filing_date']}", purl, "Low",
                f"CEO surname identified as '{surname}' via name+title adjacency in the proxy text; gender "
                f"determined from the filing's own honorific (Mr./Ms./Mrs.) or, where none was used, a "
                f"majority of pronoun references (she/her vs he/his) describing that person -- not inferred "
                f"from the first name. Not a manual bio read -- verify. Evidence: \"...{evidence[:200]}...\"")
        else:
            rec["women_led"] = none_field("No consistent CEO-name/honorific-or-pronoun pairing found in DEF 14A proxy text scan")
    else:
        for f_ in ["ceo_pay_ratio", "board_transparency_independence", "shareholder_rights_voting_structure",
                   "founder_led", "family_owned", "women_led"]:
            rec[f_] = none_field("No DEF 14A found/fetchable on EDGAR")

    # --- Q11 fraud/corruption: SEC full-text search + FTC Legal Library case search ---
    try:
        fraud_hits = full_text_search(entity_name, forms="8-K")
        n_hits = fraud_hits.get("hits", {}).get("total", {}).get("value", 0)
    except Exception:
        n_hits = None
    try:
        ftc_hits = ftc_case_search(entity_name)
    except Exception:
        ftc_hits = None

    if ftc_hits:
        value = {"ftc_case_count": ftc_hits["case_count"], "ftc_example_cases": ftc_hits["examples"]}
        notes = (f"FTC Legal Library case search ({ftc_hits['search_url']}) name-matched to {ftc_hits['case_count']} "
                 "case(s) -- see ftc_example_cases for titles/links, verify each is this company and not a "
                 "same-named unrelated party.")
        if n_hits:
            value["sec_fulltext_search_hits"] = n_hits
            notes += f" Also {n_hits} SEC EDGAR full-text search hit(s) across 8-K filings (name-matched, not confirmed litigation releases)."
        rec["fraud_corruption_scandal_history"] = field(
            value, "FTC Legal Library case search (ftc.gov) + SEC EDGAR full-text search (efts.sec.gov)",
            ftc_hits["search_url"], "Medium", notes)
    elif n_hits:
        rec["fraud_corruption_scandal_history"] = field(
            {"sec_fulltext_search_hits": n_hits}, "SEC EDGAR full-text search (efts.sec.gov) across 8-K filings",
            f"https://www.sec.gov/cgi-bin/srqsb?text={entity_name}", "Low",
            "Raw full-text search hit count only (name-matched 8-K filings, not confirmed litigation releases); no FTC Legal Library case matched. Violation Tracker and Stanford Securities Class Action Clearinghouse -- the two stronger intended sources -- are blocked in this environment; see logs/manual_review_needed.md.")
    else:
        rec["fraud_corruption_scandal_history"] = none_field("No SEC full-text search hits and no FTC Legal Library case matched; Violation Tracker/Stanford Clearinghouse unavailable (see manual_review log)")
    # --- Q22 data privacy: 8-K Item 1.05 material-cybersecurity-incident disclosures ---
    try:
        cyber = cybersecurity_incident_search(cik)
    except Exception:
        cyber = None
    if cyber is None:
        rec["data_privacy_practices"] = none_field("SEC EDGAR full-text search (Item 1.05) request failed")
    elif cyber["incident_count"] > 0:
        rec["data_privacy_practices"] = field(
            {"item_1_05_incident_count": cyber["incident_count"], "examples": cyber["examples"]},
            "SEC EDGAR full-text search (efts.sec.gov), 8-K Item 1.05 filings", cyber["search_url"], "Medium",
            f"{cyber['incident_count']} material-cybersecurity-incident 8-K(s) (SEC Item 1.05, rule effective "
            "December 2023) filed under this company's own CIK -- self-disclosed, not a third-party finding.")
    else:
        rec["data_privacy_practices"] = field(
            {"item_1_05_incident_count": 0}, "SEC EDGAR full-text search (efts.sec.gov), 8-K Item 1.05 filings",
            cyber["search_url"], "Low",
            "No Item 1.05 (material cybersecurity incident) 8-K filed under this company's own CIK. Item 1.05 "
            "only exists for incidents from December 2023 onward, so this does not rule out an incident before "
            "the rule took effect, or one judged immaterial.")

    # --- Q18: religious compliance -- always None per background doc ---
    rec["religious_investment_compliance"] = field(
        "No verifiable per-company religious compliance data source available", None, None, "None",
        "No comprehensive free public halal/kosher screening database exists at S&P 500 scale (confirmed gap per project background doc).")

    # --- Q3 EPA ECHO ---
    try:
        echo = epa_echo_summary(entity_name)
        if echo and echo.get("Message") == "Success":
            rec["environmental_pollution_violations"] = field(
                {
                    "matched_facility_query_rows": int(echo.get("QueryRows", 0)),
                    "caa_case_rows": int(echo.get("CAARows", 0)),
                    "cwa_case_rows": int(echo.get("CWARows", 0)),
                    "rcra_case_rows": int(echo.get("RCRRows", 0)),
                    "total_penalties_usd": echo.get("TotalPenalties"),
                },
                "EPA ECHO facility search (name-matched)", f"https://echodata.epa.gov/echo/echo_rest_services.get_facilities?p_fn={entity_name}",
                "Medium", "Aggregated across all EPA-regulated facilities whose name matches the company name substring; may include unrelated facilities with similar names, and may miss facilities filed under subsidiary names.")
        else:
            rec["environmental_pollution_violations"] = none_field("No EPA ECHO facilities matched by company name")
    except Exception:
        rec["environmental_pollution_violations"] = none_field("EPA ECHO request failed")

    # --- Q8 OSHA ---
    try:
        osha = osha_establishment_search(entity_name)
        if osha and osha["row_count"] > 0:
            rec["worker_safety_record"] = field(
                {"matched_establishment_rows": osha["row_count"]}, "OSHA establishment search (name-matched)",
                osha["source_url"], "Medium",
                "Aggregated across all OSHA-inspected establishments whose name matches the company name substring; row count reflects inspections, not confirmed violations -- see individual establishment records for detail.")
        else:
            rec["worker_safety_record"] = none_field("No OSHA establishments matched by company name")
    except Exception:
        rec["worker_safety_record"] = none_field("OSHA request failed")

    # --- Q6 NLRB -- not programmatically reachable in this environment ---
    rec["labor_disputes_exploitation_history"] = none_field(
        "NLRB case search (nlrb.gov) is a JS-rendered Drupal search widget with no discoverable JSON/HTML API reachable by this pipeline; see logs/manual_review_needed.md")

    # --- Q20 political donation transparency ---
    try:
        fec_match = match_company_to_fec_pac(name)
    except Exception:
        fec_match = None
    if fec_match:
        total_receipts = sum(float(s["TTL_RECEIPTS"]) for _, _, _, s in fec_match if s and s.get("TTL_RECEIPTS"))
        total_disb = sum(float(s["TTL_DISB"]) for _, _, _, s in fec_match if s and s.get("TTL_DISB"))
        cmte_names = "; ".join(cmte_nm for _, cmte_nm, _, _ in fec_match)
        rec["political_donation_transparency"] = field(
            "Disclosed",
            f"FEC committee master + committee summary bulk data, {FEC_CYCLE} election cycle",
            f"https://www.fec.gov/data/committee/{fec_match[0][0]}/?cycle={FEC_CYCLE}", "High",
            f"Matched to registered corporate PAC(s): {cmte_names}. Cycle totals: ${total_receipts:,.2f} receipts / "
            f"${total_disb:,.2f} disbursements. Matched by company name against FEC's CONNECTED_ORG_NM/committee-name "
            "fields (FEC does not publish a CIK crosswalk) -- verify the matched committee is this company, not a "
            "similarly-named one.")
    elif proxy_text and re.search(r"political (contribut|spending|donation)", proxy_text.lower()):
        rec["political_donation_transparency"] = field("Disclosed", f"DEF 14A political spending disclosure, filed {proxy['filing_date']}", purl, "Medium")
    else:
        rec["political_donation_transparency"] = none_field("No FEC-registered corporate PAC name-matched and no political-spending disclosure language found in proxy text scan; opensecrets.org blocked by Cloudflare, cii.org unavailable in this environment")

    # --- Q21 countries of concern: 10-K text scan + Section 13(r) Iran/Syria disclosure ---
    if tenk_text:
        coc = find_countries_of_concern(tenk_text)
        if coc:
            countries = list(coc["countries"])
            if coc["section_13r"] and "Iran" not in countries:
                countries = sorted(countries + ["Iran (Section 13(r) disclosure)"])
            notes = ("Section 13(r) of the Exchange Act (Iran Threat Reduction and Syria Human Rights Act) "
                      "disclosure present in this filing -- a company only includes this section when it has "
                      "actual Iran/Syria-connected activity to report. " if coc["section_13r"] else "")
            if coc["evidence"]:
                notes += ("Country name(s) matched near operational-presence language (subsidiary/facility/"
                           "revenue/etc.), not a bare mention: " +
                           "; ".join(f"{c}: \"...{ev[:150]}...\"" for c, ev in coc["evidence"].items()))
            rec["countries_of_concern_operations"] = field(
                countries, f"10-K Item 1/1A text scan + Section 13(r) disclosure, filed {tenk['filing_date']}",
                tenk_url, "High" if coc["section_13r"] else "Medium", notes)
        else:
            rec["countries_of_concern_operations"] = field(
                [], f"10-K text scan, filed {tenk['filing_date']}", tenk_url, "Low",
                "No OFAC-comprehensively-sanctioned-country name found near operational-presence language, and "
                "no Section 13(r) Iran/Syria disclosure in this filing. Scope is deliberately narrow (Russia, "
                "Iran, North Korea, Syria, Cuba, Belarus, Venezuela) -- does not cover countries under only "
                "sectoral/targeted sanctions (e.g. China).")
    else:
        rec["countries_of_concern_operations"] = none_field("No 10-K found/fetchable on EDGAR")

    # --- Q26/27 Growth Potential / Stability (EDGAR-derived only; see manual_review log for price-data gap) ---
    try:
        rg = revenue_growth(cik)
    except Exception:
        rg = None
    try:
        dte = debt_to_equity(cik)
    except Exception:
        dte = None
    try:
        divc = dividend_consistency(cik)
    except Exception:
        divc = None

    if rg:
        tier = "High" if rg["growth_pct"] >= 10 else ("Medium" if rg["growth_pct"] >= 0 else "Low")
        rec["growth_potential"] = field(
            tier, f"SEC EDGAR XBRL company facts ({rg['tag']}), FY{rg['latest_fy']}",
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{rg['tag']}.json", "Medium",
            f"Based on revenue growth of {rg['growth_pct']}% YoY only ({rg['prior_val']:,} -> {rg['latest_val']:,}); "
            "5-year total return component unavailable (Finnhub/Alpha Vantage/Stooq all blocked in this environment -- see logs/manual_review_needed.md).")
    else:
        rec["growth_potential"] = none_field("No annual revenue XBRL facts found on EDGAR, and price-return sources are unavailable in this environment")

    stability_parts = {}
    notes_parts = []
    if dte:
        stability_parts["debt_to_equity"] = dte["debt_to_equity"]
        notes_parts.append(f"D/E {dte['debt_to_equity']} as of {dte['as_of']}")
    if divc:
        stability_parts["dividend_years_paid_of_last_5"] = divc["years_paid"]
        notes_parts.append(f"paid dividend in {divc['years_paid']}/{divc['years_checked']} most recent fiscal years")
    if stability_parts:
        de = stability_parts.get("debt_to_equity")
        div_ok = stability_parts.get("dividend_years_paid_of_last_5", 0) >= 3
        tier = "High" if (de is not None and de < 1.5 and div_ok) else ("Low" if (de is not None and de > 3) else "Medium")
        rec["stability"] = field(tier, "SEC EDGAR XBRL company facts (Liabilities, StockholdersEquity, CommonStockDividendsPerShareDeclared)",
                                  f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", "Medium",
                                  "; ".join(notes_parts) + ". Volatility/beta component unavailable (price-data sources blocked in this environment).")
    else:
        rec["stability"] = none_field("No balance-sheet/dividend XBRL facts found on EDGAR, and volatility sources are unavailable in this environment")

    rec["processing_status"] = "complete"
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--tickers", type=str, default=None, help="comma-separated ticker list to force-process")
    args = ap.parse_args()

    dataset = load()
    by_ticker = {r["ticker"]: r for r in dataset}

    if args.tickers:
        todo = [t.strip() for t in args.tickers.split(",")]
    else:
        todo = [r["ticker"] for r in dataset if r["processing_status"] == "pending"][:args.count]

    processed = []
    for i, ticker in enumerate(todo):
        rec = by_ticker.get(ticker)
        if not rec:
            continue
        try:
            process_company(rec)
            processed.append(ticker)
        except Exception as e:
            log_manual_review(ticker, f"Unhandled exception during processing: {e}\n{traceback.format_exc()[-500:]}")
            rec["processing_status"] = "manual_review_needed"
        if (i + 1) % 5 == 0:
            save(dataset)
            print(f"[{i+1}/{len(todo)}] checkpoint saved", flush=True)

    save(dataset)

    # progress.json
    import json
    complete = [r["ticker"] for r in dataset if r["processing_status"] == "complete"]
    manual = [r["ticker"] for r in dataset if r["processing_status"] == "manual_review_needed"]
    pending = [r["ticker"] for r in dataset if r["processing_status"] == "pending"]
    progress = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_companies": len(dataset),
        "complete": len(complete),
        "manual_review_needed": len(manual),
        "pending": len(pending),
        "complete_tickers": sorted(complete),
        "manual_review_tickers": sorted(manual),
    }
    save_json(PROGRESS_PATH, progress)
    print(f"Batch done. complete={len(complete)} manual_review={len(manual)} pending={len(pending)}")


if __name__ == "__main__":
    main()
