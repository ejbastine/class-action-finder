"""Parsers against excerpts of the real pages (captured 2026-09-22, trimmed to the cases the
tests use so the repo doesn't redistribute whole pages)."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from caf import sources

FIX = Path(__file__).parent / "fixtures"


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cao():
    return sources.parse_cao_listing(page("cao_settlements.html"))


@pytest.fixture(scope="module")
def oca():
    return sources.parse_oca_directory(page("oca_directory.html"))


def test_cao_counts_and_dedupes_featured_cards(cao):
    # 39 cards on the page: the 3 "Featured" ones appear twice
    assert page("cao_settlements.html").count("settlement-card") == 39
    assert len(cao) == 36
    assert len({c.slug for c in cao}) == 36
    assert Counter(c.proof for c in cao) == {"No": 29, "N/A": 4, "Yes": 3}


def test_cao_fields(cao):
    flo = next(c for c in cao if c.slug == "flo-app-data-privacy")
    assert flo.name == "FLO App - Data Privacy"
    assert flo.deadline == date(2026, 10, 15)
    assert flo.proof == "No"
    assert flo.official_url == "https://periodtrackerdataprivacylitigation.com/home/"
    assert flo.blurb.startswith("You may be included in this settlement if you used the FLO app")
    lands = next(c for c in cao if c.slug == "lands-end-data-breach")
    assert lands.name == "Lands’ End - Data Breach"      # UTF-8 survives
    varies = [c for c in cao if c.deadline_text == "Varies"]
    assert varies and all(c.deadline is None for c in varies)


def test_oca_directory(oca):
    assert len(oca) == 30
    assert Counter(r.proof for r in oca) == {"required": 20, "none": 7, "automatic": 3}
    gotham = next(r for r in oca if "gotham-steel" in r.url)
    assert gotham.states == ["CA", "CO"]
    assert gotham.deadline == date(2026, 9, 25)
    assert gotham.slug == "gotham-steel-granite-stone-bell-howell-cookware-settlement"


def test_oca_no_proof_page():
    rows = sources.parse_oca_no_proof(page("oca_no_proof.html"))
    assert len(rows) == 10
    assert all(r.strict_no_proof and r.proof == "none" for r in rows)
    mg = next(r for r in rows if "mg217" in r.url)
    assert mg.deadline == date(2026, 9, 24)
    # this page writes regions as "US-CA CO"; normalized the same as "US-CA US-CO"
    assert next(r for r in rows if "gotham-steel" in r.url).states == ["CA", "CO"]


def test_oca_detail_gotham():
    d = sources.parse_oca_detail(page("oca_detail_gotham.html"))
    assert d.fact("Proof")[0] == "No"
    assert "Notice ID field" in d.fact("Proof")[1]
    assert d.claim_url == "https://www.stainless-steelcookwaresettlement.com/claim"   # utm removed
    assert d.official_url == "https://www.stainless-steelcookwaresettlement.com/"
    assert d.fact("Payout") == ("$6 per product", d.fact("Payout")[1])
    assert len(d.faq) >= 5
    assert {"PayPal", "Venmo", "Zelle", "virtual card", "check"} <= set(d.payment_methods)
    assert d.status_text.startswith("Claims are open.")


def test_oca_detail_without_official_link():
    d = sources.parse_oca_detail(page("oca_detail_landsend.html"))
    assert d.official_url is None
    assert d.claim_url == "https://www.LandsEndDataSettlement.com/"
    assert d.fact("Proof")[0].startswith("Yes (Login ID & PIN")
    assert d.fact("Payout", "Payment")[0].startswith("~$60")


@pytest.mark.parametrize("text,expected", [
    ("You may be included in this settlement if you live in California or Pennsylvania and "
     "conducted search queries", ["CA", "PA"]),
    ("people who bought Boohoo products outside of California", []),
    ("Current Illinois residents who used the app", ["IL"]),
    ("a residential mortgage loan securing a property in North Carolina that was serviced", ["NC"]),
    ("anyone who bought a covered pan or pot in California or Colorado", ["CA", "CO"]),
    ("New York City residents who were detained", []),
])
def test_states_in_text(text, expected):
    assert sources.states_in_text(text) == expected


def test_states_in_parentheses_and_normalize():
    assert sources.states_in_parentheses("Tesla - Idle Fees (California)") == ["CA"]
    assert sources.states_in_parentheses("Washington Nationals - Discount Tickets") == []
    assert sources.normalize_states("US-CA US-CT US-DE") == ["CA", "CT", "DE"]
    assert sources.normalize_states("") == []


def test_strip_tracking_and_host():
    url = "https://x.example.com/claim?utm_source=openclassactions.com&id=7"
    assert sources.strip_tracking(url) == "https://x.example.com/claim?id=7"
    assert sources.host_of("https://www.LandsEndDataSettlement.com/") == "landsenddatasettlement.com"
