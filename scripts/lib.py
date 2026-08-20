"""Shared helpers for the TrueNorth S&P 500 dataset pipeline.
Restricted to the approved source list. Every fetch function returns data
plus enough provenance (source name + URL) to populate a scored field."""
import json
import re
import time
from datetime import datetime, timezone

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

UA = "TrueNorth-DataMine/1.0 (research@truenorth.example; contact ryan.delp08@gmail.com)"
SEC_HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
GENERIC_HEADERS = {"User-Agent": UA}

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

_last_call = {}


def _throttle(bucket, min_interval):
    now = time.monotonic()
    last = _last_call.get(bucket, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[bucket] = time.monotonic()


def sec_get(url, params=None, timeout=25):
    _throttle("sec", 0.15)
    r = requests.get(url, headers=SEC_HEADERS, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def epa_get(url, params=None, timeout=25):
    _throttle("epa", 1.0)
    r = requests.get(url, headers=GENERIC_HEADERS, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def osha_get(url, params=None, timeout=25):
    _throttle("osha", 1.0)
    r = requests.get(url, headers=GENERIC_HEADERS, params=params, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def generic_get(url, params=None, timeout=25):
    _throttle("generic", 0.7)
    r = requests.get(url, headers=GENERIC_HEADERS, params=params, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def field(value, source, source_url, confidence, notes=None):
    return {
        "value": value,
        "source": source,
        "source_url": source_url,
        "confidence": confidence,
        "notes": notes,
        "last_updated": TODAY,
    }


def none_field(source_note=None):
    return field("No verifiable data found", None, None, "None", source_note)


# ---------------------------------------------------------------- SEC EDGAR

def get_submissions(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return sec_get(url).json()


def get_company_concept(cik, taxonomy, tag):
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
    try:
        r = sec_get(url)
        return r.json()
    except requests.HTTPError:
        return None


def full_text_search(query, forms=None, ciks=None, timeout=25):
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {"q": f'"{query}"'}
    if forms:
        params["forms"] = forms
    if ciks:
        params["ciks"] = ciks
    r = sec_get(url, params=params, timeout=timeout)
    return r.json()


def latest_filing(submissions, form_type):
    recent = submissions["filings"]["recent"]
    forms = recent["form"]
    for i, f in enumerate(forms):
        if f == form_type:
            return {
                "accession": recent["accessionNumber"][i],
                "primary_doc": recent["primaryDocument"][i],
                "filing_date": recent["filingDate"][i],
            }
    return None


def filing_document_url(cik_no_padding, accession, primary_doc):
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik_no_padding)}/{acc_nodash}/{primary_doc}"


def fetch_filing_text(url, max_chars=600000):
    r = sec_get(url, timeout=40)
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return text[:max_chars]


# ---------------------------------------------------------------- SIC screens

TOBACCO_SIC = {"2100", "2111", "2121", "2131", "2141"}
ALCOHOL_SIC = {"2082", "2083", "2084", "2085"}  # NOT 2080 -- SEC EDGAR assigns the generic
# "2080 Beverages" code to soft-drink makers (Coca-Cola, PepsiCo, Keurig Dr Pepper) just as
# often as to alcohol producers (Constellation Brands, Brown-Forman); it does not reliably
# distinguish the two. SIC-2080 registrants need a business-description keyword check instead
# -- see ALCOHOL_2080_KEYWORDS and its use in process_batch.py.
ALCOHOL_2080_KEYWORDS = ["wine", "beer", "brewery", "brewing", "spirits", "distilled", "vodka",
                          "whiskey", "whisky", "rum ", "tequila", "bourbon", "alcoholic beverage"]
GAMBLING_SIC = {"7993"}  # 7990 ("Amusement & Recreation, NEC") is too broad -- it's also Disney's own
# SIC code (theme parks), not a gambling-specific classification. 7993 (Coin-Operated
# Amusement Devices) is closer but still imperfect for pure-play casino operators, who
# are often coded under Hotels (7011) instead -- see notes on this field's confidence.
WEAPONS_SIC = {"3480", "3483", "3484", "3489", "3760", "3761", "3764", "3769", "3795", "3489"}
FINANCE_LENDING_SIC = {str(x) for x in list(range(6000, 6100)) + list(range(6100, 6200)) + [6712, 6199, 6159, 6141, 6162, 6022, 6020, 6035, 6036]}


def sic_screen(sic_code):
    sic = str(sic_code).zfill(4) if sic_code else None
    return {
        "tobacco": sic in TOBACCO_SIC,
        "alcohol": sic in ALCOHOL_SIC,
        "gambling": sic in GAMBLING_SIC,
        "weapons": sic in WEAPONS_SIC,
        "interest_based_finance": sic in FINANCE_LENDING_SIC,
    }


# ---------------------------------------------------------------- EPA ECHO

def epa_echo_summary(company_name):
    url = "https://echodata.epa.gov/echo/echo_rest_services.get_facilities"
    params = {"output": "JSON", "p_fn": company_name}
    try:
        r = epa_get(url, params=params)
        data = r.json()
        results = data.get("Results", {})
        if "Error" in results:
            return None
        return results
    except Exception:
        return None


# ---------------------------------------------------------------- OSHA

def osha_establishment_search(company_name):
    url = "https://www.osha.gov/ords/imis/establishment.search"
    params = {"p_logger": 1, "establishment": company_name, "State": "All", "officetype": "All", "Industry": "All"}
    try:
        r = osha_get(url, params=params)
        soup = BeautifulSoup(r.text, "lxml")
        tables = soup.find_all("table", class_="table")
        if not tables:
            return None
        rows = tables[0].find_all("tr")
        data_rows = [tr for tr in rows if tr.find("td")]
        return {"row_count": len(data_rows), "source_url": r.url}
    except Exception:
        return None


# ---------------------------------------------------------------- keyword scan helpers

ENV_KEYWORDS = {
    "fossil_fuel": ["oil and gas", "coal", "petroleum", "fossil fuel", "crude oil", "natural gas exploration"],
    "renewable": ["renewable energy", "solar", "wind power", "clean energy", "clean technology", "decarbonization", "electric vehicle"],
    "sustainable_ag": ["sustainable agriculture", "regenerative agriculture", "responsible sourcing", "sustainable forestry", "water stewardship"],
}
LABOR_KEYWORDS = {
    "fair_wages": ["living wage", "fair wage", "supplier code of conduct", "responsible sourcing"],
    "dei": ["diversity, equity and inclusion", "diversity, equity, and inclusion", "workplace diversity", "inclusion and diversity"],
    "labor_dispute": ["labor dispute", "strike", "unionization", "collective bargaining", "work stoppage"],
}
GOV_KEYWORDS = {
    "dual_class": ["class a common stock", "class b common stock", "ten votes per share", "super-voting"],
}

# Requires completion language, not a bare mention of "merger"/"acquisition" --
# those words appear as generic risk-factor/strategy boilerplate in nearly
# every 10-K regardless of whether anything actually happened.
RECENT_CORPORATE_ACTION_PATTERN = re.compile(
    r"(completed (?:the |its )?(merger|acquisition|spin-?off|separation|business combination)|"
    r"(merger|acquisition|spin-?off|separation|business combination)[^.]{0,60}?(?:was|were) completed|"
    r"\bspun off\b|became an? (?:new |newly )?(?:independent |standalone )?public(?:ly traded)? company)")


def keyword_hit(text_lower, keywords):
    return any(k in text_lower for k in keywords)


def alcohol_2080_hit(text_lower):
    """Like keyword_hit(ALCOHOL_2080_KEYWORDS), but guards against the
    'nonalcoholic beverage' substring trap -- 'alcoholic beverage' is a
    literal substring of 'nonalcoholic beverage', which flagged Coca-Cola
    (whose 10-K explicitly defines its trademark beverages as nonalcoholic)
    as an alcohol producer."""
    for kw in ALCOHOL_2080_KEYWORDS:
        for m in re.finditer(re.escape(kw), text_lower):
            if kw == "alcoholic beverage" and text_lower[max(0, m.start() - 3):m.start()] == "non":
                continue
            return True
    return False


def find_pay_ratio(text):
    patterns = [
        r"ratio[^.]{0,120}?is\s+(?:approximately\s+)?([\d,]{2,7})\s*(?:to|:)\s*1",
        r"pay ratio[^.]{0,300}?([\d,]{2,7})\s*(?:to|:)\s*1",
        r"([\d,]{2,7})\s*(?:to|:)\s*1[^.]{0,60}?pay ratio",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
                if 1 < val < 100000:
                    return val
            except ValueError:
                continue
    return None


_COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|corp|ltd|holdings|plc|lp|company|co|advisors?|partners?|"
    r"capital|ventures?|associates|management|group)\.?(?![a-z])")
_DATE_RANGE_PAREN = re.compile(r"^\s*\(\d{4}[\s\-–—]")  # e.g. "(2022-september 2024)" = a past role elsewhere
_PAST_TENSE = re.compile(r"previously served|no longer serves|from \d{4} to|from \w+ \d{4} to|until \d{4}|\bformer\b|\bretired\b")
_POSSESSIVE_PRECEDER = re.compile(r"([a-z]+)[’']s\s*$")
_SELF_REFERENCE_WORDS = {"company", "our", "registrant"}
_GENERIC_CRITERIA_PRECEDER = re.compile(
    r"(served as a|such as a|including a|including the|who have|criteria include)\s*$")
_FAMILY_BRAND_PHRASE = re.compile(r"^\s*of\s+(companies|brands|products|funds|restaurants|stores)\b", re.IGNORECASE)
_OWNERSHIP_CONTEXT = re.compile(r"beneficial(?:ly)?\s+own|voting power|\btrust\b|\bshares\b|%\s|percent", re.IGNORECASE)


def find_founder_led(text_lower):
    """Only counts a 'founder ... CEO/Executive Chairman' hit if: it isn't
    immediately followed by a different, named company (a classic false
    positive from director bios listing OTHER companies they founded); the
    matched span doesn't contain a second 'founder' mention (a sign this is
    a multi-person table/list where the founder and CEO titles belong to two
    different people, not one bio); and it isn't preceded by generic board-
    selection-criteria language ('directors who have served as a founder,
    CEO...') rather than an actual person's bio. This is still a flattened-
    text regex heuristic, not a structured read of the filing -- treat hits
    as Low confidence and spot-check before trusting."""
    for m in re.finditer(r"(founder|co-founder)[^.]{0,120}?(chief executive officer|executive chairman)", text_lower):
        span = text_lower[m.start():m.end()]
        if span.count("founder") > 1:
            continue
        preceding = text_lower[max(0, m.start() - 30):m.start()]
        if _GENERIC_CRITERIA_PRECEDER.search(preceding):
            continue
        poss = _POSSESSIVE_PRECEDER.search(preceding)
        if poss and poss.group(1) not in _SELF_REFERENCE_WORDS:
            continue
        middle = span[len(m.group(1)):-len(m.group(2))]  # text between "founder" and the CEO/chairman title itself
        if _COMPANY_SUFFIX.search(middle) or _PAST_TENSE.search(middle):
            continue
        trailing = text_lower[m.end():m.end() + 100]
        if _COMPANY_SUFFIX.search(trailing) or _DATE_RANGE_PAREN.match(trailing) or _PAST_TENSE.search(trailing):
            continue
        return text_lower[max(0, m.start() - 40):m.end() + 60]
    return None


def find_family_owned(text):
    """Requires the '<Name> family' mention to sit near real ownership
    language (beneficial ownership, voting power, trust, %) and rejects the
    common false positive of corporate brand phrasing like 'the X family of
    companies/brands/products'."""
    for m in re.finditer(r"the ([A-Z][a-z]+) family\b", text):
        after = text[m.end():m.end() + 30]
        if _FAMILY_BRAND_PHRASE.match(after):
            continue
        window = text[max(0, m.start() - 250):m.end() + 250]
        if _OWNERSHIP_CONTEXT.search(window):
            return m.group(0), window
    return None


def find_independent_directors_pct(text):
    m = re.search(r"(\d{1,3})\s*%\s*of[^.]{0,60}?independent", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{1,2})\s+of\s+(?:our\s+)?(\d{1,2})\s+director[s]?[^.]{0,60}?(?:is|are)\s+independent", text, re.IGNORECASE)
    if m2:
        n, d = int(m2.group(1)), int(m2.group(2))
        if d > 0:
            return round(n / d * 100)
    m3 = re.search(r"each of (?:our|the) directors[^.]{0,80}?(?:other than[^.]{0,60}?)?(?:is|are) independent", text, re.IGNORECASE)
    if m3:
        return None  # qualitative-only signal; caller should treat as a text hit, not a %
    return None


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    import os
    os.replace(tmp, path)
