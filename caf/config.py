"""Paths and settings. Importing this loads `.env` into the environment (real env vars win)."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
PAGE_CACHE_DIR = DATA_DIR / "pages"
STATE_PATH = DATA_DIR / "state.json"        # first-seen dates + cached Claude results
PROFILE_PATH = ROOT / "profile.toml"                  # yours; git-ignored
PROFILE_TEMPLATE_PATH = ROOT / "profile.example.toml"  # blank template, copied on first run
REPORT_PATH = Path(os.environ.get("CAF_REPORT_PATH") or ROOT / "report.html")

# Claim deadlines are calendar days; administrators are mostly US-Eastern.
TZ = ZoneInfo("America/New_York")

# A normal browser UA plus our own token, so site owners can still tell what we are.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0 Safari/537.36 class-action-finder/0.1")
# Which signed-in Google account the report's Gmail searches open: "0" is the first account
# you signed into; an email address picks that mailbox explicitly.
GMAIL_ACCOUNT = os.environ.get("CAF_GMAIL_ACCOUNT", "0").strip() or "0"

LISTING_TTL_HOURS = 6          # directory pages
DETAIL_TTL_HOURS = 24 * 5      # per-case pages (deadlines are re-read from the listings every run)
REQUEST_GAP_SECONDS = 0.8      # minimum spacing between requests to the same host

# -- Claude matching (optional: only with `run --match`) --------------------------------
MODEL = os.environ.get("CAF_MODEL", "claude-opus-5")
EFFORT = os.environ.get("CAF_EFFORT", "low")
MAX_RUN_COST_USD = float(os.environ.get("CAF_MAX_RUN_COST_USD", "3.00"))
# USD per million tokens (input, output), from the claude-api model table (June 2026).
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}
