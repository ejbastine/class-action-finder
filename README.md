# class-action-finder

Finds open US class action settlements you can claim with **little or no evidence**: no
receipts, and at most the ID printed on a notice you were sent. It turns them into one
actionable HTML report: who qualifies, the deadline, the payout, what the claim form asks
for, and a link to the official claim site.

## Setup (once)

Needs Python 3.11 or newer.

```powershell
git clone https://github.com/ejbastine/class-action-finder.git
cd class-action-finder
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS/Linux, use `.venv/bin/python` in place of `.venv\Scripts\python.exe` throughout.

## Run it

On Windows, double-click `run.cmd`. Or run:

```powershell
.venv\Scripts\python.exe -m caf run          # builds report.html and opens it
.venv\Scripts\python.exe -m caf run --help   # --offline, --no-open, --json PATH, --match
```

The first run creates `profile.toml` from `profile.example.toml`. Put your state(s) in it
(`states = ["NY"]`) and run again. That hides settlements limited to other states.

The first run reads about 150 case pages (~2 minutes). Pages are cached under `data/`, so
later runs are quicker. Directory listings refresh every 6 hours and case pages every 5 days.
`profile.toml`, `.env`, `data/` and `report.html` are git-ignored, so your details stay on
your machine.

## What counts as "minimal evidence"

| Badge | Meaning |
|---|---|
| **No receipts · no ID** | Sign-only: name, contact info, what you bought or used; you attest under penalty of perjury |
| **ID from your notice** | No documents, but you need the Claim/Notice ID (and often a PIN) that was mailed or emailed to class members. Typical for data breaches |
| **No receipts (unverified)** | Only ClassAction.org lists it, as "no proof required"; check the official FAQ for an ID requirement |
| **Automatic for most** | Paid automatically if the company's records identify you; everyone else can file a claim form |
| **Automatic** | No claim form at all; class members are paid automatically |

Settlements that need receipts or other records for the basic payment are left out. So are
settlements that are closed, not open yet, or limited to states you haven't lived in. The
footer of the report lists what was left out and why.

## The report

- **Products & services.** Consumer settlements anyone could be in, as cards sorted by deadline.
- **Data breaches.** You're only in these if you were notified. One-click Gmail searches
  check batches of company names for a notice. The searches open your *first* signed-in
  Google account. If you're signed into more than one, set `CAF_GMAIL_ACCOUNT=you@gmail.com`
  in `.env` so they search the right mailbox.
- **Automatic payments** and **Specific groups** (employees, patients of one provider,
  tenants, people who got certain calls or texts…) are collapsed lists.
- **That's me / Filed ✓ / Not me** buttons are saved in your browser (localStorage). They
  carry over between runs as long as you open the report from the same path.

## Your profile (`profile.toml`)

`states` is used on every run and costs nothing. Settlements limited to other states are
dropped. Everything else in the file is used **only** by `run --match`.

### Optional: `--match` (Claude API)

`run --match` sends your profile facts and each settlement's short directory summary to
Claude. Claude sorts every claimable settlement into *likely you / worth a look / probably
not*, with a yes/no confirmation question for each.

- Set a key once with `.venv\Scripts\python.exe -m caf key set`. It's stored in your OS
  keychain (Windows Credential Manager, macOS Keychain). Or put `ANTHROPIC_API_KEY=` in `.env`.
- Defaults: model `claude-opus-5`, effort `low`, and a spend cap of `$3.00` per run
  (`--budget`, or `CAF_MAX_RUN_COST_USD`). Answers are cached per profile and settlement,
  so later runs only pay for new settlements. `CAF_MODEL=claude-sonnet-5` or
  `claude-haiku-4-5` costs less.
- Server-side refusal fallback (`fallbacks: "default"`) is on, so a declined request is
  retried on a fallback model instead of failing.
- Page HTML is never sent to Claude, and nothing Claude returns is used as a link.

## Where the data comes from

- **ClassAction.org** `/settlements`: proof-required flag, deadline, eligibility blurb and a
  link to the official site.
- **OpenClassActions.com**: its directory, its strict no-proof list, and per-case pages whose
  "Proof Required" box separates receipts from notice IDs.

Both are independent directories, not settlement administrators. Claim links are copied
from them, and a claim link is shown only when it is on the official site's domain. Always
confirm the deadline and the class definition on the official site before you file.
TopClassActions is not used because it blocks automated requests.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

The parsers are tested against excerpts of the real pages in `tests/fixtures`, captured
2026-09-22 and trimmed to the cases the tests use. If a site changes its layout, the run
prints a warning ("loaded but no settlements were found") and the parser needs updating.

## Weekly refresh (optional, Windows)

Replace the path with wherever you cloned the repo:

```powershell
schtasks /Create /SC WEEKLY /D SUN /ST 09:00 /TN "Class action report" /TR "\"C:\path\to\class-action-finder\run.cmd\" --no-open"
```

## Disclaimer

This isn't legal advice. Only file claims you actually qualify for, because claim forms are
signed under penalty of perjury.
