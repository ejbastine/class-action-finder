"""Turn the two directories into one de-duplicated list of settlements, then decide for
each one (a) how much evidence a claim needs, (b) what kind of class it is, and
(c) whether it can apply to you at all (open deadline, your states).

Evidence tiers -- the "minimal to no evidence" rule lives here:

  automatic    no claim form at all; paid if you're in the class
  attestation  claim form asks for no receipts and no notice ID; you sign under penalty of perjury
  notice_id    no documents, but you need the Claim/Notice ID (+PIN) mailed or emailed to class members
  unverified   ClassAction.org says "no proof" but nothing confirms whether a notice ID is required

Anything that needs receipts or records is excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlsplit

from .sources import (CaoItem, OcaDetail, OcaRow, host_of, states_in_parentheses, states_in_text,
                      strip_tracking)

TIER_AUTOMATIC = "automatic"
TIER_PARTIAL_AUTO = "partial_auto"   # automatic for people in the company's records; others file a claim
TIER_ATTEST = "attestation"
TIER_NOTICE = "notice_id"
TIER_UNVERIFIED = "unverified"
TIER_ORDER = {TIER_AUTOMATIC: 0, TIER_PARTIAL_AUTO: 1, TIER_ATTEST: 2, TIER_NOTICE: 3,
              TIER_UNVERIFIED: 4}

KIND_CONSUMER = "consumer"   # a product/service/app/company you'd know you used
KIND_BREACH = "breach"       # data breaches: you're in only if your data was exposed (you'd have a notice)
KIND_GROUP = "group"         # a narrow population: employees, patients of one provider, tenants...

EXCLUDED_DOCS = "Needs receipts or other documents"


@dataclass
class Settlement:
    key: str
    aliases: list[str]
    name: str
    who: str
    payout: str
    payout_note: str
    deadline: date | None
    deadline_note: str
    states: list[str]
    category: str
    kind: str
    group_label: str
    tier: str | None
    tier_note: str
    official_url: str | None
    claim_url: str | None
    link_note: str
    links: dict[str, str]
    company: str
    summary: str = ""                # OpenClassActions' one-line summary when ClassAction.org gave `who`
    faq_hint: str = ""
    payment_methods: list[str] = field(default_factory=list)
    excluded: str = ""
    status: str = ""                 # case page "Status" fact, e.g. "Claims Open"
    deadline_text: str = ""          # case page "Claim Deadline" fact, e.g. "TBD"
    cao: CaoItem | None = None
    oca: OcaRow | None = None
    detail: OcaDetail | None = None
    first_seen: date | None = None
    is_new: bool = False             # first appeared in this run (never on a first run)
    ai: dict = field(default_factory=dict)

    def days_left(self, today: date) -> int | None:
        return (self.deadline - today).days if self.deadline else None

    @property
    def status_upcoming(self) -> bool:
        """Case page says claims haven't opened yet (nothing to file today). "Pending final
        approval" is *not* this: claims are normally open while final approval is pending."""
        if self.tier == TIER_AUTOMATIC:
            return False
        if self.detail and not self.claim_url and not self.official_url:
            return True    # the case page links to no claim site yet
        st, dl = self.status.lower(), self.deadline_text.lower()
        return ("claims open" not in st and bool(re.search(
            r"not yet|upcoming|coming soon|pending (?:preliminary|court)|awaiting preliminary|"
            r"register for updates|litigation", st))) or bool(
            re.fullmatch(r"\s*(?:tbd|to be (?:announced|determined)|not set(?: yet)?)\s*", dl))


# -- pairing the two directories -------------------------------------------------------

_STOP = set("""class action actions settlement settlements lawsuit lawsuits litigation data breach
breaches privacy the and of for a an inc llc co corp company corporation group claims claim program
consumer website security incident cyberattack cyber attack in on at by with to us""".split())


def name_tokens(name: str) -> set[str]:
    text = name.lower().replace("’", "'")
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", "", text)      # "non-bank" == "nonbank"
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = set()
    for tok in text.split():
        if tok in _STOP or len(tok) < 2 or re.fullmatch(r"\d+[mk]?", tok):
            continue  # generic words and "$23.9M"-style amounts
        tokens.add(tok[:-1] if len(tok) > 4 and tok.endswith("s") else tok)
    return tokens


def same_case_score(name_a: str, deadline_a: date | None,
                    name_b: str, deadline_b: date | None) -> float:
    """> 0 when two listings look like the same case (higher = more confident)."""
    a, b = name_tokens(name_a), name_tokens(name_b)
    if not a or not b:
        return 0.0
    shared, smaller = a & b, min(len(a), len(b))
    gap = abs((deadline_a - deadline_b).days) if deadline_a and deadline_b else None
    same_deadline = gap is not None and gap <= 2
    jaccard = len(shared) / len(a | b)
    contained = len(shared) == smaller
    distinctive = any(len(t) >= 3 for t in shared)
    if ((contained and smaller >= 2) or jaccard >= 0.6
            or (same_deadline and distinctive)
            or (len(shared) >= 2 and gap is not None and gap <= 31)):
        return jaccard + (0.5 if same_deadline else 0.0)
    return 0.0


def pair_score(cao: CaoItem, oca: OcaRow) -> float:
    return same_case_score(cao.name, cao.deadline, oca.name, oca.deadline)


def pair_sources(cao_items: list[CaoItem], oca_rows: list[OcaRow]) -> dict[str, OcaRow]:
    """CAO slug -> its OCA row. Greedy by score so each listing is used at most once."""
    scored = sorted(((pair_score(c, o), c.slug, o.url)
                     for c in cao_items for o in oca_rows), reverse=True)
    by_url = {o.url: o for o in oca_rows}
    used_cao: set[str] = set()
    used_oca: set[str] = set()
    pairs: dict[str, OcaRow] = {}
    for score, slug, url in scored:
        if score <= 0:
            break
        if slug in used_cao or url in used_oca:
            continue
        used_cao.add(slug)
        used_oca.add(url)
        pairs[slug] = by_url[url]
    return pairs


# -- classification --------------------------------------------------------------------

_BREACH_RX = re.compile(r"data breach|\bbreach(?:es)?\b|data (?:security )?incident|"
                        r"cyber ?attack|ransomware", re.I)

# First match wins. Only clearly narrow populations -- banks, cars, apps etc. stay "consumer"
# because you know whether you used them.
_GROUP_RULES = [
    ("Calls, texts or faxes you received", r"unwanted (?:calls|texts|faxes)|text messages?|robocall|"
                                           r"prerecorded|telemarket|\btcpa\b|called on your cell|\bfax"),
    ("Retirement-plan members", r"\b401\(?k\)?|\b403\(?b\)?|\berisa\b|\besop\b|retirement (?:savings )?plan|"
                                r"\bpension"),
    ("Shareholders & investors", r"\bstockholders?\b|\bshareholders?\b|securities|\binvestors?\b"),
    ("Veterans & military", r"\bveterans?\b|\bmilitary\b|servicemember"),
    ("Employees & job applicants", r"\bemploy|\bworkers?\b|\bwages?\b|job postings?|\bapplicants?\b|"
                                   r"\bdrivers?\b|\bofficers?\b|overtime|\bpaga\b|\bnurses?\b|piece-rate|"
                                   r"\bpilots?\b"),
    ("Families & specific events", r"\bdonors?\b|families of|next of kin|morgue|funeral|cemetery|burial"),
    ("Students", r"\bstudents?\b|tuition|\benrolled\b"),
    ("Patients of a specific provider", r"\bpatients?\b|hospital|medical (?:center|group)|"
                                        r"health(?:care)? system|\bclinic|patient portal|surger"),
    ("Tenants & specific housing", r"\btenants?\b|apartment|landlord|rental forms|\bhoa\b|eviction"),
    ("Insurance policyholders & claims", r"total loss|policyholders?|underinsured|"
                                         r"\binsurance (?:polic|claim|syndicate)"),
    ("Local residents & specific places", r"\bcity of\b|\bcounty\b|\bpolice\b|correction|\bjail|prison|"
                                          r"\barrest|strip search|red[- ]light|derailment|refinery|"
                                          r"wildfire|\bflood|central booking|\bnyc\b|new york city"),
    ("Businesses & professionals", r"\bbusinesses\b|\bmerchants?\b|franchise|\bdealers?\b|physicians|"
                                   r"\bfarm(?:er|ers|ing)?\b|agricultur|commercial|small business"),
]


def classify_kind(text: str, category: str) -> tuple[str, str]:
    if category.lower() == "data breach" or _BREACH_RX.search(text):
        return KIND_BREACH, "Data breach"
    for label, rx in _GROUP_RULES:
        if re.search(rx, text, re.I):
            return KIND_GROUP, label
    return KIND_CONSUMER, ""


_ID_RX = re.compile(r"\b(?:login|claim|notice|class member|unique|member)\s*(?:id|number|code|#)"
                    r"|\bpin\b", re.I)
_ID_OPTIONAL_RX = re.compile(r"\b(?:id|pin|number|code)\b[^.;·]{0,40}\b(?:optional|not required)|"
                             r"\boptional\b[^.;·]{0,40}\b(?:id|pin)\b|no (?:notice|claim) id|"
                             r"without (?:a|an|the|your|any) (?:[\w-]+ ){0,2}(?:id|pin|notice|claim)",
                             re.I)
_ID_REQUIRED_RX = re.compile(r"\b(?:required|requires|gated|needed|must)\b|will not open|"
                             r"won't open", re.I)
_PAPER_ONLY_RX = re.compile(r"optional on the (?:mailed )?paper|(?:paper|printed|printable|mailed[- ]in|"
                            r"mail-in) (?:claim )?form", re.I)
_GATED_WITHOUT_RX = re.compile(r"(?:will not|won't|cannot|can't|does not|doesn't) (?:open|proceed|work|"
                               r"be filed)[^.;·]{0,20}\bwithout\b", re.I)
_PARTIAL_AUTO_RX = re.compile(r"\bfor (?:most|some)\b|everyone else (?:files|must)|others (?:must )?file|"
                              r"claim form opens|some (?:class )?members (?:must )?file", re.I)
_DOCS_RX = re.compile(r"receipts?|documentation|documented|proof of purchase|invoices?|"
                      r"(?:bank|account) statements?|\brecords\b", re.I)
_DOCS_WAIVED_RX = re.compile(r"no (?:\w+ )?(?:receipts?|documentation|documents|proof|records)|"
                             r"without (?:\w+ )?(?:receipts?|documentation|proof)|needs no|"
                             r"no-documentation|\bflat\b|alternat", re.I)
# Documents that are only for an optional, bigger payment ("receipts for the $5,000
# documented-loss tier") don't count against the basic claim.
_DOCS_TIER_ONLY_RX = re.compile(r"\btiers?\b|\boptions?\b|documented[- ]loss|\blosse?s?\b|"
                                r"out-of-pocket|reimburse|claims? (?:of|over|above) \$|"
                                r"\bonly (?:for|to|if|when)\b", re.I)
_NOTICE_RX = re.compile(r"\bnotice\b|\bnotified\b", re.I)


def tier_from_text(value: str, sub: str) -> tuple[str | None, str] | None:
    """Tier from an OpenClassActions 'Proof Required' fact (value + sub-line).

    Returns (tier, note), (None, note) when the basic claim needs documents, or None when the
    text doesn't say either way.
    """
    v = value.strip().lower()
    both = f"{value} · {sub}"     # separator so "No" + "Claim ID…" never reads as "No Claim ID"
    note = sub or value
    if v.startswith("automatic"):
        return TIER_AUTOMATIC, note
    has_id = bool(_ID_RX.search(both))
    # "optional on the paper form" or "won't open without the Claim ID" still means the
    # online form needs the ID
    id_optional = (bool(_ID_OPTIONAL_RX.search(both)) and not _PAPER_ONLY_RX.search(both)
                   and not _GATED_WITHOUT_RX.search(both))
    needs_docs = bool(_DOCS_RX.search(both))
    docs_waived = bool(_DOCS_WAIVED_RX.search(both))
    docs_tier_only = bool(_DOCS_TIER_ONLY_RX.search(both))
    base_needs_docs = needs_docs and not docs_waived and not docs_tier_only
    if v.startswith(("no", "optional", "partial")):
        # "Proof: No" plus an ID mention means notice-gated only if the ID is said to be required
        id_required = has_id and not id_optional and bool(_ID_REQUIRED_RX.search(both))
        return (TIER_NOTICE if id_required else TIER_ATTEST), note
    if base_needs_docs:
        return None, note
    if has_id and not id_optional:
        return TIER_NOTICE, note
    if has_id or docs_waived or docs_tier_only:
        return (TIER_NOTICE if _NOTICE_RX.search(both) and not id_optional else TIER_ATTEST), note
    return None


def _listing_tier(cao: CaoItem | None, oca: OcaRow | None) -> tuple[str | None, str]:
    if oca and oca.strict_no_proof:
        return TIER_ATTEST, "No receipts, records or notice ID needed"
    if oca and oca.proof == "automatic":
        return TIER_AUTOMATIC, "Paid automatically; no claim form"
    if oca and oca.proof == "none":
        return TIER_ATTEST, "No receipts needed"
    if oca and oca.proof == "required":
        # OpenClassActions lumps "receipts" and "the ID from your notice" together as
        # "Proof / ID". Keep the case if anything suggests the ID is the only gate; the
        # detail page (fetched next) confirms or excludes it.
        if ((cao and cao.proof == "No") or _ID_RX.search(oca.details)
                or _DOCS_WAIVED_RX.search(oca.details)):
            return TIER_NOTICE, "Likely needs the ID from the notice sent to class members"
        return None, EXCLUDED_DOCS
    if cao and cao.proof == "No":
        return TIER_UNVERIFIED, "No proof of purchase needed (per ClassAction.org); may still ask for a notice ID"
    if cao and cao.proof == "Yes":
        return None, EXCLUDED_DOCS
    return TIER_UNVERIFIED, "Proof requirement not stated; check the official site"


def _company(cao: CaoItem | None, oca: OcaRow | None) -> str:
    if cao:
        return re.split(r"\s+-\s+", cao.name, maxsplit=1)[0].strip()
    name = re.split(r"\s+[—–-]\s+|\s+\$", oca.name, maxsplit=1)[0]
    name = re.sub(r"\([^)]*\)", "", name)
    name = re.split(r"\b(?:Data Breach|Data Security|Pixel|Website|Class Action|Settlement|BIPA)\b",
                    name, maxsplit=1)[0]
    return re.sub(r"\s+", " ", name).strip(" -–—&,") or oca.name


def _make(cao: CaoItem | None, oca: OcaRow | None) -> Settlement:
    aliases = ([f"cao:{cao.slug}"] if cao else []) + ([f"oca:{oca.slug}"] if oca else [])
    deadlines = [d for d in (cao.deadline if cao else None, oca.deadline if oca else None) if d]
    note = ""
    if len(deadlines) == 2 and deadlines[0] != deadlines[1]:
        note = (f"ClassAction.org says {cao.deadline:%b %d}, OpenClassActions says "
                f"{oca.deadline:%b %d}; confirm on the official site")
    states = list(oca.states) if oca else []
    for code in (states_in_parentheses(cao.name if cao else "")
                 + states_in_parentheses(oca.name if oca else "")
                 + states_in_text(cao.blurb if cao else "")
                 + states_in_text(oca.details if oca else "")):
        if code not in states:
            states.append(code)
    text = " ".join(filter(None, [cao.name if cao else "", cao.blurb if cao else "",
                                  oca.name if oca else "", oca.details if oca else ""]))
    kind, label = classify_kind(text, oca.category if oca else "")
    tier, tier_note = _listing_tier(cao, oca)
    links = {}
    if cao:
        links["ClassAction.org"] = cao.page_url
    if oca:
        links["OpenClassActions"] = oca.url
    return Settlement(
        key=aliases[0], aliases=aliases,
        name=cao.name if cao else oca.name,
        who=(cao.blurb if cao and cao.blurb else (oca.details if oca else "")),
        payout=(cao.payout if cao and cao.payout else ""),
        payout_note="",
        # (skip one-word blurbs like "No proof": the tier badge already says that)
        summary=(oca.details if oca and cao and len(oca.details) >= 30
                 and oca.details != cao.blurb else ""),
        deadline=min(deadlines) if deadlines else None,
        deadline_note=note,
        states=states,
        category=oca.category if oca else "",
        kind=kind, group_label=label,
        tier=tier, tier_note=tier_note,
        official_url=strip_tracking(cao.official_url) if cao and cao.official_url else None,
        claim_url=None, link_note="",
        links=links,
        company=_company(cao, oca),
        excluded="" if tier else tier_note,
        cao=cao, oca=oca,
    )


def build(cao_items: list[CaoItem], oca_rows: list[OcaRow], strict_rows: list[OcaRow],
          today: date, home_states: list[str]) -> list[Settlement]:
    """All settlements with open deadlines. Ones that can't apply get `excluded` set."""
    oca_by_url = {r.url: r for r in oca_rows}
    for row in strict_rows:  # the strict no-proof page is the more careful label
        twin = oca_by_url.get(row.url) or next(
            (r for r in oca_rows
             if same_case_score(r.name, r.deadline, row.name, row.deadline) >= 0.5), None)
        if twin:  # same case, sometimes under a second URL
            twin.strict_no_proof = True
        else:
            oca_by_url[row.url] = row
    all_oca = list(oca_by_url.values())
    pairs = pair_sources(cao_items, all_oca)
    paired = {row.url for row in pairs.values()}
    settlements = [_make(c, pairs.get(c.slug)) for c in cao_items]
    settlements += [_make(None, o) for o in all_oca if o.url not in paired]
    open_ones = []
    for s in settlements:
        if s.deadline and s.deadline < today:
            continue
        apply_state_rule(s, home_states)
        open_ones.append(s)
    return open_ones


def apply_state_rule(s: Settlement, home_states: list[str]) -> None:
    if s.excluded or not s.states or not home_states:
        return
    if not set(s.states) & set(home_states):
        s.excluded = f"Only for {', '.join(s.states)}"


# -- detail pages ----------------------------------------------------------------------

def _site(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_site(a: str | None, b: str | None) -> bool:
    ha, hb = host_of(a), host_of(b)
    return bool(ha and hb and _site(ha) == _site(hb))


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def _parse_long_date(text: str) -> date | None:
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


_FAQ_PICK_RX = re.compile(r"receipt|proof|notice|need|required|how (?:do|can) i (?:file|claim)|"
                          r"claim form|who (?:is|qualif)", re.I)


def apply_detail(s: Settlement, d: OcaDetail, today: date) -> None:
    """Refine tier, links, payout and deadline from an OpenClassActions detail page."""
    s.detail = d
    s.status = d.fact("Status")[0]
    if re.search(r"\bclosed\b|claims? (?:period )?(?:has )?ended|payments? (?:issued|sent)|"
                 r"distribution", s.status, re.I) and s.tier != TIER_AUTOMATIC:
        s.excluded = "Claims closed (per case page)"
    value, sub = d.fact("Proof")
    if value:
        refined = tier_from_text(value, sub)
        if refined:
            tier, note = refined
            if tier is None:
                s.tier, s.excluded = None, EXCLUDED_DOCS
            else:
                s.tier = tier
            s.tier_note = note

    # Links: never taken from anywhere but the parsed hrefs; the claim link must be on the
    # same site as the official website or it isn't shown.
    official = s.official_url or d.official_url or (_origin(d.claim_url) if d.claim_url else None)
    s.official_url = official
    if d.claim_url and same_site(d.claim_url, official):
        s.claim_url = d.claim_url
    elif d.claim_url:
        s.link_note = (f"The two directories point to different sites ({host_of(official)} vs "
                       f"{host_of(d.claim_url)}); go through the official site shown here")

    pay_value, pay_sub = d.fact("Payout", "Payment", "Award", "Refund")
    if pay_value:
        s.payout, s.payout_note = pay_value, pay_sub

    dl_value, dl_sub = d.fact("Claim Deadline", "Deadline")
    s.deadline_text = dl_value
    automatic_words = re.compile(r"no claim form (?:is )?(?:required|needed)|nothing to file|"
                                 r"paid automatically|payment is automatic|automatic payment", re.I)
    if s.tier != TIER_AUTOMATIC and (automatic_words.search(f"{dl_value} · {dl_sub}")
                                     or re.search(r"automatic", s.status, re.I)):
        s.tier, s.tier_note = TIER_AUTOMATIC, dl_sub or s.status
    if s.tier == TIER_AUTOMATIC and _PARTIAL_AUTO_RX.search(f"{value} · {sub} · {dl_value} · {dl_sub}"):
        # e.g. Amazon Returns: paid automatically if Amazon's records identify you, everyone
        # else files a claim form -- that's a claim to act on, not "nothing to do"
        s.tier = TIER_PARTIAL_AUTO
        s.deadline_note = dl_sub
    parsed = _parse_long_date(dl_value)
    if parsed and s.tier != TIER_AUTOMATIC:
        if s.deadline and parsed != s.deadline and not s.deadline_note:
            s.deadline_note = (f"Directory listing says {s.deadline:%b %d}, the case page says "
                               f"{parsed:%b %d}; confirm on the official site")
        s.deadline = min(parsed, s.deadline) if s.deadline else parsed
    if s.tier == TIER_AUTOMATIC and (dl_value or dl_sub):
        # e.g. "October 26, 2026: Also the objection deadline · no claim deadline exists", or
        # "December 1, 2026: claim form opens by October 2" -- worth reading either way
        s.deadline_note = f"Dates: {dl_value}{': ' + dl_sub if dl_sub else ''}"

    for question, answer in d.faq:
        if _FAQ_PICK_RX.search(question) and answer:
            s.faq_hint = _trim(answer, 360)
            break
    s.payment_methods = d.payment_methods


def merge_by_site(settlements: list[Settlement], today: date,
                  home_states: list[str]) -> list[Settlement]:
    """Join a ClassAction.org-only case with an OpenClassActions-only case when both point at
    the same official website (names can differ completely, e.g. 'Domestic Flight Antitrust'
    vs 'US Domestic Airlines Price Fixing')."""
    cao_only = [s for s in settlements if s.cao and not s.oca and s.official_url]
    oca_only = [s for s in settlements if s.oca and not s.cao and s.official_url]
    replaced: dict[int, Settlement] = {}
    dropped: set[int] = set()
    for a in cao_only:
        for b in oca_only:
            if id(b) in dropped:
                continue
            if same_site(a.official_url, b.official_url) and name_tokens(a.name) & name_tokens(b.name):
                joined = _make(a.cao, b.oca)
                if b.detail:
                    apply_detail(joined, b.detail, today)
                apply_state_rule(joined, home_states)
                replaced[id(a)] = joined
                dropped.add(id(b))
                break
    return [replaced.get(id(s), s) for s in settlements if id(s) not in dropped]


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return (cut[: end + 1] if end > limit * 0.5 else cut.rsplit(" ", 1)[0] + "…")
