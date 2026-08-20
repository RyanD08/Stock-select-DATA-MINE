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


def fec_get(url, params=None, timeout=60):
    """fec.gov bulk-download files are served from a redirect (www.fec.gov ->
    an official FEC-managed S3 bucket in GovCloud) -- allow_redirects follows
    that through, same as generic_get. The request originates at the
    approved www.fec.gov domain."""
    _throttle("fec", 0.5)
    r = requests.get(url, headers=GENERIC_HEADERS, params=params, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def ftc_get(url, params=None, timeout=25):
    _throttle("ftc", 0.7)
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


# Q21 countries of concern -- deliberately narrow to OFAC's comprehensively-
# sanctioned jurisdictions (the closest thing to an objective, sourced list of
# "countries of concern" rather than an editorial judgment call). Does NOT
# include countries under only sectoral/targeted sanctions (e.g. China) --
# see the field's own notes for that scoping caveat.
COUNTRIES_OF_CONCERN = ["Russia", "Iran", "North Korea", "Syria", "Cuba", "Belarus", "Venezuela"]
_SECTION_13R = re.compile(r"13\(r\)")
_OPERATIONAL_CONTEXT = re.compile(
    r"operations? in|subsidiary in|subsidiaries in|facilit(?:y|ies) in|employees? in|"
    r"interest in|distribution.{0,20}in|customers?.{0,20}in|revenue.{0,20}from|"
    r"conduct(?:ed|s)? business in|maintain(?:ed|s)? operations? in|manufactur\w* in|"
    r"business in|sales? in|joint venture in|plant(?:s)? in|office(?:s)? in",
    re.IGNORECASE)


def find_countries_of_concern(text):
    """Two-tier signal: (1) SEC Section 13(r) of the Exchange Act is a
    purpose-built mandatory disclosure item for any Iran- or Syria-related
    dealings (Iran Threat Reduction and Syria Human Rights Act) -- its
    presence is a high-confidence, high-precision hit, and its absence
    genuinely means no disclosable activity, not "not searched". (2) For
    the other OFAC-comprehensively-sanctioned countries, a country name is
    only counted if it sits within ~100 chars of real operational-presence
    language (subsidiary/facility/revenue/etc.), and is rejected if the
    same sentence-ish window also names two or more OTHER tracked
    countries (a strong sign of generic sanctions/export-control
    boilerplate listing multiple jurisdictions at once, not a specific
    operational claim about this one). Returns a dict {countries: [...],
    section_13r: bool, evidence: {country: snippet}} or None if nothing
    found."""
    countries_found = {}
    section_13r = bool(_SECTION_13R.search(text))
    for country in COUNTRIES_OF_CONCERN:
        for m in re.finditer(r"\b" + re.escape(country) + r"\b", text):
            window_start = max(0, m.start() - 100)
            window = text[window_start:m.end() + 100]
            if not _OPERATIONAL_CONTEXT.search(window):
                continue
            other_country_count = sum(
                1 for c in COUNTRIES_OF_CONCERN
                if c != country and re.search(r"\b" + re.escape(c) + r"\b", window)
            )
            if other_country_count >= 2:
                continue
            countries_found[country] = text[max(0, m.start() - 60):m.end() + 60].strip()
            break
    if not countries_found and not section_13r:
        return None
    return {
        "countries": sorted(countries_found.keys()),
        "section_13r": section_13r,
        "evidence": countries_found,
    }


_NAME_CHARS = r"A-Za-zÀ-ÖØ-öø-ÿ'’"
_CEO_NAME_TITLE = re.compile(
    r"\b([A-Z][" + _NAME_CHARS + r".-]+(?:\s+[A-Z]\.?)?\s+[A-Z][" + _NAME_CHARS + r"-]+)\s*,?\s+"
    r"(?:(?:our |the Company's )?(?:Chair(?:man|woman)?(?:\s+of\s+the\s+Board)?(?:\s+and\s+|,\s*)|President(?:\s+and\s+|,\s*))*"
    r"(?:Chief Executive Officer|CEO)\b)")
_HONORIFIC_SURNAME = re.compile(r"\b(Mr|Ms|Mrs)\.\s*[ \s]?([A-Z][" + _NAME_CHARS + r"-]+)")
_CEO_NAME_STOPWORDS = {
    "company", "corporation", "corp", "group", "inc", "officer", "officers",
    "chairman", "chairwoman", "chair", "president", "retired", "public",
    "board", "committee", "compensation", "executive", "holdings",
    "registrant", "former", "interim", "named", "our", "the", "peer",
    "current", "acting", "outgoing", "incoming", "neo", "neos", "ceo", "cfo",
    "coo", "evp", "svp", "chief", "vice", "senior", "salary", "paid", "total",
    "director", "directors", "non-executive", "nonexecutive", "nominee",
    "nominees", "independent", "lead", "trustee",
}


def find_ceo_gender_signal(text):
    """Identifies the current CEO's surname from a name-immediately-before-
    title construction (e.g. "Mary T. Barra Chair and Chief Executive
    Officer", "Timothy D. Cook, CEO" -- the standard proxy-statement
    Summary Compensation Table / bio format), then reads which honorific
    (Mr./Ms./Mrs.) the filing itself consistently uses for that exact
    surname elsewhere in the document. This is a gendered reference the
    filing itself makes about a specific named person -- it never guesses
    gender from a first name. Requires every honorific found for that
    surname to agree, and at least 2 supporting occurrences, before
    returning a signal. Returns (is_woman: bool, surname, evidence_snippet)
    or None if no consistent CEO-name/honorific pairing was found."""
    from collections import Counter
    text = text.replace("\xa0", " ")  # BeautifulSoup's get_text() leaves non-breaking
    # spaces inside a single text node un-joined, which otherwise breaks literal-space
    # matches inside multi-word titles like "Chief Executive Officer".
    name_hits = Counter()
    surname_display = {}
    chair_tagged = set()
    for m in _CEO_NAME_TITLE.finditer(text):
        full_name = m.group(1).strip()
        tokens = full_name.split()
        surname = tokens[-1].strip(".,’'")
        first = tokens[0].strip(".,’'")
        if surname.lower() in _CEO_NAME_STOPWORDS or first.lower() in _CEO_NAME_STOPWORDS:
            continue
        key = surname.lower()
        name_hits[key] += 1
        surname_display.setdefault(key, surname)
        if re.search(r"chair", m.group(0), re.IGNORECASE):
            chair_tagged.add(key)
    if not name_hits:
        return None
    # Some companies (e.g. P&G) use "Chief Executive Officer" as an internal
    # title for multiple business-segment heads, not just the single overall
    # corporate CEO -- pure mention-frequency can pick the wrong one. A
    # "Chair(man/woman) ... CEO" combined title is a much stronger signal of
    # being THE company's top executive (segment heads are essentially never
    # also Board Chair), so prefer a uniquely chair-tagged candidate over raw
    # frequency; only fall back to plurality-by-frequency when that signal is
    # absent or itself ambiguous (multiple chair-tagged candidates).
    # A single stray mention -- e.g. an outside director's bio quoting their
    # own CEO title *at a different company* (a board bio table lists Mary
    # Barra as "Chair and Chief Executive Officer" in every proxy she's a
    # director of, not just GM's) -- must never win just for being
    # chair-tagged. Only trust the chair-tag signal when that candidate is
    # independently a real, repeated presence in this filing (>=2 mentions,
    # the same bar the raw-frequency path requires).
    qualifying_chair = {k for k in chair_tagged if name_hits[k] >= 2}
    candidates = name_hits
    if len(qualifying_chair) == 1:
        ceo_key = next(iter(qualifying_chair))
    else:
        if qualifying_chair:
            candidates = Counter({k: v for k, v in name_hits.items() if k in qualifying_chair})
        top_two = candidates.most_common(2)
        top_key, top_count = top_two[0]
        # A single name+title adjacency match is too weak to trust on its own --
        # it's just as likely to be an incidental "...previously served as CEO
        # of X" in someone else's bio as the real, current CEO. Require the top
        # candidate to clearly lead (not tie) a second-place name before using it.
        if top_count < 2 or (len(top_two) > 1 and top_two[1][1] >= top_count):
            return None
        ceo_key = top_key
    ceo_surname = surname_display[ceo_key]

    honorific_hits = Counter()
    evidence = None
    for m in _HONORIFIC_SURNAME.finditer(text):
        honorific, surname = m.group(1), m.group(2)
        if surname.lower() != ceo_key:
            continue
        gender = "female" if honorific in ("Ms", "Mrs") else "male"
        honorific_hits[gender] += 1
        if evidence is None:
            start = max(0, m.start() - 40)
            evidence = text[start:m.end() + 60].strip()
    if honorific_hits and sum(honorific_hits.values()) >= 2 and len(honorific_hits) == 1:
        is_woman = next(iter(honorific_hits)) == "female"
        return (is_woman, ceo_surname, evidence)

    # Fallback: some proxies never use Mr./Ms. (a stylistic choice, e.g. AMD
    # uses "Dr. Su" throughout, which is gender-neutral) but still describe
    # the CEO with a gendered pronoun in their own bio narrative ("Dr. Su
    # has served ... She has served ..."). Look at the text immediately
    # following each mention of the CEO's surname, stopping early at the
    # next capitalized full name (another person) to avoid picking up a
    # pronoun that refers to someone else.
    pronoun_hits = Counter()
    evidence = None
    surname_pat = re.compile(r"\b" + re.escape(ceo_surname) + r"\b")
    next_name_pat = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")
    pronoun_pat = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.IGNORECASE)
    for m in surname_pat.finditer(text):
        window_end = m.end() + 250
        # Find the next capitalized-name-like token, skipping a repeat of
        # the CEO's own name (e.g. "Carol Tomé ... Carol Tomé is..."),
        # which would otherwise truncate the window before any pronoun.
        search_from = m.end() + 1
        for _ in range(4):
            next_name = next_name_pat.search(text, search_from)
            if not next_name or next_name.start() >= window_end:
                break
            if ceo_surname.lower() in next_name.group(0).lower():
                search_from = next_name.end()
                continue
            window_end = next_name.start()
            break
        window = text[m.end():window_end]
        p = pronoun_pat.search(window)
        if not p:
            continue
        gender = "female" if p.group(1).lower() in ("she", "her", "hers", "herself") else "male"
        pronoun_hits[gender] += 1
        if evidence is None:
            evidence = text[m.start():m.end() + p.end()].strip()
    total = sum(pronoun_hits.values())
    if total < 2:
        return None
    (top_gender, top_count) = pronoun_hits.most_common(1)[0]
    # Pronoun windows are noisier than honorific matches (a nearby sentence
    # can describe someone else), so require a strong majority rather than
    # unanimity -- a single stray opposite-gender pronoun among many
    # shouldn't erase an otherwise consistent signal.
    if top_count / total < 0.85:
        return None
    is_woman = top_gender == "female"
    return (is_woman, ceo_surname, evidence)


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


# ---------------------------------------------------------------- FEC (Q20 political donations)
#
# fec.gov's bulk-download files give real, filed committee-level data: the
# committee master file (cm) lists each PAC's officially reported sponsoring
# organization (CONNECTED_ORG_NM) and designation, and the committee summary
# file gives per-committee financial totals for the cycle. This is a much
# stronger signal than the DEF 14A keyword scan (a real named/registered PAC
# with dollar totals vs. a proxy-statement sentence merely mentioning
# "political contributions"), so an FEC match is scored High confidence.
#
# Matching a company to its PAC(s) is name-matching against CONNECTED_ORG_NM
# (FEC's own structured field) or, failing that, the committee's own name
# with PAC boilerplate stripped -- both restricted to committees with
# ORG_TP == "C" (Corporation) and CMTE_DSGN == "B" (Lobbyist/Registrant PAC).
# That restriction was found necessary during testing: without it, several
# single-word company names (e.g. "Cooper Companies" -> "COOPER", "Progressive
# Corporation" -> "PROGRESSIVE") false-matched unrelated candidate leadership
# PACs whose CONNECTED_ORG_NM field happened to be a person's surname
# ("COOPER", "LIEU", "WATERS") -- those leadership PACs have CMTE_DSGN "D"
# and a blank ORG_TP, so filtering to ORG_TP == "C" / CMTE_DSGN == "B"
# (genuine corporate PACs only) eliminates that false-positive class. Even
# with this restriction, matching is by name only (FEC does not publish a
# CIK crosswalk) -- exact match only, no fuzzy/prefix matching, since a
# prefix-match test run produced a real false positive (D.R. Horton
# incorrectly matched to a Teamsters "D R I V E" committee via a shared
# two-token prefix).
FEC_CYCLE = "2024"  # most recently *completed* even-year cycle as of 2026-08-20;
# preferred over the in-progress 2026 cycle for stable, full-cycle financial totals.

FEC_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "companies",
    "llc", "ltd", "limited", "plc", "holdings", "holding", "the", "na",
}

_FEC_PAC_NOISE_PHRASES = [
    r"\bfederal political action committee\b", r"\bpolitical action committee\b",
    r"\bseparate segregated fund\b", r"\bnonpartisan political action committee\b",
    r"\bgood government fund\b", r"\bgood government committee\b", r"\bgood government club\b",
    r"\bemployees political action committee\b", r"\bemployees pac\b", r"\bemployees fund\b",
    r"\bemployees' fund\b", r"\bcivic action committee\b", r"\bgovernment affairs\b",
    r"\bpolitical action fund\b", r"\baction fund\b", r"\baction committee\b",
    r"\bpolitical fund\b", r"\bconcerned citizens fund\b", r"\bcitizens for \b",
    r"\bemployees\b", r"\bemployee\b", r"\bassociates\b", r"\bpac\b",
]


def _fec_normalize(name):
    name = name.upper().replace("&", " AND ")
    name = re.sub(r"[.,'’]", "", name)
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    return [t for t in name.split() if t.lower() not in FEC_SUFFIXES]


def _fec_norm_str(name):
    return " ".join(_fec_normalize(name))


def _fec_cmte_candidate_name(cmte_nm):
    s = re.sub(r"\([^)]*\)", " ", cmte_nm).lower()
    for pat in _FEC_PAC_NOISE_PHRASES:
        s = re.sub(pat, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _fec_norm_str(s)


_fec_committee_index = None  # {"org": {...}, "cmte": {...}} -- lazily built once per process


def _load_fec_committee_master():
    url = f"https://www.fec.gov/files/bulk-downloads/{FEC_CYCLE}/cm{FEC_CYCLE[2:]}.zip"
    r = fec_get(url)
    import io
    import zipfile
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    name = [n for n in zf.namelist() if n.lower().endswith(".txt")][0]
    text = zf.read(name).decode("latin-1")

    org_index, cmte_index = {}, {}
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 14:
            continue
        cmte_id, cmte_nm = parts[0], parts[1]
        cmte_dsgn, cmte_tp = parts[8], parts[9]
        org_tp = parts[12]
        connected_org = parts[13]
        if cmte_tp not in ("Q", "N", "O", "V", "W"):
            continue
        if org_tp != "C" or cmte_dsgn != "B":
            continue  # genuine corporate-sponsored PACs only -- see module note above
        if connected_org.strip():
            org_index.setdefault(_fec_norm_str(connected_org), []).append((cmte_id, cmte_nm, connected_org))
        cand = _fec_cmte_candidate_name(cmte_nm)
        if cand:
            cmte_index.setdefault(cand, []).append((cmte_id, cmte_nm, connected_org))
    return {"org": org_index, "cmte": cmte_index}


def _load_fec_committee_summary():
    url = f"https://www.fec.gov/files/bulk-downloads/{FEC_CYCLE}/committee_summary_{FEC_CYCLE}.csv"
    r = fec_get(url)
    import csv
    import io
    reader = csv.DictReader(io.StringIO(r.text))
    by_cmte = {}
    for row in reader:
        by_cmte[row["CMTE_ID"]] = row
    return by_cmte


def get_fec_committee_index():
    global _fec_committee_index
    if _fec_committee_index is None:
        _fec_committee_index = {
            "master": _load_fec_committee_master(),
            "summary": _load_fec_committee_summary(),
        }
    return _fec_committee_index


def match_company_to_fec_pac(company_name):
    """Returns a list of (cmte_id, cmte_nm, connected_org, summary_row_or_None)
    for the company's matched corporate PAC(s), or None if no exact match."""
    idx = get_fec_committee_index()
    master, summary = idx["master"], idx["summary"]
    key = _fec_norm_str(company_name)
    if not key:
        return None
    hit = master["org"].get(key) or master["cmte"].get(key)
    if not hit:
        return None
    return [(cmte_id, cmte_nm, connected_org, summary.get(cmte_id))
            for cmte_id, cmte_nm, connected_org in hit]


# ---------------------------------------------------------------- FTC (Q11 fraud/corruption)
#
# ftc.gov's Legal Library case search (a real server-rendered HTML results
# page, not JS-only) supplements the existing SEC-full-text-search signal for
# Q11 with named FTC enforcement actions. The site's own search matches on
# full text, not just party name, so results are filtered down to items whose
# URL has the numeric case-docket prefix real cases use (category/menu pages
# like "commissioner-statements" or "petitions-quash" don't) AND whose title
# text contains the company's own name -- both checks are needed; verified
# against a real "Amazon" search that otherwise pulled in unrelated cases
# (e.g. "Lights of America", "Sellers Playbook") sharing only incidental
# keyword overlap with the query.
def cybersecurity_incident_search(cik, max_examples=5):
    """Q22 data privacy: searches EDGAR full-text search, scoped to this
    company's own CIK, for 8-K filings disclosing Item 1.05 ("Material
    Cybersecurity Incidents") -- the SEC rule effective December 2023
    requiring public companies to disclose a material cybersecurity
    incident within four business days. Unlike a name-matched search
    across all filers, this is scoped to the company's own CIK, so a zero
    result is a real, meaningful answer (no such 8-K filed) rather than a
    failed name-match -- though it only covers incidents from December
    2023 onward, since the item didn't exist before that. Returns
    {incident_count, examples, search_url} or None if the search itself
    failed (never for a genuine zero)."""
    try:
        result = full_text_search("Item 1.05", forms="8-K", ciks=cik)
    except Exception:
        return None
    # The query above is a plain full-text match, which also catches a
    # filing that merely contains the literal string "Item 1.05" somewhere
    # unrelated (e.g. a numbered contract clause in an exhibit) -- confirmed
    # by two false positives in testing, including one filed in 2005, two
    # decades before Item 1.05 (cybersecurity incidents) existed as an 8-K
    # item. EDGAR's search index separately tags each filing with its real,
    # structured item codes, so only trust a hit whose own "items" field
    # actually contains "1.05".
    hits = [h for h in result.get("hits", {}).get("hits", [])
            if "1.05" in (h.get("_source", {}).get("items") or [])]
    examples = []
    for h in hits[:max_examples]:
        src = h.get("_source", {})
        examples.append({
            "filed": src.get("file_date"),
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0') or '0'}/{src.get('adsh', '').replace('-', '')}/{h.get('_id', '').split(':')[-1]}",
        })
    return {
        "incident_count": len(hits), "examples": examples,
        "search_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K",
    }


_FTC_CASE_HREF = re.compile(r'href="(/legal-library/browse/cases-proceedings/\d[^"]*)"[^>]*>([^<]+)<')


def ftc_case_search(company_name, max_examples=5):
    url = "https://www.ftc.gov/legal-library/browse/cases-proceedings"
    r = ftc_get(url, params={"search": company_name})
    html = r.text
    # Require the first TWO significant (non-suffix) tokens of the company name,
    # when there are that many, to both appear as whole words in the case title --
    # matching on a single leading word is too generic (e.g. "Home Depot (The)"'s
    # first token alone is "HOME", which false-matched "Home Matters USA" and
    # "Vivint Smart Home, Inc." in testing). Single-word company names fall back
    # to that one word, guarded by the same length/digit heuristic as before.
    sig_tokens = [t for t in _fec_normalize(company_name) if t not in ("AND", "OF", "FOR")]
    seen_tok = set()
    sig_tokens = [t for t in sig_tokens if not (t in seen_tok or seen_tok.add(t))]  # dedupe, preserve order
    if not sig_tokens:
        return None
    match_tokens = sig_tokens[:2]
    if len(match_tokens) == 1 and len(match_tokens[0]) < 3 and not re.search(r"\d", match_tokens[0]):
        return None  # too generic/short a token to safely word-match (unless it's distinctive like "3M")
    token_patterns = [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in match_tokens]
    seen = set()
    hits = []
    for m in _FTC_CASE_HREF.finditer(html):
        href, title = m.group(1), m.group(2).strip()
        if href in seen:
            continue
        if all(p.search(title) for p in token_patterns):
            seen.add(href)
            hits.append({"title": title, "url": f"https://www.ftc.gov{href}"})
    if not hits:
        return None
    return {"case_count": len(hits), "examples": hits[:max_examples], "search_url": f"{url}?search={company_name}"}


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    import os
    os.replace(tmp, path)
