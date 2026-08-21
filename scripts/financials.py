"""Revenue growth / debt-to-equity / dividend-consistency from SEC EDGAR XBRL
companyconcept API. This is the fallback financial source now that Finnhub,
Alpha Vantage, and Stooq are all unavailable in this environment (see
logs/manual_review_needed.md) -- it can supply the revenue-growth half of
Growth Potential and the balance-sheet half of Stability, but NOT beta or
5-year total return, which need price history."""
from lib import get_company_concept


from datetime import date


def _is_annual_duration(fact):
    start, end = fact.get("start"), fact.get("end")
    if not start or not end:
        return True  # instant facts (balance sheet items) have no 'start'
    try:
        d1 = date.fromisoformat(start)
        d2 = date.fromisoformat(end)
    except ValueError:
        return False
    return 340 <= (d2 - d1).days <= 390


def _annual_10k_points(concept_json, unit="USD"):
    if not concept_json:
        return []
    units = concept_json.get("units", {})
    facts = units.get(unit, [])
    pts = [f for f in facts if f.get("form") == "10-K" and f.get("fp") == "FY" and _is_annual_duration(f)]
    pts.sort(key=lambda f: (f.get("end", ""), f.get("filed", "")))
    deduped = {}
    for p in pts:
        deduped[p.get("end")] = p  # last (most recently filed) wins for a given period-end
    return sorted(deduped.values(), key=lambda f: f.get("end", ""))


_REVENUE_TAGS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]


def _best_revenue_points(cik):
    """Companies switch which XBRL revenue tag they file under over time --
    most commonly "Revenues" -> "RevenueFromContractWithCustomerExcludingAssessedTax"
    when adopting ASC 606 (~2018). Trying tags in a fixed priority order and
    stopping at the first one with >=2 points is a real bug: "Revenues" often
    still has old data (Apple: last point 2018-09-29) that's older than what
    "RevenueFromContractWithCustomerExcludingAssessedTax" has (Apple: last
    point 2025-09-27), so a first-match strategy would silently report 2018
    figures as "the latest year" -- found producing a genuinely wrong growth
    percentage in the already-deployed growth_potential field. Checks every
    tag and returns whichever has the most recent latest-period end date."""
    best = None
    best_tag = None
    for tag in _REVENUE_TAGS:
        cc = get_company_concept(cik, "us-gaap", tag)
        pts = _annual_10k_points(cc)
        if pts and (best is None or pts[-1]["end"] > best[-1]["end"]):
            best, best_tag = pts, tag
    return best, best_tag


def revenue_growth(cik):
    pts, tag = _best_revenue_points(cik)
    if not pts or len(pts) < 2:
        return None
    latest, prior = pts[-1], pts[-2]
    if prior["val"] == 0:
        return None
    growth_pct = round((latest["val"] - prior["val"]) / abs(prior["val"]) * 100, 2)
    return {
        "growth_pct": growth_pct,
        "latest_fy": latest.get("fy"),
        "latest_val": latest["val"],
        "prior_val": prior["val"],
        "tag": tag,
    }


def debt_to_equity(cik):
    liab = get_company_concept(cik, "us-gaap", "Liabilities")
    eq = get_company_concept(cik, "us-gaap", "StockholdersEquity")
    liab_pts = _annual_10k_points(liab)
    eq_pts = _annual_10k_points(eq)
    if not liab_pts or not eq_pts:
        return None
    l = liab_pts[-1]
    e = eq_pts[-1]
    if e["val"] == 0:
        return None
    return {
        "debt_to_equity": round(l["val"] / e["val"], 2),
        "as_of": l.get("end"),
        "liabilities": l["val"],
        "equity": e["val"],
    }


def dividend_consistency(cik):
    cc = get_company_concept(cik, "us-gaap", "CommonStockDividendsPerShareDeclared")
    pts = _annual_10k_points(cc, unit="USD/shares")
    if not pts:
        return None
    recent = pts[-5:]
    paid_years = [p for p in recent if p.get("val", 0) > 0]
    return {
        "years_checked": len(recent),
        "years_paid": len(paid_years),
        "latest_dividend_per_share": recent[-1]["val"] if recent else None,
    }


def profit_margin(cik):
    """Net income / revenue for the most recent full fiscal year, both from
    the same 10-K so they're always a matched pair."""
    revenue_cc, revenue_tag = _best_revenue_points(cik)
    if not revenue_cc:
        return None
    net_income_cc = get_company_concept(cik, "us-gaap", "NetIncomeLoss")
    ni_pts = _annual_10k_points(net_income_cc)
    if not ni_pts:
        return None
    # Match by fiscal-year-end date, not just "latest" independently for each --
    # a company that just changed fiscal year end could otherwise pair a FY2025
    # revenue figure with a stub-period net income figure.
    rev_by_end = {p["end"]: p for p in revenue_cc}
    ni_by_end = {p["end"]: p for p in ni_pts}
    common_ends = sorted(set(rev_by_end) & set(ni_by_end))
    if not common_ends:
        return None
    end = common_ends[-1]
    rev, ni = rev_by_end[end], ni_by_end[end]
    if rev["val"] == 0:
        return None
    return {
        "margin_pct": round(ni["val"] / rev["val"] * 100, 2),
        "fiscal_year_end": end,
        "net_income": ni["val"],
        "revenue": rev["val"],
        "revenue_tag": revenue_tag,
    }


def free_cash_flow_margin(cik):
    """(Operating cash flow - capex) / revenue for the most recent full
    fiscal year. capex is best-effort across the two common XBRL tags for
    it; if neither is present, falls back to operating-cash-flow margin
    alone with that noted explicitly by the caller (capex missing is common
    for asset-light/services companies that don't break it out)."""
    revenue_cc, revenue_tag = _best_revenue_points(cik)
    if not revenue_cc:
        return None
    ocf_cc = get_company_concept(cik, "us-gaap", "NetCashProvidedByUsedInOperatingActivities")
    ocf_pts = _annual_10k_points(ocf_cc)
    if not ocf_pts:
        return None
    capex_pts = []
    for tag in ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForCapitalImprovements"]:
        cc = get_company_concept(cik, "us-gaap", tag)
        pts = _annual_10k_points(cc)
        if pts:
            capex_pts = pts
            break
    rev_by_end = {p["end"]: p for p in revenue_cc}
    ocf_by_end = {p["end"]: p for p in ocf_pts}
    capex_by_end = {p["end"]: p for p in capex_pts}
    common_ends = sorted(set(rev_by_end) & set(ocf_by_end))
    if not common_ends:
        return None
    end = common_ends[-1]
    rev, ocf = rev_by_end[end], ocf_by_end[end]
    capex = capex_by_end.get(end)
    if rev["val"] == 0:
        return None
    fcf = ocf["val"] - (capex["val"] if capex else 0)
    return {
        "fcf_margin_pct": round(fcf / rev["val"] * 100, 2),
        "fiscal_year_end": end,
        "operating_cash_flow": ocf["val"],
        "capex": capex["val"] if capex else None,
        "revenue": rev["val"],
        "capex_missing": capex is None,
    }
