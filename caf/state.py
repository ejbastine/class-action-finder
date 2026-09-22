"""data/state.json -- when each case was first seen (for NEW badges) and cached Claude answers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .merge import Settlement


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self.data = {}
        self.data.setdefault("runs", 0)
        self.data.setdefault("first_seen", {})
        self.data.setdefault("ai", {})

    @property
    def first_run(self) -> bool:
        return self.data["runs"] == 0

    @property
    def ai_cache(self) -> dict:
        return self.data["ai"]

    def stamp_first_seen(self, settlements: list[Settlement], today: date) -> None:
        """Set first_seen, and is_new for cases no earlier run has seen under any alias."""
        seen = self.data["first_seen"]
        before = set(seen)
        for s in settlements:
            known = [date.fromisoformat(seen[a]) for a in s.aliases if a in seen]
            s.first_seen = min(known) if known else today
            s.is_new = not self.first_run and not any(a in before for a in s.aliases)
            for alias in s.aliases:
                seen.setdefault(alias, s.first_seen.isoformat())

    def save(self) -> None:
        self.data["runs"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
