"""Report rendering and the optional Claude matcher (with a fake client: no API calls)."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from caf import ai, merge, report, sources

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 22)


def page(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture()
def settlements():
    built = merge.build(sources.parse_cao_listing(page("cao_settlements.html")),
                        sources.parse_oca_directory(page("oca_directory.html")),
                        sources.parse_oca_no_proof(page("oca_no_proof.html")), TODAY, ["TX"])
    for s in built:
        s.first_seen = TODAY
    return built


def test_render(settlements):
    html = report.render(settlements, today=TODAY, home_states=["TX"],
                         stats={"sources": {"cao": 210, "oca": 255}}, first_run=True)
    assert html.startswith("<!doctype html>") and html.endswith("</html>")
    for anchor in ('id="consumer"', 'id="breach"', 'id="automatic"', 'id="groups"', 'id="excluded"'):
        assert anchor in html
    assert "Dr. Squatch" in html
    assert "None" not in html.replace("NoneType", "")
    assert "Search Gmail · batch 1" in html
    assert "penalty of perjury" in html


def test_breach_batches_stay_short(settlements):
    breach = [s for s in settlements if s.kind == merge.KIND_BREACH and not s.excluded]
    batches = report.breach_batches(breach)
    assert len(batches) > 1 and all(len(q) <= 380 for q in batches)
    assert sum(q.count('"') for q in batches) // 2 >= len(breach)


def _fake_client(verdicts: dict[str, str]):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        listing = kwargs["messages"][0]["content"]
        ids = [line.split(": ", 1)[1] for line in listing.splitlines() if line.startswith("id: ")]
        results = [{"id": i, "verdict": verdicts.get(i, "unlikely"), "reason": "r", "question": "q?"}
                   for i in ids]
        return SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10_000, output_tokens=2_000,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=json.dumps({"results": results}))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    return client, calls


def test_matcher_request_shape_and_cache(settlements):
    client, calls = _fake_client({"s0": "likely", "s1": "maybe"})
    m = ai.Matcher("sk-test", client=client, budget_usd=100)
    cache: dict = {}
    m.match(settlements, "Google account", cache)
    req = calls[0]
    assert req["model"] == "claude-opus-5"
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["output_config"]["effort"] == "low"
    todo = [s for s in settlements if not s.excluded and s.tier != merge.TIER_AUTOMATIC]
    assert all(s.ai.get("verdict") for s in todo)
    assert len(calls) == -(-len(todo) // ai.BATCH_SIZE)
    # second run with the same profile hits the cache: no new calls
    for s in settlements:
        s.ai = {}
    before = len(calls)
    ai.Matcher("sk-test", client=client, budget_usd=100).match(settlements, "Google account", cache)
    assert len(calls) == before
    html = report.render(settlements, today=TODAY, home_states=["TX"], stats={}, first_run=True)
    assert 'id="likely"' in html and 'id="maybe"' in html


def test_matcher_budget_stop_keeps_items_visible(settlements, monkeypatch):
    monkeypatch.setattr(ai, "BATCH_SIZE", 5)     # several batches, so the cap has room to bite
    client, calls = _fake_client({})
    m = ai.Matcher("sk-test", client=client, budget_usd=0.01)   # one call exceeds this
    note = m.match(settlements, "Google account", {})
    assert len(calls) == 1 and "Stopped early" in note
    todo = [s for s in settlements if not s.excluded and s.tier != merge.TIER_AUTOMATIC]
    assert all(s.ai.get("verdict") in ("likely", "maybe", "unlikely") for s in todo)
