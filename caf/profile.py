"""profile.toml -- facts about you. The free run only reads `states`; `run --match` also sends
the rest to Claude to rank which settlements are likely yours."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .sources import US_STATES


@dataclass
class Profile:
    states: list[str]
    facts: str              # every other filled-in value, as "section / key: value" lines
    bad_states: list[str]

    @property
    def has_facts(self) -> bool:
        return bool(self.facts.strip())


def load(path: Path) -> Profile:
    if not path.exists():
        return Profile(states=[], facts="", bad_states=[])
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_states = [str(s).strip().upper() for s in data.get("states", [])]
    lines: list[str] = []

    def walk(prefix: str, node: dict) -> None:
        for key, value in node.items():
            if not prefix and key == "states":
                continue
            name = f"{prefix}{key}"
            if isinstance(value, dict):
                walk(f"{name} / ", value)
            elif isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                if items:
                    lines.append(f"{name}: {', '.join(items)}")
            elif isinstance(value, str):
                if value.strip():
                    lines.append(f"{name}:\n{value.strip()}")
            elif value not in (0, False, None):
                lines.append(f"{name}: {value}")

    walk("", data)
    return Profile(states=[s for s in raw_states if s in US_STATES],
                   facts="\n".join(lines),
                   bad_states=[s for s in raw_states if s and s not in US_STATES])
