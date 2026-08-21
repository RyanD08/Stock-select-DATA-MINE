#!/usr/bin/env python3
"""Populate the `financial_metrics` field for every company (see
schema/company_schema.json's additional_criteria.financial_metrics entry).

Two live sources, both on the approved list:
  - GitHub CSV (datasets/s-and-p-500-companies-financials, raw.githubusercontent.com)
    -> market_cap_usd, dividend_yield_pct, pe_ratio, eps_ttm,
       fifty_two_week_low/high, price_to_book, price_to_sales, ebitda_usd
  - SEC EDGAR XBRL (data.sec.gov, via scripts/financials.py)
    -> revenue_growth_yoy_pct, profit_margin_pct, debt_to_equity_ratio,
       free_cash_flow_margin_pct

Finnhub (no API key configured here), Stooq, and Alpha Vantage (both
network-blocked at the proxy level in this environment) are unavailable,
so analyst_consensus_rating, beta, yoy_stock_price_return_pct, and
five_year_total_return_pct are written as explicit None for every company,
each with a notes string saying exactly why -- never fabricated.

Companies with recent_corporate_action_flag=true get their YoY-type metric
(revenue_growth_yoy_pct) marked "Unreliable -- recent merger/spin-off/IPO,
YoY comparison not meaningful" instead of a computed number.

Resumable: only processes records that don't already have a
financial_metrics key, checkpoints every 20."""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from lib import get_github_financials_dataset, field, none_field, save_json, _normalize_github_ticker  # noqa: E402
from financials import revenue_growth, profit_margin, debt_to_equity, free_cash_flow_margin  # noqa: E402

DATA_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "sp500_full_dataset.json")
CHECKPOINT_EVERY = 20

GITHUB_SOURCE_NAME = "GitHub dataset: datasets/s-and-p-500-companies-financials (Yahoo Finance via Open Knowledge Foundation, PDDL license)"
GITHUB_SOURCE_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies-financials/master/data/constituents-financials.csv"
SEC_SOURCE_NAME = "SEC EDGAR XBRL companyconcept API"

_UNAVAILABLE_NOTES = {
    "analyst_consensus_rating": "No analyst consensus data available on free-tier sources -- Finnhub requires an API key not configured in this environment; Stooq and Alpha Vantage are blocked at the network proxy level; no credible, actively-maintained free analyst-consensus dataset was found on raw.githubusercontent.com.",
    "beta": "Beta requires historical price-return data to compute against a market index; Finnhub (needs an API key we don't have), Stooq, and Alpha Vantage (both blocked at the network proxy level in this environment) are the only approved sources for this, and none is reachable here.",
    "yoy_stock_price_return_pct": "Trailing-12-month price return requires historical daily price data; Finnhub (needs an API key we don't have), Stooq, and Alpha Vantage (both blocked at the network proxy level in this environment) are the only approved sources for this, and none is reachable here.",
    "five_year_total_return_pct": "5-year total return requires 5 years of historical price + dividend data; Finnhub (needs an API key we don't have), Stooq, and Alpha Vantage (both blocked at the network proxy level in this environment) are the only approved sources for this, and none is reachable here.",
}


def _num(row, key):
    v = row.get(key, "")
    if v in (None, "", "N/A", "NaN"):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    if f != f:  # NaN
        return None
    return f


def github_metrics(row):
    """Build the GitHub-CSV-derived subset of financial_metrics for one
    matched row. Returns a dict of metric_name -> field()."""
    out = {}

    mcap = _num(row, "Market Cap")
    out["market_cap_usd"] = (
        field(mcap, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        if mcap is not None else none_field("Market cap not present/parseable in the GitHub dataset row for this ticker.")
    )

    dy = _num(row, "Dividend Yield")
    if dy is not None:
        notes = "No dividend paid." if dy == 0 else None
        out["dividend_yield_pct"] = field(round(dy * 100, 4), GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High", notes)
    else:
        out["dividend_yield_pct"] = none_field("Dividend yield not present/parseable in the GitHub dataset row for this ticker.")

    pe = _num(row, "Price/Earnings")
    out["pe_ratio"] = (
        field(pe, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        if pe is not None else none_field("P/E not present/parseable (often means negative or undefined trailing earnings) in the GitHub dataset row for this ticker.")
    )

    eps = _num(row, "Earnings/Share")
    out["eps_ttm"] = (
        field(eps, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        if eps is not None else none_field("EPS not present/parseable in the GitHub dataset row for this ticker.")
    )

    lo, hi = _num(row, "52 Week Low"), _num(row, "52 Week High")
    if lo is not None and hi is not None:
        out["fifty_two_week_low"] = field(lo, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        out["fifty_two_week_high"] = field(hi, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
    else:
        out["fifty_two_week_low"] = none_field("52-week range not present/parseable in the GitHub dataset row for this ticker.")
        out["fifty_two_week_high"] = none_field("52-week range not present/parseable in the GitHub dataset row for this ticker.")

    pb = _num(row, "Price/Book")
    out["price_to_book"] = (
        field(pb, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        if pb is not None else none_field("Price/Book not present/parseable in the GitHub dataset row for this ticker.")
    )

    ps = _num(row, "Price/Sales")
    out["price_to_sales"] = (
        field(ps, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        if ps is not None else none_field("Price/Sales not present/parseable in the GitHub dataset row for this ticker.")
    )

    ebitda = _num(row, "EBITDA")
    out["ebitda_usd"] = (
        field(ebitda, GITHUB_SOURCE_NAME, GITHUB_SOURCE_URL, "High")
        if ebitda is not None else none_field("EBITDA not present/parseable in the GitHub dataset row for this ticker.")
    )

    return out


def github_none_metrics(reason):
    keys = ["market_cap_usd", "dividend_yield_pct", "pe_ratio", "eps_ttm",
            "fifty_two_week_low", "fifty_two_week_high", "price_to_book",
            "price_to_sales", "ebitda_usd"]
    return {k: none_field(reason) for k in keys}


def sec_metrics(cik, corporate_action_flagged):
    """Build the SEC-EDGAR-derived subset. cik may be None/missing."""
    out = {}

    if not cik:
        reason = "No CIK on file for this company -- cannot query SEC EDGAR XBRL."
        out["revenue_growth_yoy_pct"] = none_field(reason)
        out["profit_margin_pct"] = none_field(reason)
        out["debt_to_equity_ratio"] = none_field(reason)
        out["free_cash_flow_margin_pct"] = none_field(reason)
        return out

    try:
        rg = revenue_growth(cik)
    except Exception:
        rg = None
    if corporate_action_flagged:
        out["revenue_growth_yoy_pct"] = field(
            "Unreliable -- recent merger/spin-off/IPO, YoY comparison not meaningful",
            SEC_SOURCE_NAME, f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/Revenues.json",
            "Low", "recent_corporate_action_flag is set for this company; see that field's notes for the specific event.")
    elif rg:
        out["revenue_growth_yoy_pct"] = field(
            rg["growth_pct"], SEC_SOURCE_NAME,
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{rg['tag']}.json",
            "Medium", f"FY{rg['latest_fy']}: {rg['prior_val']:,} -> {rg['latest_val']:,} ({rg['tag']}).")
    else:
        out["revenue_growth_yoy_pct"] = none_field("Fewer than 2 annual 10-K revenue data points found on SEC EDGAR XBRL for this CIK (common for recent IPOs/spin-offs or filers using an uncommon revenue tag).")

    try:
        pm = profit_margin(cik)
    except Exception:
        pm = None
    if pm:
        out["profit_margin_pct"] = field(
            pm["margin_pct"], SEC_SOURCE_NAME,
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{pm['revenue_tag']}.json",
            "Medium", f"FY end {pm['fiscal_year_end']}: net income {pm['net_income']:,} / revenue {pm['revenue']:,}.")
    else:
        out["profit_margin_pct"] = none_field("No matching fiscal-year-end pair of revenue and net income data found on SEC EDGAR XBRL for this CIK.")

    try:
        dte = debt_to_equity(cik)
    except Exception:
        dte = None
    if dte:
        out["debt_to_equity_ratio"] = field(
            dte["debt_to_equity"], SEC_SOURCE_NAME,
            f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/Liabilities.json",
            "Medium", f"As of {dte['as_of']}: liabilities {dte['liabilities']:,} / equity {dte['equity']:,}.")
    else:
        out["debt_to_equity_ratio"] = none_field("Liabilities and/or StockholdersEquity XBRL data not found on SEC EDGAR for this CIK.")

    try:
        fcf = free_cash_flow_margin(cik)
    except Exception:
        fcf = None
    if fcf:
        notes = f"FY end {fcf['fiscal_year_end']}: OCF {fcf['operating_cash_flow']:,}"
        notes += f" - capex {fcf['capex']:,}" if not fcf["capex_missing"] else " (capex tag not found, using OCF alone)"
        notes += f" / revenue {fcf['revenue']:,}."
        out["free_cash_flow_margin_pct"] = field(fcf["fcf_margin_pct"], SEC_SOURCE_NAME,
                                                   f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/NetCashProvidedByUsedInOperatingActivities.json",
                                                   "Medium", notes)
    else:
        out["free_cash_flow_margin_pct"] = none_field("No matching fiscal-year-end pair of revenue and operating-cash-flow data found on SEC EDGAR XBRL for this CIK.")

    return out


def unavailable_metrics():
    return {k: none_field(v) for k, v in _UNAVAILABLE_NOTES.items()}


def load():
    with open(DATA_PATH) as f:
        return json.load(f)


def save(dataset):
    save_json(DATA_PATH, dataset)


def main():
    force = "--force" in sys.argv
    dataset = load()
    gh = get_github_financials_dataset()
    print(f"{len(dataset)} companies loaded; {len(gh)} rows in GitHub financials CSV.", flush=True)

    processed = 0
    gh_matched = 0
    for i, rec in enumerate(dataset):
        if not force and "financial_metrics" in rec:
            continue

        ticker = rec["ticker"]
        cik = rec.get("cik")
        corp_action = bool((rec.get("recent_corporate_action_flag") or {}).get("value"))

        row = gh.get(_normalize_github_ticker(ticker))
        if row:
            gh_matched += 1
            metrics = github_metrics(row)
        else:
            metrics = github_none_metrics(
                f"Ticker '{ticker}' not present in the GitHub financials dataset (a daily-refreshed but sometimes-lagging S&P 500 constituent list) -- likely a recent index addition or a symbol-format mismatch; see logs/manual_review_needed.md.")

        metrics.update(sec_metrics(cik, corp_action))
        metrics.update(unavailable_metrics())

        rec["financial_metrics"] = metrics
        processed += 1

        if (processed % CHECKPOINT_EVERY) == 0:
            save(dataset)
            print(f"[{i + 1}/{len(dataset)}] checkpoint saved | {processed} processed this run | {gh_matched} GitHub-CSV matches so far", flush=True)

    save(dataset)
    print(f"Done. {processed} companies processed this run ({gh_matched} matched the GitHub financials CSV).", flush=True)


if __name__ == "__main__":
    main()
