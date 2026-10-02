#!/usr/bin/env python3
"""Generate showcase.html at the project root -- a browsable view of the whole workspace.

Why generated rather than a static page that loads the data itself: a file opened over
file:// cannot fetch() sibling files, browsers treat every local read as cross-origin.
Baking the data in keeps the page a single self-contained artifact you can double-click,
with no server and no CORS flags. Images are inlined as data URIs for the same reason.

Reads whatever exists and skips the rest, so it works before any given connection has
been scraped:
    Connections/*/profile.json          account facts and course registry
    Connections/*/profile.png           avatar
    Connections/*/assets/*.svg          stat icons
    Connections/*/data/languages/*/*.csv    raw course word tables
    Connections/Tests/*/*.csv           test vocabulary lists
    Profile/lexicon.jsonl   the merged lexicon, with confidence

Usage:
    python build_showcase.py
    python build_showcase.py --open      # write it, then open in the default browser
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import webbrowser
from datetime import date
from pathlib import Path

# scripts live at Profile/data/scripts/, so Profile is three up.
PROFILE_DIR = Path(__file__).resolve().parents[2]
ROOT = PROFILE_DIR.parent
CONNECTIONS = ROOT / "Connections"
RESOURCES = ROOT / "Resources"
LEXICON = PROFILE_DIR / "lexicon.jsonl"
NAMES = PROFILE_DIR / "names.jsonl"
LEARNER = PROFILE_DIR / "profile.json"
OUT = ROOT / "showcase.html"

# Every Duolingo audio URL shares this prefix; stripping it saves ~250KB per table.
AUDIO_PREFIX = "https://d1vq87e9lcf771.cloudfront.net/"

NUM = "num"


def col(label, cls="", type_="text"):
    return {"label": label, "cls": cls, "type": type_}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def collect_profiles() -> list[dict]:
    """Every connection with a profile.json, with avatar and stat icons inlined."""
    profiles = []
    for path in sorted(CONNECTIONS.glob("*/profile.json")):
        profile = read_json(path)
        if not profile:
            continue
        root = path.parent
        profile["connection"] = root.name
        avatar = root / "profile.png"
        if avatar.exists():
            profile["avatar_data"] = data_uri(avatar, "image/png")
        # Inline the scraped icons so the page stays self-contained.
        icons = {}
        for name, rel in (profile.get("assets") or {}).items():
            asset = root / rel
            if asset.exists() and asset.suffix == ".svg" and asset.stat().st_size < 40_000:
                icons[name] = data_uri(asset, "image/svg+xml")
        profile["icons"] = icons
        profiles.append(profile)
    return profiles


def _word_rows(path: Path) -> list[list]:
    """Shared row shape for the lexicon and the names table."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        audio = r.get("audio") or ""
        rows.append([
            r["word"],
            r.get("kana") or "",
            r.get("kanji") or "",
            " / ".join(r.get("gloss") or []),
            f"N{r['rating']}" if r.get("rating") else "",
            "listed" if r.get("jlpt") else "inferred",
            r.get("rating_source") or "",
            r.get("matched") or "",
            r.get("confidence") or "unseen",
            r.get("unit"),
            r.get("unit_name") or "",
            "+".join(r.get("sources") or []),
            r.get("script") or "",
            r.get("romaji") or "",
            audio[len(AUDIO_PREFIX):] if audio.startswith(AUDIO_PREFIX) else audio,
        ])
    return rows


# Reading order: what the word is, then how hard, then where you are with it, then admin.
WORD_COLUMNS = [
    col("Word", "word"), col("Kana", "reading"), col("Kanji", "word"), col("Meaning"),
    col("Rating", NUM), col("On list", NUM), col("Graded by", NUM), col("Matched", NUM),
    col("Status", "status"),
    col("Unit", NUM, "num"), col("Unit name", NUM), col("Source", NUM),
    col("Script", NUM), col("Rōmaji", "reading"), col("Audio", "", "audio"),
]


def lexicon_dataset() -> dict | None:
    if not LEXICON.exists():
        return None
    rows = _word_rows(LEXICON)
    rows.sort(key=lambda r: (r[9] if r[9] is not None else 10**6, r[0]))
    return {
        "id": "lexicon",
        "connection": "Profile",
        "title": "Lexicon",
        "note": "Every word the connections and resources contribute, deduplicated. "
                "Rating is difficulty (N5 easiest); “On list” says whether that came from a "
                "real JLPT entry or was inferred.",
        "columns": WORD_COLUMNS,
        "facets": [4, 5, 6, 8, 11],
        "lockCol": 8,
        "sort": 9,          # course order reads better than alphabetical
        "rows": rows,
    }


def names_dataset() -> dict | None:
    if not NAMES.exists():
        return None
    rows = _word_rows(NAMES)
    if not rows:
        return None
    rows.sort(key=lambda r: (r[9] if r[9] is not None else 10**6, r[0]))
    return {
        "id": "names",
        "connection": "Profile",
        "title": "Names",
        "note": "People and places, kept out of the lexicon so “words you know” stays "
                "vocabulary. Rated by their script rather than any list.",
        "columns": WORD_COLUMNS,
        "facets": [4, 6, 8],
        "lockCol": 8,
        "sort": 9,
        "rows": rows,
    }


def wordlist_datasets() -> list[dict]:
    """Raw course tables, one dataset per connection/language CSV."""
    datasets = []
    for path in sorted(CONNECTIONS.glob("*/data/languages/*/*.csv")):
        connection = path.relative_to(CONNECTIONS).parts[0]
        language = path.stem.capitalize()
        with path.open(encoding="utf-8-sig", newline="") as fh:
            raw = list(csv.DictReader(fh))
        rows = []
        for r in raw:
            audio = r.get("audio") or ""
            rows.append([
                int(r["unit"]) if r.get("unit", "").isdigit() else None,
                r.get("unit_name") or "",
                r.get("unit_topic") or "",
                r.get("word") or "",
                r.get("reading") or "",
                (r.get("gloss") or "").replace("|", " / "),
                r.get("script") or "",
                audio[len(AUDIO_PREFIX):] if audio.startswith(AUDIO_PREFIX) else audio,
            ])
        datasets.append({
            "id": f"{connection.lower()}-{language.lower()}",
            "connection": connection,
            "title": f"{connection} {language} Wordlist",
            "note": "Every word the course teaches, in course order. Unit is where it is first introduced.",
            "columns": [
                col("Unit", NUM, "num"), col("Unit name", NUM), col("Topic", NUM),
                col("Word", "word"), col("Reading", "reading"), col("Meaning"),
                col("Script", NUM), col("Audio", "", "audio"),
            ],
            "facets": [6],
            "lockCol": None,
            "rows": rows,
        })
    return datasets


def test_datasets() -> list[dict]:
    """Test vocabulary lists, e.g. Resources/Tests/Japanese/jlpt-n5.csv."""
    datasets = []
    tests = RESOURCES / "Tests"
    for path in sorted(tests.glob("*/*.csv")) if tests.exists() else []:
        language = path.parent.name
        with path.open(encoding="utf-8-sig", newline="") as fh:
            raw = list(csv.DictReader(fh))
        if not raw:
            continue
        level = (raw[0].get("level") or path.stem).upper()
        rows = [[r.get("expression", ""), r.get("reading", ""), r.get("meaning", ""), r.get("tags", "")] for r in raw]
        datasets.append({
            "id": f"tests-{path.stem}",
            "connection": "Tests",
            "title": f"{language} {level.replace('N', 'JLPT N')}" if level.startswith("N") else f"{language} {level}",
            "note": f"{len(rows):,} words expected at this level.",
            "columns": [col("Expression", "word"), col("Reading", "reading"), col("Meaning"), col("Tags", NUM)],
            "facets": [],
            "lockCol": None,
            "rows": rows,
        })
    # N5 (easiest) first rather than alphabetical, which would give N1 first.
    order = {f"tests-jlpt-n{n}": i for i, n in enumerate([5, 4, 3, 2, 1])}
    datasets.sort(key=lambda d: order.get(d["id"], 99))
    return datasets


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Language-Agent — Showcase</title>
<style>
:root {
  --bg: #f5f6f8; --panel: #ffffff; --sunk: #f0f2f5; --ink: #14181f; --muted: #6b7280;
  --line: #e2e5ea; --accent: #4f7cff; --accent-soft: #edf2ff;
  --unseen: #98a0ac; --exposed: #4f7cff; --shaky: #cf7a1d; --known: #189a51;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1115; --panel: #171b21; --sunk: #12161b; --ink: #e8ecf1; --muted: #8f98a5;
    --line: #262c35; --accent: #6d92ff; --accent-soft: #1b2540;
    --unseen: #6b7280; --exposed: #6d92ff; --shaky: #e0a050; --known: #35c07a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 30px 20px 70px; background: var(--bg); color: var(--ink);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1140px; margin: 0 auto; }
h1 { font-size: 23px; margin: 0 0 3px; letter-spacing: -0.02em; }
.sub { color: var(--muted); font-size: 13px; margin-bottom: 26px; }
h2 {
  font-size: 12px; text-transform: uppercase; letter-spacing: .09em; color: var(--muted);
  margin: 34px 0 12px; display: flex; align-items: center; gap: 10px;
}
h2::after { content: ""; flex: 1; height: 1px; background: var(--line); }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 13px; }

/* ---------- profile card ---------- */
/* align-items matters: the default `stretch` makes .face full-card height, which sends
   the absolutely-positioned badge to the bottom of the card instead of the avatar. */
.card { display: flex; align-items: flex-start; gap: 22px; padding: 22px; margin-bottom: 12px; flex-wrap: wrap; }
.face { position: relative; flex: none; line-height: 0; }
.face img.avatar { width: 92px; height: 92px; border-radius: 16px; display: block; background: var(--sunk); }
.face img.badge {
  position: absolute; right: -9px; bottom: -9px; width: 34px; height: 41px;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,.35));
}
.card-main { flex: 1 1 320px; min-width: 0; }
.name { font-size: 20px; font-weight: 650; letter-spacing: -0.01em; }
.handle { color: var(--muted); font-size: 13px; margin-bottom: 14px; }
.handle .tag {
  display: inline-block; border: 1px solid var(--line); border-radius: 5px;
  padding: 0 6px; margin-right: 7px; font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
}
.stats { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
.stat {
  display: flex; align-items: center; gap: 9px; background: var(--sunk);
  border: 1px solid var(--line); border-radius: 10px; padding: 8px 13px 8px 10px;
}
.stat img { width: 20px; height: 24px; }
.stat b { display: block; font-size: 16px; font-variant-numeric: tabular-nums; line-height: 1.2; }
.stat span { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
.meta { color: var(--muted); font-size: 12px; line-height: 1.7; }
.meta b { color: var(--ink); font-weight: 600; }
.courses { display: flex; gap: 9px; flex-wrap: wrap; margin-top: 15px; }
.course { border: 1px solid var(--line); border-radius: 10px; padding: 9px 12px; font-size: 12px; min-width: 150px; }
.course.active { border-color: var(--accent); background: var(--accent-soft); }
.course .top { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 620; }
.course .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex: none; }
.course small { color: var(--muted); display: block; margin-top: 2px; }
.bar { height: 4px; border-radius: 3px; background: var(--line); margin-top: 7px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--accent); }

/* ---------- connections nav ---------- */
.conns { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.conn { padding: 14px 15px; }
.conn h3 { margin: 0; font-size: 14px; font-weight: 650; display: flex; align-items: center; gap: 7px; }
.conn h3 .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.conn p { margin: 3px 0 11px; color: var(--muted); font-size: 12px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip {
  border: 1px solid var(--line); background: var(--sunk); color: var(--ink);
  border-radius: 8px; padding: 6px 11px; font-size: 12.5px; cursor: pointer; font-family: inherit;
  display: flex; align-items: center; gap: 7px;
}
.chip:hover { border-color: var(--accent); }
.chip[aria-selected="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip em { font-style: normal; opacity: .65; font-size: 11px; font-variant-numeric: tabular-nums; }

/* ---------- table ---------- */
.tablewrap { margin-top: 12px; overflow: hidden; }
.thead { padding: 15px 16px 0; }
.thead b { font-size: 15px; }
.thead p { margin: 2px 0 0; color: var(--muted); font-size: 12px; }
.controls { display: flex; gap: 9px; flex-wrap: wrap; align-items: center; padding: 13px 16px; }
input[type=search], select {
  font: inherit; font-size: 13px; padding: 7px 10px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--sunk); color: var(--ink);
}
input[type=search] { flex: 1 1 230px; min-width: 160px; }
label.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); cursor: pointer; }
.count { margin-left: auto; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }

/* The scroller owns BOTH axes. A horizontal-only container gives sticky nothing to
   stick to, because the page, not the container, is what scrolls vertically. */
.scroll { max-height: 70vh; overflow: auto; border-top: 1px solid var(--line); }
table { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 9px 13px; border-bottom: 1px solid var(--line); vertical-align: top; }
th {
  position: sticky; top: 0; z-index: 2; background: var(--panel); cursor: pointer; user-select: none;
  font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted);
  white-space: nowrap; box-shadow: inset 0 -1px 0 var(--line);
  border-bottom: none;
}
th:hover { color: var(--ink); }
th .arrow { opacity: .45; font-size: 9px; }
th[aria-sort] { color: var(--ink); }
th[aria-sort] .arrow { opacity: 1; color: var(--accent); }
td.num { font-variant-numeric: tabular-nums; color: var(--muted); white-space: nowrap; }
td.word { font-size: 17px; font-weight: 600; white-space: nowrap; }
td.reading { color: var(--muted); font-size: 13px; white-space: nowrap; }
tbody tr:hover { background: var(--accent-soft); }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; text-transform: capitalize; border: 1px solid currentColor; }
.c-unseen { color: var(--unseen); } .c-exposed { color: var(--exposed); }
.c-shaky { color: var(--shaky); } .c-known { color: var(--known); }
.play {
  border: 1px solid var(--line); background: var(--sunk); color: var(--ink);
  border-radius: 7px; width: 28px; height: 26px; cursor: pointer; font-size: 11px; line-height: 1;
}
.play:hover { border-color: var(--accent); color: var(--accent); }
.play:disabled { opacity: .25; cursor: default; }
.empty { padding: 44px; text-align: center; color: var(--muted); }
.legend { color: var(--muted); font-size: 12px; padding: 12px 16px; border-top: 1px solid var(--line); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Language-Agent</h1>
  <div class="sub">__SUBTITLE__</div>

  <h2>Profile</h2>
  <div id="profiles"></div>

  <h2>Connections</h2>
  <div class="conns" id="conns"></div>

  <div class="panel tablewrap">
    <div class="thead"><b id="dsTitle"></b><p id="dsNote"></p></div>
    <div class="controls">
      <input type="search" id="q" placeholder="Search…">
      <span id="facets" style="display:contents"></span>
      <label class="check" id="lockWrap" hidden><input type="checkbox" id="unlocked" checked> Unlocked only</label>
      <span class="count" id="count"></span>
    </div>
    <div class="scroll"><table>
      <thead><tr id="head"></tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
    <div class="empty" id="empty" hidden>Nothing matches those filters.</div>
    <div class="legend" id="legend" hidden>
      <b>unseen</b> the course has not reached it ·
      <b>exposed</b> the course taught it ·
      <b>shaky</b> you hesitated or missed it ·
      <b>known</b> you used it unprompted
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;
const AUDIO_PREFIX = "__AUDIO_PREFIX__";
const CONN_NOTES = {
  Profile: "Yours. The merged word store everything else feeds, plus your own evidence.",
  Duolingo: "Your account — course vocabulary and unit progress, scraped from duome.eu.",
  Tests: "Reference. Standardised exam vocabulary, for measuring coverage against a syllabus.",
};

const el = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = v => Number(v).toLocaleString();

let ds = DATA.datasets[0] || null;
let sortCol = ds?.sort ?? 0, sortDir = 1;

/* ---------- profile ---------- */
function profileCard(p) {
  const ic = p.icons || {};
  const league = (p.league || "").split("·")[0].trim();
  const badge = ic.ruby || ic.badge || ic.gold || ic.silver || ic.bronze;
  const stat = (v, label, icon) => v == null ? "" :
    `<div class="stat">${icon ? `<img src="${icon}" alt="">` : ""}<div><b>${num(v)}</b><span>${label}</span></div></div>`;

  const courses = Object.entries(p.courses || {}).map(([key, c]) => {
    const pct = c.units_total ? Math.max(1, Math.round(100 * (c.units_completed || 0) / c.units_total)) : 0;
    return `<div class="course ${c.active ? "active" : ""}">
      <div class="top">${c.active ? '<span class="dot"></span>' : ""}${esc(c.language || key)}</div>
      <small>${num(c.xp ?? 0)} XP</small>
      ${c.through_unit != null
        ? `<small>unit ${c.through_unit} of ${num(c.units_total)}</small><div class="bar"><i style="width:${pct}%"></i></div>`
        : `<small>summary only — not active</small>`}
    </div>`;
  }).join("");

  return `<div class="panel card">
    <div class="face">
      ${p.avatar_data ? `<img class="avatar" src="${p.avatar_data}" alt="">` : ""}
      ${badge ? `<img class="badge" src="${badge}" alt="${esc(league)}" title="${esc(p.league || "")}">` : ""}
    </div>
    <div class="card-main">
      <div class="name">${esc(p.display_name || p.username || p.connection)}</div>
      <div class="handle"><span class="tag">${esc(p.connection)}</span>${p.username ? "@" + esc(p.username) : ""}</div>
      <div class="stats">
        ${stat(p.xp, "XP", ic.exp)}${stat(p.streak_days, "day streak", ic.streak)}
        ${stat(p.lingots, "lingots", ic.lingot)}${stat(p.words, "words", ic.voc)}
      </div>
      <div class="meta">
        ${league ? `<b>${esc(league)}</b> — ${esc((p.league || "").split("·").slice(1).join("·").trim())}<br>` : ""}
        ${p.created ? `Joined <b>${esc(p.created)}</b>` : ""}${p.streak_extended ? ` · streak extended <b>${esc(p.streak_extended)}</b>` : ""}
        ${p.achievement ? `<br>${esc(p.achievement)}` : ""}
        ${p.duome_last_update ? `<br><span style="opacity:.75">Synced ${esc(p.duome_last_update)}</span>` : ""}
      </div>
      <div class="courses">${courses}</div>
    </div>
  </div>`;
}

/* ---------- connections nav ---------- */
function buildConns() {
  const groups = {};
  DATA.datasets.forEach(d => (groups[d.connection] ||= []).push(d));
  el("conns").innerHTML = Object.entries(groups).map(([name, list]) => `
    <div class="panel conn">
      <h3><span class="dot"></span>${esc(name)}</h3>
      <p>${esc(CONN_NOTES[name] || "")}</p>
      <div class="chips">${list.map(d =>
        `<button class="chip" data-id="${d.id}" aria-selected="${ds && d.id === ds.id}">${esc(d.title)} <em>${num(d.rows.length)}</em></button>`
      ).join("")}</div>
    </div>`).join("");
}
el("conns").addEventListener("click", e => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  ds = DATA.datasets.find(d => d.id === chip.dataset.id);
  sortCol = ds.sort ?? 0; sortDir = 1;
  el("q").value = "";
  buildConns(); mountDataset();
});

/* ---------- table ---------- */
function mountDataset() {
  el("dsTitle").textContent = ds.title;
  el("dsNote").textContent = ds.note || "";
  el("legend").hidden = ds.lockCol == null;
  el("lockWrap").hidden = ds.lockCol == null;

  el("facets").innerHTML = ds.facets.map(i => {
    const vals = [...new Set(ds.rows.map(r => r[i]).filter(Boolean))].sort();
    return `<select data-i="${i}"><option value="">Any ${esc(ds.columns[i].label.toLowerCase())}</option>${
      vals.map(v => `<option>${esc(v)}</option>`).join("")}</select>`;
  }).join("");
  el("facets").querySelectorAll("select").forEach(s => s.addEventListener("input", render));

  buildHead();
  render();
}

function buildHead() {
  el("head").innerHTML = ds.columns.map((c, i) => {
    if (c.type === "audio") return `<th style="cursor:default">${esc(c.label)}</th>`;
    const on = sortCol === i;
    return `<th data-i="${i}"${on ? ` aria-sort="${sortDir > 0 ? "ascending" : "descending"}"` : ""}>${
      esc(c.label)} <span class="arrow">${on ? (sortDir > 0 ? "▲" : "▼") : "↕"}</span></th>`;
  }).join("");
}
el("head").addEventListener("click", e => {
  const th = e.target.closest("th[data-i]");
  if (!th) return;
  const i = +th.dataset.i;
  sortDir = sortCol === i ? -sortDir : 1;
  sortCol = i;
  buildHead(); render();
});

function render() {
  const q = el("q").value.trim().toLowerCase();
  const facets = [...el("facets").querySelectorAll("select")].map(s => [+s.dataset.i, s.value]).filter(f => f[1]);
  const lockCol = ds.lockCol, hideLocked = lockCol != null && el("unlocked").checked;

  let rows = ds.rows.filter(r => {
    if (hideLocked && r[lockCol] === "unseen") return false;
    for (const [i, v] of facets) if (r[i] !== v) return false;
    if (q && !r.join(" ").toLowerCase().includes(q)) return false;
    return true;
  });

  rows = rows.slice().sort((a, b) => {
    const x = a[sortCol], y = b[sortCol];
    if (x == null) return 1;
    if (y == null) return -1;
    const cmp = ds.columns[sortCol].type === "num" ? x - y : String(x).localeCompare(String(y), "ja");
    return cmp * sortDir;
  });

  el("count").textContent = `${num(rows.length)} of ${num(ds.rows.length)}`;
  el("empty").hidden = rows.length > 0;
  el("rows").innerHTML = rows.map(r => "<tr>" + ds.columns.map((c, i) => {
    if (c.type === "audio")
      return r[i] ? `<td><button class="play" data-a="${esc(r[i])}" title="Play">▶</button></td>`
                  : `<td><button class="play" disabled>▶</button></td>`;
    if (c.cls === "status") return `<td><span class="pill c-${esc(r[i])}">${esc(r[i])}</span></td>`;
    return `<td class="${c.cls}">${esc(r[i] ?? "")}</td>`;
  }).join("") + "</tr>").join("");
}

// Audio lives on Duolingo's CDN, so playback needs a connection. Reuse one element.
const player = new Audio();
el("rows").addEventListener("click", e => {
  const btn = e.target.closest(".play[data-a]");
  if (!btn) return;
  player.src = AUDIO_PREFIX + btn.dataset.a;
  player.play().catch(() => { btn.textContent = "×"; btn.title = "Could not play — are you offline?"; });
});

el("profiles").innerHTML = DATA.profiles.map(profileCard).join("") || '<div class="panel empty">No connection profile yet.</div>';
el("q").addEventListener("input", render);
el("unlocked").addEventListener("input", render);
if (ds) { buildConns(); mountDataset(); }
else { el("count").textContent = "No data yet — run the connection scrapers."; }
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--open", action="store_true", help="open the page after writing it")
    args = ap.parse_args()

    profiles = collect_profiles()
    datasets = [d for d in (lexicon_dataset(), names_dataset()) if d] + wordlist_datasets() + test_datasets()
    learner = read_json(LEARNER)

    counts = learner.get("lexicon", {})
    subtitle = f"Generated {date.today().isoformat()}"
    if counts:
        subtitle += f" · {counts.get('usable', 0):,} of {counts.get('total', 0):,} words unlocked"

    payload = json.dumps({"profiles": profiles, "datasets": datasets}, ensure_ascii=False, separators=(",", ":"))
    page = (
        PAGE.replace("__DATA__", payload)
        .replace("__AUDIO_PREFIX__", AUDIO_PREFIX)
        .replace("__SUBTITLE__", subtitle)
    )
    OUT.write_text(page, encoding="utf-8")

    print(f"profiles: {len(profiles)} ({', '.join(p['connection'] for p in profiles) or 'none'})")
    for d in datasets:
        print(f"  {d['connection']:<10} {d['title']:<34} {len(d['rows']):>6,} rows")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")

    if args.open:
        webbrowser.open(OUT.as_uri())


if __name__ == "__main__":
    main()
