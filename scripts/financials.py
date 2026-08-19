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


def revenue_growth(cik):
    for tag in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]:
        cc = get_company_concept(cik, "us-gaap", tag)
        pts = _annual_10k_points(cc)
        if len(pts) >= 2:
            latest, prior = pts[-1], pts[-2]
            if prior["val"] != 0:
                growth_pct = round((latest["val"] - prior["val"]) / abs(prior["val"]) * 100, 2)
                return {
                    "growth_pct": growth_pct,
                    "latest_fy": latest.get("fy"),
                    "latest_val": latest["val"],
                    "prior_val": prior["val"],
                    "tag": tag,
                }
    return None


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
