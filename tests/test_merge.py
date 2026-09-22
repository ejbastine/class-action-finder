"""Pairing, evidence tiers, state filtering and link safety."""

import copy
from datetime import date
from pathlib import Path

import pytest

from caf import merge, sources
from caf.merge import TIER_ATTEST, TIER_AUTOMATIC, TIER_NOTICE, TIER_UNVERIFIED

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 22)


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed():
    return (sources.parse_cao_listing(page("cao_settlements.html")),
            sources.parse_oca_directory(page("oca_directory.html")),
            sources.parse_oca_no_proof(page("oca_no_proof.html")))


@pytest.fixture(scope="module")
def built(parsed):
    cao, oca, strict = parsed
    return merge.build(cao, oca, strict, TODAY, ["TX"])


def by_alias(settlements, alias):
    return next(s for s in settlements if alias in s.aliases)


def test_known_pairs(parsed):
    cao, oca, strict = parsed
    pairs = merge.pair_sources(cao, oca + strict)
    assert "lands-end-data-breach" in pairs["lands-end-data-breach"].url
    assert "dr-squatch" in pairs["dr-squatch-all-natural-claims"].url
    # completely different names, same case (matched on "steel"/"cookware" + same deadline)
    assert "gotham-steel" in pairs["mishan-and-sons-stainless-steel-cookware"].url
    assert "flo" in pairs["flo-app-data-privacy"].url.lower()


def test_no_duplicate_listings(built):
    aliases = [a for s in built for a in s.aliases]
    assert len(aliases) == len(set(aliases))


@pytest.mark.parametrize("value,sub,tier", [
    ("No", "Attestation under penalty of perjury · no receipts, and the Notice ID field on the "
           "online form is optional", TIER_ATTEST),
    ("Yes (Login ID & PIN from Notice)", "online filing requires the Login ID & PIN printed on your "
     "mailed notice · the ~$60 cash needs no documentation, but documented losses up to $5,000 "
     "require receipts", TIER_NOTICE),
    ("Yes", "LoginID and PIN from the mailed notice to file online", TIER_NOTICE),
    ("Automatic Payment", "No claim form to file", TIER_AUTOMATIC),
    ("Yes", "Receipts or other proof of purchase required for every claim", None),
    ("No", "Claim ID from your notice is required to file online", TIER_NOTICE),
    # documents only for an optional bigger tier: the basic payment needs just the notice ID
    ("Yes", "LoginID and PIN from your notice to file online · receipts or statements for the "
            "$2,000 tier", TIER_NOTICE),
    ("Yes", "Settlement Claim ID from the mailed or emailed notice · no medical records or receipts",
     TIER_NOTICE),
    ("Yes", "Class Member ID from the notice to file online · purchase records only to amend the "
            "amounts", TIER_NOTICE),
    ("Yes", "Reasonable Documentation for the $5,000 tier · have the notice you were sent in front "
            "of you when you file", TIER_NOTICE),
    ("Yes", "Unique ID & PIN from your mailed notice to file online, optional on the mailed paper "
            "form · receipts or records for the up-to-$5,000 documented-loss tier", TIER_NOTICE),
    ("Yes", "Notice ID & Confirmation Code to file online · documentation required for claims of "
            "$8,000 or more", TIER_NOTICE),
    # "No" + an ID that is explicitly optional: sign-only
    ("No", "sworn attestation; you can file without a Unique ID or PIN (California 2× share may "
           "require residency documentation)", TIER_ATTEST),
    ("No", "Up to $5 without documents or a notice ID; proof for up to $10", TIER_ATTEST),
    ("No", "The $40 payment needs no documentation or explanation, and the settlement website links "
           "an open claim form that can be filed without the LoginID and PIN from the notice",
     TIER_ATTEST),
    # online form gated on the ID; a paper route exists -> still "ID from your notice"
    ("Yes — ID to file online", "A LoginID and PIN from the notice are required to open the online "
     "form · a paper form can be mailed without one · receipts needed for the loss tier, but not "
     "for the $40", TIER_NOTICE),
    ("Yes — ID to file online", "no receipts for the $50 tier, but the online form opens on a Login "
     "ID and PIN screen · a printed form mailed in treats the Notice ID as optional", TIER_NOTICE),
    ("Yes — ID to file online", "The online claim form will not open without the Settlement Claim ID "
     "from the notice; the printable form asks for the Notice ID only if known. No receipts are "
     "needed for the cash payment", TIER_NOTICE),
    # no notice? the portal emails you a code instead -> no notice needed
    ("Yes — a portal code", "no receipts for a one-unit claim, but the portal asks first for a Notice "
     "ID and Confirmation Code; without a notice you register an email address to be sent a code "
     "before you can reach the claim form", TIER_ATTEST),
])
def test_tier_from_text(value, sub, tier):
    assert merge.tier_from_text(value, sub)[0] == tier


def test_partial_automatic_is_a_claim(built):
    """'Automatic for most' (Amazon Returns-style) must not hide in the nothing-to-do list."""
    s = copy.deepcopy(by_alias(built, "cao:dr-squatch-all-natural-claims"))
    d = sources.OcaDetail(
        title="", status_text="", faq=[], payment_methods=[], claim_url=None, official_url=None,
        facts={"Status": ("Preliminary Approval Granted", ""),
               "Claim Deadline": ("December 1, 2026", "claim form opens by October 2, 2026"),
               "Proof Required": ("Automatic Payment for most", "no claim form at all for anyone "
                                  "the records identify · everyone else files a claim form")})
    merge.apply_detail(s, d, TODAY)
    assert s.tier == merge.TIER_PARTIAL_AUTO
    assert s.deadline == date(2026, 11, 27)      # earlier listing deadline kept (min), noted
    assert "claim form opens" in s.deadline_note


def test_detail_pages_refine_tiers(built):
    lands = by_alias(built, "cao:lands-end-data-breach")
    merge.apply_detail(lands, sources.parse_oca_detail(page("oca_detail_landsend.html")), TODAY)
    assert lands.tier == TIER_NOTICE and not lands.excluded
    assert lands.claim_url == "https://www.LandsEndDataSettlement.com/"   # same site as CAO's link
    assert lands.kind == merge.KIND_BREACH

    olinsky = by_alias(built, "cao:olinsky-and-associates-data-breach")
    merge.apply_detail(olinsky, sources.parse_oca_detail(page("oca_detail_olinsky.html")), TODAY)
    assert olinsky.tier == TIER_AUTOMATIC


def test_state_filter(built):
    gotham = by_alias(built, "cao:mishan-and-sons-stainless-steel-cookware")
    assert gotham.states == ["CA", "CO"] and gotham.excluded == "Only for CA, CO"
    labcorp = by_alias(built, "cao:laboratory-corporation-of-america-data-privacy")
    assert labcorp.excluded.startswith("Only for")
    squatch = by_alias(built, "cao:dr-squatch-all-natural-claims")
    assert not squatch.excluded and squatch.tier == TIER_ATTEST


def test_proof_required_is_excluded(built):
    yes_only = [s for s in built if s.cao and s.cao.proof == "Yes" and not s.oca]
    assert yes_only and all(s.excluded == merge.EXCLUDED_DOCS for s in yes_only)
    assert all(s.tier is None for s in built if s.excluded == merge.EXCLUDED_DOCS)


def test_cao_only_no_proof_is_unverified(built):
    orphans = [s for s in built if s.cao and not s.oca and s.cao.proof == "No" and not s.excluded]
    assert orphans and all(s.tier == TIER_UNVERIFIED for s in orphans)


def test_expired_deadlines_dropped(parsed):
    cao, oca, strict = parsed
    later = merge.build(cao, oca, strict, date(2026, 10, 16), [])
    assert not any(s.deadline and s.deadline < date(2026, 10, 16) for s in later)


def test_claim_link_must_match_official_site(built):
    s = by_alias(built, "cao:lands-end-data-breach")
    d = sources.parse_oca_detail(page("oca_detail_landsend.html"))
    d.claim_url = "https://lands-end-claims.example.net/file"      # a different domain
    s.claim_url = None
    merge.apply_detail(s, d, TODAY)
    assert s.claim_url is None and "different sites" in s.link_note
    assert s.official_url == "https://landsenddatasettlement.com/"


def test_kinds(built):
    assert by_alias(built, "cao:dr-squatch-all-natural-claims").kind == merge.KIND_CONSUMER
    assert by_alias(built, "cao:the-money-source-unwanted-calls").kind == merge.KIND_GROUP
    assert by_alias(built, "cao:equinox-data-breach").kind == merge.KIND_BREACH
