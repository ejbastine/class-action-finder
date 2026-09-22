"""NEW badges: nothing is new on the first run; later runs flag only never-seen cases."""

from datetime import date
from types import SimpleNamespace

from caf.state import State


def case(*aliases):
    return SimpleNamespace(aliases=list(aliases), first_seen=None, is_new=False)


def test_new_flags(tmp_path):
    path = tmp_path / "state.json"
    first = State(path)
    a, b = case("cao:a"), case("cao:b", "oca:b")
    first.stamp_first_seen([a, b], date(2026, 9, 22))
    assert not a.is_new and not b.is_new
    first.save()

    second = State(path)
    a2, b2, c = case("cao:a", "oca:a"), case("oca:b"), case("cao:c")
    second.stamp_first_seen([a2, b2, c], date(2026, 9, 29))
    assert not a2.is_new and not b2.is_new      # known under another alias
    assert c.is_new and c.first_seen == date(2026, 9, 29)
    assert a2.first_seen == date(2026, 9, 22)
