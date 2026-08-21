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


_PAY_RATIO_PATTERNS = [
    # Primary: "the ratio of ... [compensation/median/employee] ... is/was/were ... N to 1" --
    # requires a compensation/median/employee word somewhere near "ratio" (so an unrelated
    # financial ratio, e.g. debt-to-equity, doesn't match) and allows filler between the
    # verb and the number ("is estimated to be", "was approximately") since real disclosures
    # use both "is" and "was" and rarely put the number immediately after the verb. Uses
    # `.` rather than `[^.]` for the character budget -- a bare `[^.]` stops dead at the
    # first "Mr." or "Ms." abbreviation, which appear constantly in these disclosures right
    # next to the ratio sentence (e.g. "the ratio of Mr. Stein's ... compensation ... was
    # 369:1"), and silently killed real matches in testing. DOTALL so `.` also crosses the
    # literal "\n" line-wrap characters BeautifulSoup sometimes leaves mid-sentence (e.g.
    # "Interim CEO's annual\ntotal compensation ... was 417 to 1") -- without it those
    # newlines acted as unintended hard stops and silently killed real matches too.
    re.compile(r"\bratio\b(?=.{0,150}?\b(?:compensation|median|employee)\b).{0,150}?"
               r"\b(?:is|was|were)\b.{0,60}?([\d,]+(?:\.\d+)?)\s*(?:to|:)\s*1\b", re.IGNORECASE | re.DOTALL),
    # Fallbacks for phrasing the primary pattern doesn't cover. Both need a trailing \b --
    # without it, a table presented in reversed "median:CEO" order (e.g. Valero's own
    # summary table: "Median Employee to CEO Pay Ratio 1:162") silently matched just the
    # leading "1" of "162" as if it were "...:1", producing a wrong value (1.0 instead of
    # the real 162) rather than either the right number or no match at all.
    re.compile(r"pay ratio.{0,300}?([\d,]+(?:\.\d+)?)\s*(?:to|:)\s*1\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:to|:)\s*1\b.{0,60}?pay ratio", re.IGNORECASE | re.DOTALL),
    # Reversed "median:CEO" table format (e.g. "Median Employee to CEO Pay Ratio 1:162") --
    # the leading "1" is the normalized median-employee value, the second number is the
    # real ratio.
    re.compile(r"median employee to ceo pay ratio\D{0,10}1\s*:\s*([\d,]+(?:\.\d+)?)\b", re.IGNORECASE),
    # "N times that of/the median employee" -- an equally common alternate phrasing that
    # never uses "to 1"/":1" at all (e.g. CF Industries: "...was approximately 88 times
    # that of our median employee").
    re.compile(r"\b(?:was|is)\b.{0,60}?\b(?:approximately\s+)?([\d,]+(?:\.\d+)?)\s+times\b"
               r".{0,80}?\b(?:median|employee)\b", re.IGNORECASE | re.DOTALL),
]


def find_pay_ratio(text):
    for pat in _PAY_RATIO_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                if 0 < val < 100000:
                    return val
            except ValueError:
                continue
    return None


_COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|corp|ltd|holdings|plc|lp|company|co|advisors?|partners?|"
    r"capital|ventures?|associates|management|group|therapeutics|systems|"
    r"health|technologies|global|labs?|studio|studios|strategies|ai)\.?(?![a-z])")
_DATE_RANGE_PAREN = re.compile(r"^\s*\(\d{4}[\s\-–—]")  # e.g. "(2022-september 2024)" = a past role elsewhere
_PAST_TENSE = re.compile(r"previously served|no longer serves|from \d{4} to|from \w+ \d{4} to|until \d{4}|\bformer\b|\bretired\b|transitioned from")
_POSSESSIVE_PRECEDER = re.compile(r"([a-z]+)[’']s\s*$")
_SELF_REFERENCE_WORDS = {"company", "our", "registrant"}
_GENERIC_CRITERIA_PRECEDER = re.compile(
    r"(served as a|such as a|including a|including the|who have|criteria include)\s*$")
_FAMILY_BRAND_PHRASE = re.compile(r"^\s*of\s+(companies|brands|products|funds|restaurants|stores)\b", re.IGNORECASE)
_OWNERSHIP_CONTEXT = re.compile(r"beneficial(?:ly)?\s+own|voting power|\btrust\b|\bshares\b|%\s|percent", re.IGNORECASE)
# A "<Name> family" mention near ownership language is at least as likely to be a large
# asset manager's own controlling family showing up in a Schedule 13D/G beneficial-
# ownership footnote (an SEC-mandated disclosure of who controls the *reporting*
# institution, not the registrant) as it is the registrant's own founding family --
# confirmed as a real false positive: "the Johnson family" (Abigail P. Johnson, FMR
# LLC/Fidelity's chairman and CEO) showing up as a beneficial-ownership footnote for
# three unrelated semiconductor companies (LITE, NXPI, ON) that Fidelity funds simply
# hold a large index/institutional position in.
_INSTITUTIONAL_OWNER_MARKERS = re.compile(
    r"\bfmr\b|\bfidelity\b|\bblackrock\b|\bvanguard\b|\bstate street\b|"
    r"\bcapital research\b|\bcapital world investors\b|\bt\.?\s*rowe price\b|"
    r"\bwellington management\b|\bcapital group\b|\bgeode capital\b|\bnorges bank\b",
    re.IGNORECASE)


def find_founder_led(text, company_name):
    """Identifies the current CEO and current Executive Chair (if any) by
    name via title-adjacency, then checks ONLY the neighborhood of each
    identified officer's own name for founder language. Anchoring to a
    specific, independently-identified officer -- rather than scanning the
    whole document for any 'founder ... CEO' phrase -- is what avoids
    matching an unrelated director's own bio blurb about a completely
    different company they separately founded: a near-universal modern
    'director skills highlights' bio pattern (e.g. Microsoft's board bio for
    Jeff Weiner, LinkedIn's co-founder, sitting a few sentences from
    Microsoft's actual CEO) that a whole-document scan has no way to tell
    apart from a genuine claim about this company's own leadership -- found
    producing false positives at scale (MSFT, GM, MCD, CVS, LLY, SO, CSX,
    MDLZ, HSY, MA, WSM all matched some OTHER director's unrelated outside
    venture, not the registrant's own founder-CEO/chair). Also recovers the
    dominant phrasing this replaced: a verb-form founding bio ("Jen-Hsun
    Huang founded NVIDIA in 1993 and has served since its inception as ...
    Chief Executive Officer") that the original noun-only pattern
    ("founder ... CEO") could never match at all. Still a flattened-text
    regex heuristic, not a structured read of the filing -- treat hits as
    Low confidence and spot-check before trusting."""
    text_lower = text.lower()
    company_key = _company_key(company_name)
    candidates = []
    ceo = _top_named_officer(text, _CEO_NAME_TITLE_FOUNDER_OK, company_key)
    if ceo:
        candidates.append(ceo)
    chair = _top_named_officer(text, _EXEC_CHAIR_NAME_TITLE, company_key)
    if chair and (not ceo or chair[1] != ceo[1]):
        candidates.append(chair)
    for full_name, surname in candidates:
        hit = _officer_founder_evidence(text, text_lower, surname, full_name, company_key)
        if hit:
            return f"{full_name}: {hit}"
    return None


def _company_key(company_name):
    """First alphabetic-ish token of the registrant's own name (e.g. 'Oracle'
    from 'Oracle Corporation', 'Meta' from 'Meta Platforms') -- used as a
    lightweight same-company check on what a 'founded X' / 'founder of X'
    claim is actually claiming to have founded."""
    if not company_name:
        return None
    m = re.search(r"[A-Za-z0-9]+", company_name)
    return m.group(0).lower() if m and len(m.group(0)) > 1 else None


_TITLE_TRAILING_OF_COMPANY = re.compile(r"^\s*of\s+([A-Z][\w &,.''-]{2,60})")


def _top_named_officer(text, title_regex, company_key=None):
    """Finds the name most consistently paired with title_regex (a
    _CEO_NAME_TITLE/_EXEC_CHAIR_NAME_TITLE-shaped pattern whose group(1) is
    the person's full name), requiring it to clearly lead any second-place
    name -- otherwise a single stray mention (an outside director's bio
    quoting their OWN matching title at a different company) could win just
    by appearing once. That "clearly leads" bar alone isn't enough, though:
    a director-qualifications table can repeat the SAME outside director's
    own "Chairman and CEO of <Other Company>" title 2+ times (once in a
    summary highlights bullet, once in the full director table row) --
    found producing a real false positive (CVS: "Guy P. Sansone Chairman
    and CEO of H2 Health" won the frequency contest over CVS's actual CEO,
    J. David Joyner, who's mentioned differently). A title match whose
    trailing text is an explicit "of <Company>" naming something other than
    the registrant itself is therefore excluded from counting at all."""
    from collections import Counter
    text = text.replace("\xa0", " ")
    name_hits = Counter()
    display = {}
    for m in title_regex.finditer(text):
        full_name = m.group(1).strip()
        tokens = full_name.split()
        if len(tokens) < 2:
            continue
        surname = tokens[-1].strip(".,’'")
        first = tokens[0].strip(".,’'")
        if surname.lower() in _CEO_NAME_STOPWORDS or first.lower() in _CEO_NAME_STOPWORDS:
            continue
        trailing_of = _TITLE_TRAILING_OF_COMPANY.match(text[m.end():m.end() + 65])
        if trailing_of and not _company_object_matches(trailing_of.group(1), company_key):
            continue
        key = surname.lower()
        name_hits[key] += 1
        display.setdefault(key, full_name)
    if not name_hits:
        return None
    top_two = name_hits.most_common(2)
    top_key, top_count = top_two[0]
    # A single occurrence is trusted here (unlike find_ceo_gender_signal's stricter
    # >=2 bar) because the stopword list and the trailing-"of <Company>" exclusion
    # above already filter out the two confirmed classes of noise match (document
    # section headers like "Relationship Between CEO"; an outside director's own
    # "Chairman and CEO of <Other Company>" title) -- and some real founder-CEOs
    # (e.g. ABNB's Brian Chesky) genuinely appear in this exact name+title shape
    # only once in the filing. Still requires a clear, non-tied lead over any
    # second-place name, so an ambiguous document (two names each mentioned once)
    # correctly falls back to "can't tell" rather than guessing.
    if len(top_two) > 1 and top_two[1][1] >= top_count:
        return None
    return display[top_key], top_key


_FOUNDER_VERB = re.compile(r"\b(?:co-)?founded\s+([^.]{0,60}?)(?=\s+in\s+\d{4}\b|[.,]|\s+and\b)", re.IGNORECASE)
# The object clause (X in "founder of X") isn't always adjacent to "founder" -- a
# title cluster can sit between them ("founder AND CHAIRMAN of X", "Founder and Board
# Chair of X"), which the original of-X-only capture missed entirely, silently
# treating the whole thing as a bare/generic founder claim with no object to check
# (found producing false positives: Intel's Lip-Bu Tan is "the founder and Chairman
# of Walden International" -- a VC firm he separately runs, not Intel; NRG's Lawrence
# Coben is "Founder and Board Chair of the ESCALA Initiative", an NGO). "Founder SPAC"
# is excluded outright: a real special-purpose-acquisition-company name that happens
# to start with the word "Founder" as its brand, not a role description (Ciena).
_FOUNDER_NOUN = re.compile(
    r"\b(?:co-)?founder\b(?!\s+spac\b)"
    # NOTE: each "of X" branch below is mandatory WITHIN its own alternative
    # (not a separately-optional trailing group) so the lazy title-text
    # quantifier is forced to backtrack/expand until it actually finds "of" --
    # otherwise (a bare trailing `(?:\s+of\s+(...))?` after a lazy quantifier)
    # the engine is free to stop at zero title characters and skip the "of X"
    # match entirely, since the whole thing being optional gives it no reason
    # to keep looking. Found silently swallowing the object clause in "is
    # also the founder and chairman of an international venture capital
    # firm" (Intel's Lip-Bu Tan's OWN separate VC firm, not Intel) and "Founder
    # and Board Chair of the ESCALA Initiative" (NRG's Lawrence Coben's
    # separate NGO) -- both left group(1)/(2) empty, so the different-company
    # object was never checked against the registrant's own name at all.
    r"(?:\s+of\s+([^.,]{0,60})"
    r"|\s+and\s+[a-z][a-z ]{0,30}?\s+of\s+([^.,]{0,60})"
    r")?",
    re.IGNORECASE)


_CAPITALIZED_NAME_LIKE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")
_ADJACENT_APPOSITIVE = re.compile(
    r",\s*(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*([A-Z][a-zA-Z.'\-]*(?:\s+[A-Z][a-zA-Z.'\-]*){0,2})")


def _appositive_name_conflicts(adjacent_text, full_name, company_key):
    """True if a comma-set-off name sits right next to the founder keyword
    (an appositive: 'our founder, Mr. Luddy' / 'Wayne Rollins, the founder')
    and it names someone OTHER than the officer this evidence search is
    anchored to -- catches two real cases a same-sentence guard alone
    doesn't: ServiceNow's 'Mr. McDermott, our founder, Mr. Luddy, and Mr.
    Yuan' (the founder appositive attaches to Luddy, not McDermott, even
    though McDermott's own name sits right before it in the same clause);
    and Rollins' 'Wayne Rollins, the founder of Rollins, Inc.' next to
    current CEO Gary W. Rollins -- same surname, so a surname-only check
    can't tell them apart, but the first names differ. A capitalized,
    comma-set-off phrase isn't always a person's name, though -- a title
    cluster ("Chair, Chief Executive Officer & co-founder") or the
    registrant's own company name ("co-founder, Salesforce") match the same
    shape (capitalized words after a comma) without naming anyone at all;
    those are filtered out via _CEO_NAME_STOPWORDS and company_key rather
    than treated as a conflicting person."""
    m = _ADJACENT_APPOSITIVE.search(adjacent_text)
    if not m:
        return False
    cand = [t.strip(".,") for t in m.group(1).split() if t.strip(".,")]
    if any(t.lower() in _CEO_NAME_STOPWORDS for t in cand):
        return False
    if company_key and company_key in " ".join(cand).lower():
        return False
    officer = [t.strip(".,’'") for t in full_name.replace("’", "'").split() if t.strip(".,’'")]
    if not cand or not officer:
        return False
    if cand[-1].lower() != officer[-1].lower():
        return True
    if len(cand) > 1 and cand[0].lower() != officer[0].lower():
        return True
    return False


_ABBREV_BEFORE_PERIOD = re.compile(r"\b(?:mr|ms|mrs|dr|jr|sr|st|inc|corp|co|ltd|no|vs|etc|[a-z])\.$", re.IGNORECASE)


def _real_period_before(text_lower, start, end):
    """Like text_lower.rfind('.', start, end), but skips a period that's
    actually part of an abbreviation ('Mr.', 'J.', 'Inc.') rather than a
    real sentence end -- otherwise "our founder, Mr. Luddy" reads as
    ending right after "Mr.", truncating the window before the name it's
    actually about even appears (see _officer_founder_evidence)."""
    pos = end
    while True:
        pos = text_lower.rfind(".", start, pos)
        if pos < 0:
            return -1
        if _ABBREV_BEFORE_PERIOD.search(text_lower[max(0, pos - 4):pos + 1]):
            continue
        return pos


def _real_period_after(text_lower, start, end):
    """Forward-searching counterpart to _real_period_before."""
    pos = start
    while True:
        pos = text_lower.find(".", pos, end)
        if pos < 0:
            return -1
        if _ABBREV_BEFORE_PERIOD.search(text_lower[max(0, pos - 4):pos + 1]):
            pos += 1
            continue
        return pos


def _officer_founder_evidence(text, text_lower, surname, full_name, company_key):
    """Looks for founder language ('founded X' / 'founder [of X]') within a
    bullet/sentence-bounded window around each occurrence of a specific,
    already-identified officer's surname. An object company (X) is accepted
    as this registrant if it's empty/generic ('it', 'the Company', 'us') or
    shares the registrant's own name token (company_key); otherwise -- a
    different, explicitly named company -- it's rejected. When the founder
    text sits BEFORE the surname in the window, the clause could belong to
    a different person entirely (a run-on leadership-transition sentence:
    "Mr. Smith previously transitioned to Founder and Executive Chairman
    and Rajesh Subramaniam assumed the role of CEO" -- FDX's founder claim
    is about Smith, not the current CEO Subramaniam, even though both names
    share one sentence) -- rejected if another capitalized full name sits
    between the founder text and this officer's own name. A tighter check
    right at the founder keyword itself (see _appositive_name_conflicts)
    catches the comma-appositive variant of the same problem, where the
    other name sits immediately next to "founder" rather than between it
    and the officer's name."""
    officer_first = full_name.split()[0].strip(".,’'").lower() if full_name.split() else ""
    surname_pat = re.compile(r"\b" + re.escape(surname) + r"\b")
    for m in surname_pat.finditer(text_lower):
        # A surname alone doesn't identify WHICH person a mention is about when the
        # company shares its name with a whole founding family (Rollins, Inc.: "Ms.
        # Rollins is the granddaughter of O. Wayne Rollins, the founder of Rollins,
        # Inc." mentions three different Rollinses in one sentence). If the word
        # immediately before this specific surname occurrence is itself a
        # capitalized first-name-like token that ISN'T the officer's own first
        # name, this occurrence is about a different family member -- skip it
        # rather than let a same-surname anchor pick up someone else's founder
        # claim (Gary W. Rollins, CEO, wrongly credited with "Wayne Rollins ...
        # founder" evidence that's actually about his late father).
        preceding_word = re.search(r"([a-z][a-z'\-]*)\s*$", text_lower[max(0, m.start() - 25):m.start()])
        if preceding_word and officer_first:
            pw = preceding_word.group(1)
            if pw not in ("mr", "ms", "mrs", "dr", "the", "a", "an", "our", "co", "") and pw != officer_first:
                continue
        window_start = max(0, m.start() - 80)
        window_end = min(len(text_lower), m.end() + 300)
        boundary = _real_period_before(text_lower, window_start, m.start())
        if boundary >= 0:
            window_start = boundary + 1
        stop_positions = [p for p in (_real_period_after(text_lower, m.end(), window_end),
                                       text_lower.find("•", m.end(), window_end),
                                       text_lower.find("●", m.end(), window_end)) if p >= 0]
        if stop_positions:
            window_end = min(stop_positions) + 1
        window = text_lower[window_start:window_end]
        if _PAST_TENSE.search(window):
            continue
        surname_rel_start = m.start() - window_start
        surname_rel_end = m.end() - window_start
        for pat in (_FOUNDER_VERB, _FOUNDER_NOUN):
            fm = pat.search(window)
            if not fm:
                continue
            groups = fm.groups()
            obj = next((g for g in groups if g), "").strip()
            if obj and not _company_object_matches(obj, company_key):
                continue
            if fm.start() < surname_rel_start:
                between = text[window_start + fm.end():window_start + surname_rel_start]
                if _CAPITALIZED_NAME_LIKE.search(between):
                    continue
            elif fm.start() >= surname_rel_end:
                between = text[window_start + surname_rel_end:window_start + fm.start()]
                if _CAPITALIZED_NAME_LIKE.search(between):
                    continue
            leading_adj = text[window_start + max(0, fm.start() - 45):window_start + fm.start()]
            trailing_adj = text[window_start + fm.end():window_start + min(len(window), fm.end() + 45)]
            if (_appositive_name_conflicts(leading_adj, full_name, company_key)
                    or _appositive_name_conflicts(trailing_adj, full_name, company_key)):
                continue
            return text[max(0, window_start):window_end].strip()
    return None


def _company_object_matches(obj, company_key):
    """True if a 'founded X' / 'founder of X' object plausibly refers to
    the registrant itself: a generic self-reference ('it', 'the Company',
    'us', 'our company'), or the registrant's own name token appears in it.
    False (a different, named company) otherwise."""
    obj = obj.strip().rstrip(",")
    if not obj or obj in ("it", "us", "the company", "our company", "the registrant"):
        return True
    if company_key and company_key in obj.lower():
        return True
    return False


def find_family_owned(text):
    """Requires the '<Name> family' mention to sit near real ownership
    language (beneficial ownership, voting power, trust, %) and rejects two
    confirmed false-positive classes: corporate brand phrasing like 'the X
    family of companies/brands/products', and a large asset manager's own
    controlling family appearing in a Schedule 13D/G beneficial-ownership
    footnote about the *reporting institution*, not the registrant (see
    _INSTITUTIONAL_OWNER_MARKERS)."""
    for m in re.finditer(r"the ([A-Z][a-z]+) family\b", text):
        after = text[m.end():m.end() + 30]
        if _FAMILY_BRAND_PHRASE.match(after):
            continue
        window = text[max(0, m.start() - 250):m.end() + 250]
        if not _OWNERSHIP_CONTEXT.search(window):
            continue
        # The institutional-owner check uses a deliberately tighter window (160 vs.
        # 250 chars each side) than the ownership-context check above: a large
        # beneficial-ownership table's shared footnotes often mention Vanguard/
        # BlackRock/etc. nearby for an unrelated reason (a standard "percent of
        # class after removing double-counted shares" disclaimer covering ALL
        # reported holders), which a too-wide window wrongly blames on a genuine,
        # unrelated family mention elsewhere in the same table (found regressing
        # Marriott: MAR's real controlling family sitting ~240 chars from a
        # table-wide Vanguard/BlackRock disclaimer). A strict single-sentence bound
        # is too tight the other way -- "P." in "Abigail P. Johnson" reads as a
        # sentence end, truncating the real Fidelity/FMR sentence early (LITE/NXPI's
        # "members of the Johnson family ... form a controlling group with respect
        # to FMR" sits ~130 chars after the family mention, split across what a
        # naive period-scan sees as two sentences).
        if _INSTITUTIONAL_OWNER_MARKERS.search(text[max(0, m.start() - 160):m.end() + 160]):
            continue
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
    "nominees", "independent", "lead", "trustee", "qualification", "qualifications",
    "highlights", "summary", "biography", "experience", "skills", "matrix",
    "relationship", "between", "average", "chart", "showing", "graphical",
    "versus", "comparison", "annual", "median", "report", "section", "table",
    "figure", "notice", "meeting", "statement", "mr", "ms", "mrs", "dr",
}
_EXEC_CHAIR_NAME_TITLE = re.compile(
    r"\b([A-Z][" + _NAME_CHARS + r".-]+(?:\s+[A-Z]\.?)?\s+[A-Z][" + _NAME_CHARS + r"-]+)\s*,?\s+"
    r"(?:(?:our |the Company's )?(?:President(?:\s+and\s+|,\s*))?Executive\s+Chair(?:man|woman)?\b)")
# Used only by find_founder_led, not find_ceo_gender_signal -- a superset of
# _CEO_NAME_TITLE that also accepts "Founder," inline within the title cluster
# ("Mark Zuckerberg, Founder, Chairman, and Chief Executive Officer") and an
# optional "director since" year some proxy tables insert between name and title
# ("Mark Zuckerberg 2004 Founder, Chairman, and Chief Executive Officer, Meta").
# Deliberately not merged into the shared _CEO_NAME_TITLE to avoid touching the
# already-validated women_led CEO-identification logic.
_CEO_NAME_TITLE_FOUNDER_OK = re.compile(
    r"\b([A-Z][" + _NAME_CHARS + r".-]+(?:\s+[A-Z]\.?)?\s+[A-Z][" + _NAME_CHARS + r"-]+)\s*,?\s+"
    r"(?:\d{1,4}\s+)?(?:(?:Co-)?Founder(?:,\s*|\s+and\s+))?"
    r"(?:(?:our |the Company's )?(?:Chair(?:man|woman)?(?:\s+of\s+the\s+Board(?:\s+of\s+Directors)?)?(?:,?\s+and\s+|\s*&\s*|,\s*)|President(?:,?\s+and\s+|\s*&\s*|,\s*))*"
    r"(?:Chief Executive Officer|CEO)\b)")


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


_INDEP_PCT_PATTERNS = [
    # "91% of the board/directors ... independent" -- the original, still the most common
    # form, but the original version of this ("(\d{1,3})\s*%\s*of[^.]{0,60}?independent")
    # was far too loose: it matches ANY "N% of <anything> ... independent" construction,
    # not specifically board composition. Found producing real wrong values at scale: "39%
    # of companies had an independent chair" (an industry peer-benchmarking statistic from
    # Chevron's proxy, not Chevron's own board -- and the likely source of the same wrong
    # 39% appearing across multiple unrelated companies that cite the same survey), "2% of
    # such other company's consolidated gross revenues, is not independent" (a related-
    # party-transaction revenue threshold in the independence-criteria definition, and
    # negated besides), and "5% of the fees we pay to our independent registered public
    # accounting firm" (an auditor fee cap -- "independent" here means the auditor, not a
    # director). Now requires "of" to be followed (allowing a few filler words -- "the
    # current", "serving", "the members of") by "board" or "directors" as the head noun --
    # not just "independent" appearing somewhere within 60 characters -- and excludes an
    # immediately following "accounting"/"auditor" (the auditor-independence class).
    # NOTE: must still require "independent" nearby -- an early version of this fix
    # dropped that requirement entirely while tightening the "of ..." clause, which made
    # it match ANY "N% of the board/directors" regardless of subject, including near-
    # universal "proxy access" boilerplate ("a shareholder ... is able to nominate
    # directors to fill up to 20% of the Board seats") that has nothing to do with
    # independence -- caught immediately by a full regression run before this shipped.
    # The tail also needs "are/is/were/being" directly before "independent", not just the
    # bare word anywhere in the next 60 characters -- otherwise an unrelated nearby role
    # title ("... 20% of our Board ... Lead Independent Director") satisfies a bare
    # "independent" check without ever actually stating a composition percentage.
    re.compile(r"(\d{1,3})\s*%\s*of\s+(?:[a-z]+\s+){0,4}?(?:board|directors?)\b(?:\s+members?)?"
               r"[^.]{0,60}?(?:are|is|were|being)\s+independent\b(?!\s+registered\s+public\s+accounting|\s+auditor)", re.IGNORECASE),
    # "Independent directors comprise/constitute/represent 100% of ..." -- reversed word
    # order (the word "independent" comes first, not the number) that the pattern above
    # can't match at all.
    re.compile(r"independent\s+directors?\s+(?:comprise|constitute|represent)\s+(\d{1,3})\s*%", re.IGNORECASE),
    # A compact infographic/"board snapshot" tile style increasingly common in modern
    # proxies, e.g. "8.6 years AVERAGE TENURE 91% INDEPENDENT" -- no "of" at all.
    re.compile(r"(\d{1,3})\s*%\s+independent\b", re.IGNORECASE),
    # Parenthetical form: "Nine (9) directors (82%) are independent".
    re.compile(r"\(\s*(\d{1,3})\s*%\s*\)\s*(?:are|is)\s+independent", re.IGNORECASE),
]
# A "100% independent" (or "N% of ... independent") stat is at least as likely to
# describe a specific committee (Audit, Compensation, Nominating) as the full board, and
# these dashboard-style proxies often show both close together -- confirmed as a real
# false positive on every pattern above, not just the tile/parenthetical ones originally
# thought to be at risk (e.g. Adobe: "Our Executive Compensation Committee is comprised
# 100% of independent directors"; CenterPoint: "the 100% independent director
# composition of each Board committee", and separately "100% Independent Human Capital
# and Compensation Committee" naming the committee directly after the number with no
# "members of" construction at all). Two distinct constructions, checked separately with
# different windows:
#   - LEADING: "committee(s)" as the direct grammatical subject right before the number
#     ("Board committees consist of 100% independent directors", "Nominating and
#     Corporate Governance Committee 100% INDEPENDENT"). Bounded by the nearest "." or
#     "•", OR the specific marker ", and that" (a genuine new-clause break) -- NOT a bare
#     comma, which is also just a list separator within the same clause ("Our three
#     standing Board committees—Audit, Compensation and Nominating and Governance—are
#     100% independent" -- D.R. Horton: a bare-comma break would cut "committees" out of
#     the leading window here and wrongly keep this as if it were board-wide) and must be
#     distinguished from an unrelated earlier committee mention genuinely in a separate
#     clause (Schwab: "...scope of authority of these committees, and that over 70% of
#     our directors are independent..." -- a real board-wide claim).
#   - TRAILING: either "committee(s)" directly, allowing up to 120 characters of
#     filler/committee-name text ("100% Independent Human Capital and Compensation
#     Committee"; Cigna: "100% independent Audit & Compliance, Corporate Governance,
#     Finance & Technology, and People Resources Committees" -- multi-word committee
#     names joined with "&" and commas blow past a plain-word-count filler budget, so
#     the filler is character-bounded instead, stopping only at a real clause break
#     (bullet/period), not at punctuation that's just part of a committee name list),
#     OR the longer "members/composition of/on ... committee(s)" construction for an
#     enumerated committee-name list, which must NOT break on a comma/semicolon for the
#     same reason as above ("100% independent members of the Audit, Compensation and
#     Nominating and Corporate Governance committees").
_INDEP_PCT_COMMITTEE_LEADING = re.compile(r"committees?\b", re.IGNORECASE)
_INDEP_PCT_NEW_CLAUSE = re.compile(r",\s*and\s+that\b", re.IGNORECASE)
_INDEP_PCT_COMMITTEE_TRAILING = re.compile(
    r"^\s*[^.•●○▪]{0,120}?committees?\b|"
    r"^\s*(?:[a-z]+\s+){0,2}(?:members?|composition)\s+(?:of|on)\b.{0,380}?committees?\b", re.IGNORECASE)
_INDEP_PCT_BOARD_CONTEXT = re.compile(r"\bboard\b|\bdirectors?\b", re.IGNORECASE)
# "Proxy Highlights" summary tables get flattened by get_text(" ", strip=True) into a
# run of label/value pairs with no cell delimiter -- e.g. ADM: "... Director Term One
# Year Number of Directors 13 % Independent 92% % Overall Diversity 54% ...". Pattern 2
# (bare "N% independent", meant for infographic tiles like "91% INDEPENDENT") matched
# "13" here: the *director count* label sitting immediately before an unrelated "%
# Independent" column header, not a percentage of anything. The real value, 92%, sits
# right after and is simply never reached because the loop returns on the first match.
# Excluded by checking the number isn't immediately preceded by a bare count-style label.
_INDEP_PCT_COUNT_LABEL = re.compile(r"(?:number\s+of\s+directors|board\s+size)\s*$", re.IGNORECASE)
# "100% of Board committee members are independent" (Intuitive Surgical): pattern 0's
# "of (board|directors)" head-noun requirement is satisfied by "Board" immediately after
# "of", but "committee" right after that changes the actual subject to committee
# membership, not the full board -- the existing leading/trailing committee checks only
# look OUTSIDE the matched span, so a "committee" word inside the match itself (between
# the head noun and "are/is independent") was never checked. "committee" can legitimately
# appear inside a genuine board-wide claim too ("...board, including its committees, is
# independent"), so this only excludes when it directly follows the head noun as a
# compound ("Board committee members"), not any "committee" mention anywhere in the match.
_INDEP_PCT_INLINE_COMMITTEE = re.compile(r"(?:board|directors?)\s+committee", re.IGNORECASE)


def find_independent_directors_pct(text):
    for pat in _INDEP_PCT_PATTERNS:
        for m in pat.finditer(text):
            if _INDEP_PCT_COUNT_LABEL.search(text[max(0, m.start() - 40):m.start()]):
                continue
            if _INDEP_PCT_INLINE_COMMITTEE.search(m.group(0)):
                continue
            window_start = max(0, m.start() - 250)
            # Bullet glyphs vary by filing -- "•" (U+2022) is common, but "●" (U+25CF,
            # BLACK CIRCLE) is at least as common and wasn't being recognized at all,
            # letting the leading window silently run past real bullet-point breaks and
            # pick up an unrelated separate bullet item (UDR: a "● Independent Committee
            # Chairs" bullet several items above the real "90% of serving board members
            # are independent" bullet, both in the same governance-highlights list).
            boundary_positions = [p for p in (text.rfind(c, window_start, m.start()) for c in (".", "•", "●", "○", "▪"))
                                   if p >= 0]
            boundary_positions += [window_start + cm.end() - 1
                                    for cm in _INDEP_PCT_NEW_CLAUSE.finditer(text[window_start:m.start()])]
            # rfind returns -1 for "not found", which is itself a valid int and would
            # otherwise win the max() comparison over a real (larger) boundary position
            # -- filtered out above so an absent "."/"•" correctly falls back to the
            # window_start cap instead of silently becoming -1 and scanning the ENTIRE
            # rest of the document backwards for "committee" (found producing a 110,000-
            # character "leading" window on a real filing whose preceding 250 characters
            # were dense XBRL tag metadata with no punctuation at all).
            lead_bound = max(boundary_positions, default=window_start - 1)
            leading = text[lead_bound + 1:m.start()]
            if _INDEP_PCT_COMMITTEE_LEADING.search(leading):
                continue
            trailing = text[m.end():m.end() + 400]
            if _INDEP_PCT_COMMITTEE_TRAILING.search(trailing):
                continue
            window = text[max(0, m.start() - 100):m.end() + 100]
            if not _INDEP_PCT_BOARD_CONTEXT.search(window):
                continue
            return int(m.group(1))
    # "N out of M directors ... independent" -- "out of" is at least as common as a bare
    # "of" in practice and the original pattern only accepted the latter.
    m2 = re.search(r"(\d{1,2})\s+(?:out\s+)?of\s+(?:our\s+)?(\d{1,2})\s+director[s]?[^.]{0,60}?(?:is|are)\s+independent", text, re.IGNORECASE)
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
