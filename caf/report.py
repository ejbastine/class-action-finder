"""Render the settlements as one self-contained HTML page (plus a short console summary).

The page keeps your "That's me / Filed / Not me" marks in the browser's localStorage, keyed
by each case's directory ids, so they survive re-runs as long as the report path stays the same.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime
from urllib.parse import quote

from . import config, merge
from .merge import (KIND_BREACH, KIND_CONSUMER, KIND_GROUP, TIER_ATTEST, TIER_AUTOMATIC,
                    TIER_NOTICE, TIER_PARTIAL_AUTO, TIER_UNVERIFIED, Settlement)

TIER_BADGE = {
    TIER_AUTOMATIC: ("Automatic", "t-auto"),
    TIER_PARTIAL_AUTO: ("Automatic for most", "t-auto"),
    TIER_ATTEST: ("No receipts · no ID", "t-attest"),
    TIER_NOTICE: ("ID from your notice", "t-notice"),
    TIER_UNVERIFIED: ("No receipts (unverified)", "t-unverified"),
}
TIER_NEED = {
    TIER_AUTOMATIC: "Nothing to file. If you're in the class you'll be paid; the official site may "
                    "let you update your address or choose a payment method.",
    TIER_PARTIAL_AUTO: "If the company's records identify you, you're paid automatically and may only "
                       "need to pick a payment method once notice goes out (watch your email). If "
                       "they don't, you can file a claim form; check the official site for what it "
                       "asks.",
    TIER_ATTEST: "Your name, address, email and a payment choice, plus the details the form asks "
                 "for (usually what you bought or used, and roughly when). You confirm it's true "
                 "under penalty of perjury. No receipts.",
    TIER_NOTICE: "The Claim/Notice ID (often with a PIN) printed on the notice that was emailed or "
                 "mailed to class members, plus your contact info. No receipts for the basic payment. "
                 "Search your email for it first.",
    TIER_UNVERIFIED: "ClassAction.org lists this as needing no proof of purchase. Check the official "
                     "site's FAQ for whether a Class Member/Notice ID is required before you start.",
}
FAR = date(2999, 1, 1)


def _e(text: object) -> str:
    return html.escape(str(text or ""), quote=True)


def _gmail(query: str) -> str:
    account = quote(config.GMAIL_ACCOUNT, safe="@.")
    return f"https://mail.google.com/mail/u/{account}/#search/" + quote(query, safe="")


def _company_query(company: str) -> str:
    name = company.replace('"', "")
    return f'"{name}" (settlement OR "class action" OR breach OR "data incident" OR "notice")'


def breach_batches(settlements: list[Settlement], max_len: int = 380) -> list[str]:
    """Gmail searches that each check a batch of breached companies in one go."""
    tail = ' (breach OR "data incident" OR "security incident" OR settlement)'
    batches, names = [], []
    for s in settlements:
        quoted = '"' + s.company.replace('"', "") + '"'
        if names and len(" OR ".join(names + [quoted])) + len(tail) + 2 > max_len:
            batches.append(f"({' OR '.join(names)}){tail}")
            names = []
        names.append(quoted)
    if names:
        batches.append(f"({' OR '.join(names)}){tail}")
    return batches


def _due(s: Settlement, today: date) -> tuple[str, str]:
    if s.tier == TIER_AUTOMATIC:
        return "No claim needed", "due-none"
    if not s.deadline:
        return "No deadline listed", "due-none"
    days = (s.deadline - today).days
    when = f"{s.deadline:%b} {s.deadline.day}"
    if days == 0:
        return f"{when} · due today", "due-urgent"
    label = f"{when} · {days} day{'s' if days != 1 else ''} left"
    return label, "due-urgent" if days <= 7 else "due-soon" if days <= 21 else "due-ok"


def _sort_key(s: Settlement) -> tuple:
    return (s.deadline or FAR, s.name.lower())


def _links(s: Settlement, *, compact: bool = False) -> str:
    out = []
    if s.claim_url:
        out.append(f'<a class="btn primary" href="{_e(s.claim_url)}" target="_blank" '
                   f'rel="noopener noreferrer">File claim ↗</a>')
    if s.official_url and s.official_url != s.claim_url:
        cls = "btn" if s.claim_url else "btn primary"
        out.append(f'<a class="{cls}" href="{_e(s.official_url)}" target="_blank" '
                   f'rel="noopener noreferrer">Official site ↗</a>')
    if s.tier in (TIER_NOTICE, TIER_UNVERIFIED, TIER_PARTIAL_AUTO) or s.kind == KIND_BREACH:
        out.append(f'<a class="btn ghost" href="{_e(_gmail(_company_query(s.company)))}" '
                   f'target="_blank" rel="noopener noreferrer">Search Gmail ↗</a>')
    for label, url in s.links.items():
        text = label if compact else f"{label} ↗"
        out.append(f'<a class="src" href="{_e(url)}" target="_blank" rel="noopener noreferrer">'
                   f'{_e(text)}</a>')
    return "".join(out)


def _marks() -> str:
    return ('<div class="marks">'
            '<button type="button" data-act="mine">That\'s me</button>'
            '<button type="button" data-act="filed">Filed ✓</button>'
            '<button type="button" data-act="notme">Not me</button></div>')


def _badges(s: Settlement, home_states: list[str]) -> str:
    out = []
    if s.tier in TIER_BADGE:
        text, cls = TIER_BADGE[s.tier]
        out.append(f'<span class="badge {cls}" title="{_e(s.tier_note)}">{_e(text)}</span>')
    if s.states:
        local = [c for c in s.states if c in home_states]
        cls = "st-home" if local else "st"
        out.append(f'<span class="badge {cls}">{_e(", ".join(s.states))} only</span>')
    if s.ai.get("verdict"):
        out.append(f'<span class="badge ai-{_e(s.ai["verdict"])}">'
                   f'{_e(s.ai["verdict"].capitalize())} match</span>')
    out.append('<span class="badge new" hidden>NEW</span>')
    return "".join(out)


def _card(s: Settlement, today: date, home_states: list[str], is_new: bool) -> str:
    due, due_cls = _due(s, today)
    parts = [f'<article class="card" data-keys="{_e(" ".join(s.aliases))}" '
             f'data-name="{_e(s.name)}" data-new="{int(is_new)}">',
             f'<div class="top"><span class="due {due_cls}">{_e(due)}</span>{_badges(s, home_states)}</div>',
             f'<h3>{_e(s.name)}</h3>']
    if s.ai.get("question"):
        parts.append(f'<p class="question">{_e(s.ai["question"])}</p>')
    if s.who:
        parts.append(f'<p class="who">{_e(s.who)}</p>')
    if s.summary:
        parts.append(f'<p class="muted">Summary: {_e(s.summary)}</p>')
    if s.ai.get("reason"):
        parts.append(f'<p class="why"><b>Why it\'s shown:</b> {_e(s.ai["reason"])}</p>')
    if s.payout or s.payout_note:
        pay = _e(s.payout) if s.payout and s.payout.upper() != "N/A" else ""
        note = f' <span class="muted">({_e(s.payout_note)})</span>' if s.payout_note else ""
        parts.append(f'<p><b>Payout:</b> {pay or "see site"}{note}</p>')
    need = TIER_NEED.get(s.tier, "")
    specific = s.tier_note if s.detail and s.tier_note else ""
    parts.append(f'<p><b>What you\'ll need:</b> {_e(need)}'
                 + (f' <span class="muted">Case page: “{_e(specific)}”</span>' if specific else "")
                 + "</p>")
    if s.payment_methods:
        parts.append(f'<p class="muted">Payment options mentioned: {_e(", ".join(s.payment_methods))}</p>')
    if s.faq_hint:
        parts.append(f'<details><summary>From the case FAQ</summary><p>{_e(s.faq_hint)}</p></details>')
    for note in (s.deadline_note, s.link_note):
        if note:
            parts.append(f'<p class="warn">{_e(note)}</p>')
    parts.append(f'<div class="actions">{_links(s)}</div>{_marks()}</article>')
    return "".join(parts)


def _row(s: Settlement, today: date, home_states: list[str], is_new: bool) -> str:
    due, due_cls = _due(s, today)
    pay = s.payout if s.payout and s.payout.upper() != "N/A" else ""
    extra = []
    if s.deadline_note:
        extra.append(f'<p class="warn">{_e(s.deadline_note)}</p>')
    if s.link_note:
        extra.append(f'<p class="warn">{_e(s.link_note)}</p>')
    return (f'<div class="row" data-keys="{_e(" ".join(s.aliases))}" data-name="{_e(s.name)}" '
            f'data-new="{int(is_new)}">'
            f'<div class="row-main"><div class="top"><span class="due {due_cls}">{_e(due)}</span>'
            f'{_badges(s, home_states)}</div>'
            f'<b>{_e(s.name)}</b>'
            + (f' <span class="pay">· {_e(pay)}</span>' if pay else "")
            + f'<p class="who">{_e(s.who)}</p>'
            + (f'<p class="question">{_e(s.ai["question"])}</p>' if s.ai.get("question") else "")
            + "".join(extra)
            + f'</div><div class="row-side"><div class="actions">{_links(s, compact=True)}</div>'
            f'{_marks()}</div></div>')


CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1b1f24;--muted:#5d6670;--line:#dfe3e8;--accent:#1f5eff;
--accent-ink:#fff;--red:#b42318;--red-bg:#fde8e7;--amber:#8a5a00;--amber-bg:#fff3d6;--green:#136c3a;
--green-bg:#e3f5ea;--blue-bg:#e6eeff;--gray-bg:#eef0f3;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#101317;--panel:#171b21;
--ink:#e7eaee;--muted:#9aa4af;--line:#2a3039;--accent:#6e9bff;--accent-ink:#0b1020;--red:#ff8a80;
--red-bg:#3a1714;--amber:#ffc861;--amber-bg:#35290d;--green:#7ad7a0;--green-bg:#10301f;
--blue-bg:#18264a;--gray-bg:#232830;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#101317;--panel:#171b21;--ink:#e7eaee;--muted:#9aa4af;--line:#2a3039;
--accent:#6e9bff;--accent-ink:#0b1020;--red:#ff8a80;--red-bg:#3a1714;--amber:#ffc861;--amber-bg:#35290d;
--green:#7ad7a0;--green-bg:#10301f;--blue-bg:#18264a;--gray-bg:#232830;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",
Roboto,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:28px 18px 64px}
h1{font-size:1.7rem;margin:0 0 4px}
h2{font-size:1.2rem;margin:36px 0 4px}
h3{font-size:1.05rem;margin:6px 0 6px}
.sub,.muted{color:var(--muted)}
.lede{color:var(--muted);margin:0 0 14px;max-width:70ch}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px;
text-decoration:none;color:var(--ink)}
.stat b{font-size:1.15rem;margin-right:4px}
.how{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:10px 0}
.how ol{margin:6px 0 0 18px;padding:0}
.toolbar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);padding:10px 0;
display:flex;flex-wrap:wrap;gap:14px;align-items:center;border-bottom:1px solid var(--line)}
.toolbar label{display:flex;gap:6px;align-items:center}
.toolbar input[type=search]{flex:1 1 220px;min-width:0;padding:7px 10px;border-radius:8px;
border:1px solid var(--line);background:var(--panel);color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px;margin-top:12px}
.card,.row{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card p{margin:6px 0}
.row{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:10px;justify-content:space-between}
.row-main{flex:1 1 420px;min-width:0}
.row-side{flex:0 1 300px;display:flex;flex-direction:column;gap:8px;align-items:flex-start}
.row .who{margin:4px 0 0;color:var(--muted);font-size:.93rem}
.top{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.due{font-weight:600;font-size:.85rem;padding:2px 8px;border-radius:999px;background:var(--gray-bg)}
.due-urgent{background:var(--red-bg);color:var(--red)}
.due-soon{background:var(--amber-bg);color:var(--amber)}
.due-ok{background:var(--green-bg);color:var(--green)}
.badge{font-size:.78rem;padding:2px 8px;border-radius:999px;background:var(--gray-bg);color:var(--muted)}
.t-attest{background:var(--green-bg);color:var(--green)}
.t-notice{background:var(--blue-bg);color:var(--accent)}
.t-auto{background:var(--green-bg);color:var(--green)}
.t-unverified{background:var(--amber-bg);color:var(--amber)}
.st-home{background:var(--green-bg);color:var(--green)}
.new{background:var(--accent);color:var(--accent-ink)}
.ai-likely{background:var(--green-bg);color:var(--green)}
.ai-maybe{background:var(--amber-bg);color:var(--amber)}
.question{font-weight:600}
.warn{color:var(--amber);font-size:.9rem}
.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
.row .actions{margin-top:0}
.btn{display:inline-block;padding:6px 12px;border-radius:8px;border:1px solid var(--line);
color:var(--ink);text-decoration:none;font-weight:600;font-size:.9rem;background:var(--panel)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.btn.ghost{background:transparent}
.src{font-size:.82rem;color:var(--muted)}
.marks{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.marks button{font:inherit;font-size:.82rem;padding:4px 10px;border-radius:999px;cursor:pointer;
border:1px solid var(--line);background:transparent;color:var(--muted)}
[data-state=mine] .marks [data-act=mine],[data-state=filed] .marks [data-act=filed]{
background:var(--green-bg);color:var(--green);border-color:transparent}
[data-state=notme] .marks [data-act=notme]{background:var(--gray-bg);color:var(--ink)}
[data-state=notme]{opacity:.55}
[data-state=mine]{border-color:var(--green)}
[data-state=filed]{border-color:var(--green);opacity:.8}
.hide-notme [data-state=notme],.hide-filed [data-state=filed]{display:none}
.only-new [data-new="0"]{display:none}
.searching .card:not(.hit),.searching .row:not(.hit){display:none}
details{margin:6px 0}
summary{cursor:pointer;color:var(--muted)}
.group-title{margin:22px 0 0;font-size:1rem}
.gmail-batches{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
#mine-list li,#filed-list li{margin:4px 0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-top:12px}
.excluded li{margin:2px 0}
footer{margin-top:44px;color:var(--muted);font-size:.9rem;border-top:1px solid var(--line);padding-top:16px}
footer li{margin:6px 0}
@media (max-width:520px){.wrap{padding:18px 16px 48px}h1{font-size:1.4rem}}
"""

JS = """
(function(){
  var P='caf:v1:';
  function store(){try{return window.localStorage}catch(e){return null}}
  function keysOf(el){return (el.getAttribute('data-keys')||'').split(' ').filter(Boolean)}
  function read(keys){var s=store();if(!s)return null;try{for(var i=0;i<keys.length;i++){
    var v=s.getItem(P+keys[i]);if(v)return JSON.parse(v)}}catch(e){}return null}
  function write(keys,val){var s=store();if(!s)return;try{keys.forEach(function(k){
    if(val)s.setItem(P+k,JSON.stringify(val));else s.removeItem(P+k)})}catch(e){}}
  var items=[].slice.call(document.querySelectorAll('.card,.row'));
  function paint(){
    var mine=[],filed=[];
    items.forEach(function(el){var v=read(keysOf(el));
      if(v){el.setAttribute('data-state',v.state)}else{el.removeAttribute('data-state')}
      if(v&&v.state==='mine')mine.push(el.getAttribute('data-name'));
      if(v&&v.state==='filed')filed.push(el.getAttribute('data-name')+' (filed '+v.on+')');});
    fill('mine-list',mine,'Nothing marked yet.');fill('filed-list',filed,'Nothing filed yet.');
    document.getElementById('mine-count').textContent=mine.length;
    document.getElementById('filed-count').textContent=filed.length;
  }
  function fill(id,names,empty){var ul=document.getElementById(id);ul.textContent='';
    if(!names.length){var li=document.createElement('li');li.className='muted';li.textContent=empty;
      ul.appendChild(li);return}
    names.forEach(function(n){var li=document.createElement('li');li.textContent=n;ul.appendChild(li)})}
  document.addEventListener('click',function(ev){var b=ev.target.closest('.marks button');if(!b)return;
    var el=b.closest('.card,.row');var act=b.getAttribute('data-act');var cur=read(keysOf(el));
    var today=new Date().toISOString().slice(0,10);
    write(keysOf(el),cur&&cur.state===act?null:{state:act,on:today});paint();});
  function toggle(id,cls){var box=document.getElementById(id);if(!box)return;
    var apply=function(){document.body.classList.toggle(cls,box.checked)};box.addEventListener('change',apply);apply()}
  toggle('hide-notme','hide-notme');toggle('hide-filed','hide-filed');toggle('only-new','only-new');
  var q=document.getElementById('q');
  q.addEventListener('input',function(){var t=q.value.trim().toLowerCase();
    document.body.classList.toggle('searching',!!t);
    items.forEach(function(el){el.classList.toggle('hit',!!t&&el.textContent.toLowerCase().indexOf(t)>=0)});
    if(t){document.querySelectorAll('details.fold').forEach(function(d){d.open=true})}});
  if(document.body.getAttribute('data-show-new')==='1'){
    document.querySelectorAll('[data-new="1"] .badge.new').forEach(function(b){b.hidden=false})}
  var ok=false;try{var s=store();s.setItem(P+'probe','1');ok=s.getItem(P+'probe')==='1';s.removeItem(P+'probe')}catch(e){}
  if(!ok){document.getElementById('storage-warn').hidden=false}
  paint();
})();
"""


def render(settlements: list[Settlement], *, today: date, home_states: list[str],
           stats: dict, first_run: bool, ai_note: str = "") -> str:
    live = [s for s in settlements if not s.excluded]
    new_keys = {s.key for s in live if s.is_new}
    show_new = not first_run and bool(new_keys)

    def is_new(s: Settlement) -> bool:
        return s.key in new_keys

    ai_on = any(s.ai.get("verdict") for s in live)
    upcoming = [s for s in live if s.status_upcoming]
    live = [s for s in live if not s.status_upcoming]
    automatic = sorted([s for s in live if s.tier == TIER_AUTOMATIC], key=_sort_key)
    claims = [s for s in live if s.tier != TIER_AUTOMATIC]
    likely: list[Settlement] = []
    maybe: list[Settlement] = []
    rest = claims
    if ai_on:  # Claude's verdicts pick the top sections; everything else falls through by kind
        likely = sorted([s for s in claims if s.ai.get("verdict") == "likely"], key=_sort_key)
        maybe = sorted([s for s in claims if s.ai.get("verdict") == "maybe"], key=_sort_key)
        rest = [s for s in claims if s.ai.get("verdict") not in ("likely", "maybe")]
    consumer = sorted([s for s in rest if s.kind == KIND_CONSUMER], key=_sort_key)
    breach = sorted([s for s in rest if s.kind == KIND_BREACH], key=_sort_key)
    groups = sorted([s for s in rest if s.kind == KIND_GROUP],
                    key=lambda s: (s.group_label, s.deadline or FAR))

    top = likely + maybe if ai_on else consumer
    soon = [s for s in top if s.deadline and (s.deadline - today).days <= 7]
    states_txt = ", ".join(home_states) if home_states else "all states (no states set in profile.toml)"
    # darkreader-lock: the page has its own dark theme; Dark Reader's recoloring would flatten
    # the red/amber/green deadline chips into one gray.
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
         '<meta name="darkreader-lock">'
         f"<title>Class Action Claims</title><style>{CSS}</style></head>",
         f'<body data-show-new="{int(show_new)}"><div class="wrap">',
         "<h1>Class action claims you could file</h1>",
         f'<p class="sub">Updated {datetime.now():%a %b %d, %Y %I:%M %p} · open settlements needing no '
         f'receipts or documents · state filter: {_e(states_txt)}</p>']
    if ai_note:
        h.append(f'<p class="sub">{_e(ai_note)}</p>')

    stat_links = []
    if ai_on:
        stat_links += [("#likely", len(likely), "likely you"), ("#maybe", len(maybe), "worth a look")]
    else:
        stat_links += [("#consumer", len(consumer), "products & services")]
    stat_links += [("#breach", len(breach), "data breaches"), ("#automatic", len(automatic), "automatic"),
                   ("#groups", len(groups), "specific groups")]
    if soon:
        stat_links.insert(0, ("#likely" if ai_on else "#consumer", len(soon),
                              "closing within 7 days"))
    h.append('<div class="stats">' + "".join(
        f'<a class="stat" href="{a}"><b>{n}</b>{_e(t)}</a>' for a, n, t in stat_links) + "</div>")

    h.append('<div class="how"><b>How to use this</b><ol>'
             "<li>Read who qualifies on each card. File only if every part is true for you: "
             "claim forms are signed under penalty of perjury.</li>"
             "<li>Press <b>That's me</b> to shortlist, file through the <b>File claim</b> / "
             "<b>Official site</b> button, then press <b>Filed ✓</b>.</li>"
             "<li><b>Not me</b> hides a case on this computer. Your marks carry over to future "
             "reports as long as you open them from the same file path.</li></ol></div>")

    h.append('<div class="toolbar"><input id="q" type="search" placeholder="Search (company, product, state)…" '
             'aria-label="Search">'
             '<label><input type="checkbox" id="hide-notme" checked> Hide “Not me”</label>'
             '<label><input type="checkbox" id="hide-filed"> Hide filed</label>'
             + ('<label><input type="checkbox" id="only-new"> Only new since last run '
                f'({len(new_keys)})</label>' if show_new else "")
             + "</div>")

    h.append('<div class="panel"><b>Your list</b> · <span id="mine-count">0</span> marked “That\'s me” · '
             '<span id="filed-count">0</span> filed'
             '<p id="storage-warn" class="warn" hidden>This browser isn\'t saving your marks for this '
             'page (private window or blocked site data), so they\'ll be gone after a reload.</p>'
             '<details><summary>Show</summary><p><b>To file</b></p><ul id="mine-list"></ul>'
             '<p><b>Filed</b></p><ul id="filed-list"></ul></details></div>')

    def cards(items: list[Settlement]) -> str:
        return '<div class="grid">' + "".join(_card(s, today, home_states, is_new(s)) for s in items) + "</div>"

    def rows(items: list[Settlement]) -> str:
        return "".join(_row(s, today, home_states, is_new(s)) for s in items)

    if ai_on:
        h.append(f'<h2 id="likely">Likely you: file these ({len(likely)})</h2>'
                 '<p class="lede">Matched against profile.toml. Check the question, then file.</p>'
                 + cards(likely))
        h.append(f'<h2 id="maybe">Worth a look: answer the question ({len(maybe)})</h2>' + cards(maybe))
    else:
        h.append(f'<h2 id="consumer">Products &amp; services: could be anyone ({len(consumer)})</h2>'
                 '<p class="lede">Consumer settlements with no receipts required, soonest deadline first. '
                 'Most take 2–5 minutes to file.</p>' + cards(consumer))

    h.append(f'<h2 id="breach">Data breaches: only if your data was exposed ({len(breach)})</h2>'
             '<p class="lede">You\'re in these only if the company notified you (by mail or email). '
             'The notice carries the Claim ID you\'ll need. These buttons search your Gmail for '
             'batches of the company names below:</p>')
    batches = breach_batches(breach)
    h.append('<div class="gmail-batches">' + "".join(
        f'<a class="btn ghost" href="{_e(_gmail(q))}" target="_blank" rel="noopener noreferrer">'
        f'Search Gmail · batch {i + 1}</a>' for i, q in enumerate(batches)) + "</div>")
    h.append(f'<details class="fold"><summary>Show all {len(breach)} breach settlements</summary>'
             + rows(breach) + "</details>")

    h.append(f'<h2 id="automatic">Automatic payments: nothing to file ({len(automatic)})</h2>'
             '<p class="lede">If you\'re in the class you\'ll be paid without a claim. Some sites let '
             'you update your address or pick PayPal/Venmo.</p>'
             f'<details class="fold"><summary>Show {len(automatic)}</summary>{rows(automatic)}</details>')

    h.append(f'<h2 id="groups">Specific groups: only if this describes you ({len(groups)})</h2>'
             '<p class="lede">Employees, patients of one provider, tenants, people who got certain '
             'calls or texts, and so on.</p><details class="fold"><summary>Show all</summary>')
    current = None
    for s in groups:
        if s.group_label != current:
            current = s.group_label
            h.append(f'<h3 class="group-title">{_e(current)}</h3>')
        h.append(_row(s, today, home_states, is_new(s)))
    h.append("</details>")

    if ai_on and consumer:
        h.append(f'<h2 id="unlikely">Probably not you ({len(consumer)})</h2>'
                 '<p class="lede">Consumer settlements Claude judged unlikely from your profile.</p>'
                 f'<details class="fold"><summary>Show</summary>{rows(consumer)}</details>')

    if upcoming:
        h.append(f'<h2 id="upcoming">Not open for claims yet ({len(upcoming)})</h2>'
                 f'<details class="fold"><summary>Show</summary>{rows(sorted(upcoming, key=_sort_key))}'
                 "</details>")

    excluded = [s for s in settlements if s.excluded]
    by_state = sorted([s for s in excluded if s.excluded.startswith("Only for")], key=lambda s: s.name)
    docs = [s for s in excluded if s.excluded == merge.EXCLUDED_DOCS]
    h.append('<h2 id="excluded">Left out</h2><div class="panel excluded">'
             f"<p>{len(docs)} open settlements need receipts or other records, so they're not listed. "
             f"{len(by_state)} are limited to states outside {_e(states_txt)}.</p>"
             f'<details><summary>Show the state-limited ones</summary><ul>'
             + "".join(f'<li>{_e(s.name)} <span class="muted">({_e(s.excluded)})</span></li>' for s in by_state)
             + "</ul></details></div>")

    src = stats.get("sources", {})
    h.append("<footer><ul>"
             "<li><b>Only file where every statement is true.</b> Claim forms are signed under penalty "
             "of perjury, and administrators audit claims.</li>"
             "<li>Filing is always free. A real settlement never charges a fee and never asks for "
             "your bank login. If an email gives you a Claim ID, type it into the official site "
             "linked here rather than clicking the email's link.</li>"
             "<li>You don't “join” a settled class action. If you fit the class definition you're "
             "already in it, and filing a claim is how you get paid. Lawsuits that haven't settled "
             "need nothing from you; you'll get notice if they settle. Law-firm “investigation” "
             "sign-ups are deliberately left out.</li>"
             "<li>Payouts are estimates and often shrink when many people claim. Money usually "
             "arrives months after the court's final approval.</li>"
             "<li>Sources: ClassAction.org and OpenClassActions.com. Both are independent directories, "
             "not settlement administrators. Claim and official-site links are copied from those "
             "directories, and a claim link is shown only when it's on the official site's domain. "
             "Always confirm the deadline and who qualifies on the official site.</li>"
             f"<li>This run: {src.get('cao', 0)} ClassAction.org listings, {src.get('oca', 0)} "
             f"OpenClassActions listings, {stats.get('detail_pages', 0)} case pages read "
             f"({stats.get('network', 0)} fetched fresh).</li>"
             f"</ul></footer></div><script>{JS}</script></body></html>")
    return "".join(h)


def console_summary(settlements: list[Settlement], today: date, report_path: str) -> str:
    live = [s for s in settlements if not s.excluded and not s.status_upcoming]
    claims = [s for s in live if s.tier != TIER_AUTOMATIC]
    top = sorted([s for s in claims if s.kind == KIND_CONSUMER or s.ai.get("verdict") == "likely"],
                 key=_sort_key)[:10]
    lines = [f"{len(live)} open settlements need no receipts "
             f"({sum(s.kind == KIND_CONSUMER for s in claims)} products & services, "
             f"{sum(s.kind == KIND_BREACH for s in claims)} data breaches, "
             f"{sum(s.tier == TIER_AUTOMATIC for s in live)} automatic, "
             f"{sum(s.kind == KIND_GROUP for s in claims)} specific groups).",
             "", "Soonest deadlines (products & services):"]
    for s in top:
        due, _ = _due(s, today)
        badge = TIER_BADGE.get(s.tier, ("", ""))[0]
        lines.append(f"  {due:<22} {s.name[:52]:<52} {badge}")
    lines += ["", f"Report: {report_path}"]
    return "\n".join(lines)


def to_json(settlements: list[Settlement]) -> str:
    """Machine-readable dump of what the report shows (for scripts / spreadsheets)."""
    rows = []
    for s in settlements:
        rows.append({
            "key": s.key, "aliases": s.aliases, "name": s.name, "who": s.who,
            "deadline": s.deadline.isoformat() if s.deadline else None,
            "payout": s.payout, "tier": s.tier, "tier_note": s.tier_note, "kind": s.kind,
            "group": s.group_label, "states": s.states, "official_url": s.official_url,
            "claim_url": s.claim_url, "excluded": s.excluded, "ai": s.ai,
            "sources": s.links,
        })
    return json.dumps(rows, indent=1, ensure_ascii=False)
