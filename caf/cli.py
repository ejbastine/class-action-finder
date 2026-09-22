"""Command line: `python -m caf run` builds the report; `python -m caf key ...` manages the
optional Anthropic API key used by `run --match`."""

from __future__ import annotations

import argparse
import getpass
import logging
import shutil
import sys
import webbrowser
from datetime import datetime

from . import config, credentials, pipeline, profile, report
from .fetch import Fetcher
from .state import State


def _run(args: argparse.Namespace) -> int:
    today = datetime.now(config.TZ).date()
    if not config.PROFILE_PATH.exists() and config.PROFILE_TEMPLATE_PATH.exists():
        shutil.copyfile(config.PROFILE_TEMPLATE_PATH, config.PROFILE_PATH)
        print(f"Created {config.PROFILE_PATH.name} from the template. Put your states in it "
              "(e.g. states = [\"NY\"]) to hide settlements limited to other states.")
    prof = profile.load(config.PROFILE_PATH)
    if prof.bad_states:
        print(f"Ignoring unknown state codes in profile.toml: {', '.join(prof.bad_states)}")
    print(f"Reading settlement directories (state filter: {', '.join(prof.states) or 'none'})…")

    def progress(done: int, total: int) -> None:
        print(f"\rReading case pages {done}/{total}", end="", flush=True)
        if done == total:
            print()

    fetcher = Fetcher(offline=args.offline)
    try:
        settlements, stats = pipeline.collect(fetcher, today, prof.states, progress)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        fetcher.close()
    for warning in stats["warnings"]:
        print(f"Warning: {warning}")

    state = State(config.STATE_PATH)
    first_run = state.first_run
    state.stamp_first_seen(settlements, today)

    ai_note = ""
    if args.match:
        ai_note = _match(settlements, prof, state, args.budget)
        if ai_note.startswith("Error"):
            print(ai_note)
            return 1
        print(ai_note)

    page = report.render(settlements, today=today, home_states=prof.states, stats=stats,
                         first_run=first_run, ai_note=ai_note)
    config.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.REPORT_PATH.write_text(page, encoding="utf-8")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(report.to_json(settlements))
    state.save()

    print(report.console_summary(settlements, today, str(config.REPORT_PATH)))
    if not args.no_open:
        webbrowser.open(config.REPORT_PATH.as_uri())
    return 0


def _match(settlements, prof: profile.Profile, state: State, budget: float) -> str:
    key = credentials.get_api_key()
    if not key:
        return ("Error: --match needs an Anthropic API key. Store one with "
                "`python -m caf key set` (or put ANTHROPIC_API_KEY=... in .env).")
    if not prof.has_facts:
        return ("Error: --match needs facts to match against. Fill in profile.toml "
                "(accounts, products, devices, notices…) first.")
    from .ai import Matcher  # imported lazily so the free run never needs the SDK
    matcher = Matcher(key, budget_usd=budget)
    print(f"Matching with {matcher.model} (cap ${budget:.2f})…")
    return matcher.match(settlements, prof.facts, state.ai_cache, progress=lambda m: print(f"  {m}"))


def _key(args: argparse.Namespace) -> int:
    if args.action == "status":
        print(f"ANTHROPIC_API_KEY resolves from: {credentials.source()}")
    elif args.action == "set":
        value = getpass.getpass("Anthropic API key (input hidden): ").strip()
        if not value:
            print("Nothing stored.")
            return 2
        credentials.set_api_key(value)
        print("Stored in Windows Credential Manager (service 'class-action-finder').")
    elif args.action == "delete":
        print("Deleted." if credentials.delete_api_key() else "No stored key.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(
        prog="python -m caf",
        description="Find open US class action settlements you can claim with little or no proof.")
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="build the report (the default)")
    run.add_argument("--match", action="store_true",
                     help="rank settlements against profile.toml with Claude (uses API credits)")
    run.add_argument("--budget", type=float, default=config.MAX_RUN_COST_USD,
                     help=f"max USD for Claude this run (default {config.MAX_RUN_COST_USD:.2f})")
    run.add_argument("--offline", action="store_true", help="use cached pages only")
    run.add_argument("--no-open", action="store_true", help="don't open the report in a browser")
    run.add_argument("--json", metavar="PATH", help="also write the results as JSON")
    key = sub.add_parser("key", help="manage the Anthropic API key for --match")
    key.add_argument("action", choices=["status", "set", "delete"])

    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv) or ["run"])
    if args.cmd == "key":
        return _key(args)
    return _run(args)
