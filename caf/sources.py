"""Parsers for the settlement directories. Pure functions over HTML -- no network.

Two independent directories are read:

* ClassAction.org `/settlements` -- one card per open settlement, with a "Proof Required?"
  field (Yes / No / N/A), a deadline, a payout, a one-sentence eligibility blurb and a
  direct link to the official settlement website.
* OpenClassActions.com -- the full directory (`/settlements.php`, rows labelled
  none / required / automatic), a strict "no-proof" page (no receipts *and* no
  administrator-issued ID), and per-settlement detail pages whose fact boxes say exactly
  what the claim form asks for.

The parsers are tested against saved copies of each page in tests/fixtures.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CAO_URL = "https://www.classaction.org/settlements"
OCA_DIRECTORY_URL = "https://openclassactions.com/settlements.php"
OCA_NO_PROOF_URL = "https://openclassactions.com/no-proof-class-action-settlements.php"

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
_STATE_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}


def clean(fragment: str) -> str:
    """HTML fragment -> plain text: drop tags, unescape entities, collapse whitespace."""
    text = re.sub(r"(?s)<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def strip_tracking(url: str) -> str:
    """Remove utm_* parameters (OpenClassActions tags every outbound link)."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def host_of(url: str | None) -> str:
    """Lower-cased host without a leading `www.` ('' if unparsable)."""
    if not url:
        return ""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def normalize_states(raw: str) -> list[str]:
    """'US-CA US-CO', 'US-CA CO' and 'CA' all become ['CA', 'CO'] / ['CA']."""
    codes = []
    for token in re.split(r"[\s,;/]+", raw.upper()):
        token = token.removeprefix("US-")
        if token in US_STATES and token not in codes:
            codes.append(token)
    return codes


def _codes(names_text: str) -> list[str]:
    found = []
    for piece in re.split(r",|\bor\b|\band\b|&|/", names_text):
        piece = re.sub(r"^\s*(?:the )?state of\s+", "", piece.strip(), flags=re.I).lower()
        # "Current California residents" -> try "california" after the full phrase
        code = _STATE_BY_NAME.get(piece) or _STATE_BY_NAME.get(piece.rsplit(" ", 1)[-1])
        if code and code not in found:
            found.append(code)
    return found


def states_in_parentheses(name: str) -> list[str]:
    """Directories mark state-limited cases like 'Tesla - Idle Fees (California)'."""
    found: list[str] = []
    for group in re.findall(r"\(([^)]*)\)", name):
        found += [c for c in _codes(group) if c not in found]
    return found


_STATE_WORD = r"[A-Z][a-z]+(?: [A-Z][a-z]+)?"
_STATE_LIST = rf"(?:the State of )?{_STATE_WORD}(?:(?:,? or |,? and |, ){_STATE_WORD})*"
_RESIDENCY_RX = re.compile(
    rf"\b(?:residents? of|resided in|reside in|live[sd]? in|living in|domiciled in|located in|"
    rf"property in|(?:purchased|bought|made purchases?)(?: [a-z]+){{0,6}} in)\s+({_STATE_LIST})")
_RESIDENTS_RX = re.compile(rf"\b({_STATE_LIST}) residents?\b")


def states_in_text(text: str) -> list[str]:
    """States a class is limited to, from phrases like 'if you live in California or
    Pennsylvania' or 'Illinois residents'. Mentions like 'outside of California' don't count."""
    found: list[str] = []
    for rx in (_RESIDENCY_RX, _RESIDENTS_RX):
        for group in rx.findall(text):
            found += [c for c in _codes(group) if c not in found]
    return found


def _iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


# -- ClassAction.org ------------------------------------------------------------------

@dataclass
class CaoItem:
    slug: str
    name: str
    official_url: str | None
    deadline: date | None       # None when the card says "Varies" (or anything unparsable)
    deadline_text: str
    proof: str                  # "Yes" | "No" | "N/A" | ""
    payout: str
    blurb: str

    @property
    def page_url(self) -> str:
        return f"{CAO_URL}#{self.slug}"


def _cao_field(card: str, label_regex: str) -> str:
    m = re.search(label_regex + r"</span>\s*<span[^>]*>([^<]*)</span>", card)
    return clean(m.group(1)) if m else ""


def parse_cao_listing(page: str) -> list[CaoItem]:
    starts = [m.start() for m in re.finditer(r'<div id="[^"]+"[^>]*\bsettlement-card\b', page)]
    items: list[CaoItem] = []
    seen: set[str] = set()
    for i, start in enumerate(starts):
        card = page[start: starts[i + 1] if i + 1 < len(starts) else len(page)]
        slug = re.match(r'<div id="([^"]+)"', card).group(1)
        if slug in seen:  # "Featured" cards are repeated further down the page
            continue
        seen.add(slug)
        name = re.search(r'data-name="([^"]*)"', card)
        link = re.search(r'<a href="([^"]+)" class="js-settlement-link', card)
        blurb = re.search(r'<p class="f6[^"]*">(.*?)</p>', card, re.S)
        deadline_text = _cao_field(card, r"Deadline")
        try:
            deadline = datetime.strptime(deadline_text, "%m/%d/%y").date()
        except ValueError:
            deadline = None
        items.append(CaoItem(
            slug=slug,
            name=_html.unescape(name.group(1)).strip() if name else slug,
            official_url=_html.unescape(link.group(1)).strip() if link else None,
            deadline=deadline,
            deadline_text=deadline_text,
            proof=_cao_field(card, r"Required\?"),
            payout=_cao_field(card, r"Payout"),
            blurb=clean(blurb.group(1)) if blurb else "",
        ))
    return items


# -- OpenClassActions ---------------------------------------------------------------

@dataclass
class OcaRow:
    url: str
    name: str
    details: str
    proof: str                  # "none" | "required" | "automatic" | ""
    deadline: date | None
    deadline_text: str          # raw data-deadline ('' for automatic, sometimes just a year)
    category: str
    states: list[str] = field(default_factory=list)
    strict_no_proof: bool = False   # listed on the no-receipts-no-ID page

    @property
    def slug(self) -> str:
        return urlsplit(self.url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".php")


def _attr(attrs: str, name: str) -> str:
    m = re.search(rf'\bdata-{name}="([^"]*)"', attrs)
    return _html.unescape(m.group(1)).strip() if m else ""


def parse_oca_directory(page: str) -> list[OcaRow]:
    rows = []
    for href, attrs, body in re.findall(
            r'<a class="dir-row"[^>]*?href="([^"]+)"([^>]*)>(.*?)</a>', page, re.S):
        name = re.search(r'<span class="dir-name"[^>]*>(.*?)</span>', body, re.S)
        details = re.search(r'<span class="dir-details"[^>]*>(.*?)</span>', body, re.S)
        raw_deadline = _attr(attrs, "deadline")
        rows.append(OcaRow(
            url=_html.unescape(href).strip(),
            name=clean(name.group(1)) if name else "",
            details=clean(details.group(1)) if details else "",
            proof=_attr(attrs, "proof"),
            deadline=_iso_date(raw_deadline),
            deadline_text=raw_deadline,
            category=_attr(attrs, "category"),
            states=normalize_states(_attr(attrs, "region")),
        ))
    return rows


def parse_oca_no_proof(page: str) -> list[OcaRow]:
    """The strict list: claim forms asking for no receipts, records *or* notice ID."""
    rows = []
    for tag, body in re.findall(r'(<a class="oca-card[^"]*"[^>]*>)(.*?)</a>', page, re.S):
        href = re.search(r'href="([^"]+)"', tag)
        if not href:
            continue
        title = re.search(r'<h3 class="title">(.*?)</h3>', body, re.S)
        payout = re.search(r'<div class="payout-sub">(.*?)</div>', body, re.S)
        raw_deadline = _attr(tag, "deadline")
        rows.append(OcaRow(
            url=_html.unescape(href.group(1)).strip(),
            name=clean(title.group(1)) if title else "",
            details=clean(payout.group(1)) if payout else "",
            proof=_attr(tag, "proof") or "none",
            deadline=_iso_date(raw_deadline),
            deadline_text=raw_deadline,
            category=_attr(tag, "category"),
            states=normalize_states(_attr(tag, "region")),
            strict_no_proof=True,
        ))
    return rows


@dataclass
class OcaDetail:
    title: str
    facts: dict[str, tuple[str, str]]      # label -> (value, sub-line)
    claim_url: str | None                  # the page's "File Claim" button
    official_url: str | None               # "Official settlement website" link, if given
    status_text: str
    faq: list[tuple[str, str]]
    payment_methods: list[str]

    def fact(self, *labels: str) -> tuple[str, str]:
        """First fact whose label contains any of `labels` (case-insensitive)."""
        for label, value in self.facts.items():
            if any(want.lower() in label.lower() for want in labels):
                return value
        return ("", "")


_PAYMENT_WORDS = [
    ("PayPal", r"\bpaypal\b"), ("Venmo", r"\bvenmo\b"), ("Zelle", r"\bzelle\b"),
    ("virtual card", r"virtual (?:prepaid |debit |mastercard |visa )?card"),
    ("direct deposit/ACH", r"\bach\b|direct deposit"),
    ("check", r"\b(?:paper|mailed|physical) checks?\b|\bby check\b|\ba check\b"),
]


def parse_oca_detail(page: str) -> OcaDetail:
    title = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    facts: dict[str, tuple[str, str]] = {}
    for label, value, sub in re.findall(
            r'<span class="fact-label">(.*?)</span>\s*<span class="fact-value[^"]*">(.*?)</span>'
            r'\s*(?:<span class="fact-sub">(.*?)</span>)?', page, re.S):
        facts.setdefault(clean(label), (clean(value), clean(sub)))

    claim = re.search(r'<a class="file-claim" href="([^"]+)"', page)
    official = None
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        if clean(text).lower().startswith("official settlement website"):
            official = strip_tracking(_html.unescape(href))
            break

    status = re.search(r'<h2 class="h2-headers">Current Status</h2>(.*?)<(?:h2|section|div)\b',
                       page, re.S)

    faq: list[tuple[str, str]] = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data])
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "FAQPage":
                for q in node.get("mainEntity", []):
                    answer = (q.get("acceptedAnswer") or {}).get("text", "")
                    faq.append((clean(q.get("name", "")), clean(answer)))

    status_text = clean(status.group(1))[:700] if status else ""
    # Only the case-specific parts: the whole page also carries sidebars and other cases.
    relevant = " ".join([status_text, *(f"{v} {s}" for v, s in facts.values()),
                         *(f"{q} {a}" for q, a in faq)]).lower()
    methods = [label for label, rx in _PAYMENT_WORDS if re.search(rx, relevant)]

    return OcaDetail(
        title=clean(title.group(1)) if title else "",
        facts=facts,
        claim_url=strip_tracking(_html.unescape(claim.group(1))) if claim else None,
        official_url=official,
        status_text=status_text,
        faq=faq,
        payment_methods=methods,
    )
