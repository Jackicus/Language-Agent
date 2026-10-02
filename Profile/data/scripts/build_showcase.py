#!/usr/bin/env python3
"""Generate showcase.html at the project root -- a browsable view of the whole workspace.

Why generated rather than a static page that loads the data itself: a file opened over
file:// cannot fetch() sibling files, browsers treat every local read as cross-origin.
Baking the data in keeps the page a single self-contained artifact you can double-click,
with no server and no CORS flags. Images are inlined as data URIs for the same reason.

Shows the active language only -- `language` in Profile/profile.json, labelled from
languages.json (its name, level names, scripts). Reads whatever exists and skips the
rest, so it works before any given connection has been scraped:
    Connections/*/profile.json                      account facts and course registry
    Connections/*/profile.png                       avatar
    Connections/*/assets/*.svg                      stat icons
    Connections/*/data/languages/*/<language>.csv   raw word tables (Duolingo, Anki, ...)
    Resources/Tests/<Language>/*.csv                test vocabulary lists
    Profile/<code>/lexicon.jsonl, names.jsonl       the merged lexicon, with confidence

Columns a language has no data for (kanji for French, audio for an Anki deck) are dropped.

Usage:
    python build_showcase.py
    python build_showcase.py --open      # write it, then open in the default browser
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import webbrowser
from datetime import date
from pathlib import Path

# scripts live at Profile/data/scripts/, so the project root is four up.
ROOT = Path(__file__).resolve().parents[3]
# LEXICON_DIR overrides Profile/ as a whole; the <code>/ subfolder still applies under it.
PROFILE_DIR = Path(os.environ.get("LEXICON_DIR") or ROOT / "Profile")
CONNECTIONS = ROOT / "Connections"
RESOURCES = ROOT / "Resources"
LEARNER = PROFILE_DIR / "profile.json"
OUT = ROOT / "showcase.html"

# Every Duolingo audio URL shares this prefix; stripping it saves ~250KB per table.
AUDIO_PREFIX = "https://d1vq87e9lcf771.cloudfront.net/"

NUM = "num"


def col(label, cls="", type_="text"):
    return {"label": label, "cls": cls, "type": type_}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_language() -> tuple[str, dict]:
    """(code, registry entry) for the active language. Accepts the pre-registry form of
    profile.json, which stored the name ("Japanese") rather than the code."""
    registry = {k: v for k, v in read_json(ROOT / "languages.json").items() if not k.startswith("_")}
    value = str(read_json(LEARNER).get("language") or "")
    for code, entry in registry.items():
        if value.lower() in (code, entry["name"].lower()):
            return code, entry
    code = next(iter(registry), "ja")  # nothing chosen yet: the registry's first language
    return code, registry.get(code) or {"name": "Japanese", "scripts": [], "tests": {}, "dictionary": {}}


CODE, LANG = load_language()
LEVELS = (LANG.get("tests") or {}).get("levels") or []
TEST_SOURCE = (LANG.get("tests") or {}).get("source") or ""
OFFICIAL = bool((LANG.get("tests") or {}).get("official"))
SCRIPTS = LANG.get("scripts") or []


def profile_file(name: str) -> Path:
    """Profile/<code>/<name>, or the flat pre-registry Profile/<name> until build_lexicon moves it."""
    path = PROFILE_DIR / CODE / name
    flat = PROFILE_DIR / name
    return flat if not path.exists() and CODE == "ja" and flat.exists() else path


LEXICON = profile_file("lexicon.jsonl")
NAMES = profile_file("names.jsonl")


def level_label(rating) -> str:
    """rating = len(levels) - index, so the easiest level has the highest rating."""
    if not isinstance(rating, int) or not LEVELS or not 1 <= rating <= len(LEVELS):
        return ""
    return LEVELS[len(LEVELS) - rating]


def prune(dataset: dict, keep: tuple = ()) -> dict:
    """Drop columns no row fills, remapping the facet/lock/sort indices that point at them."""
    cols, rows = dataset["columns"], dataset["rows"]
    live = [i for i in range(len(cols)) if i in keep or any(r[i] not in (None, "") for r in rows)]
    where = {old: new for new, old in enumerate(live)}
    dataset["columns"] = [cols[i] for i in live]
    dataset["rows"] = [[r[i] for i in live] for r in rows]
    dataset["facets"] = [where[i] for i in dataset.get("facets", []) if i in where]
    for key in ("lockCol", "sort"):
        if dataset.get(key) is not None:
            dataset[key] = where.get(dataset[key], 0 if key == "sort" else None)
    return dataset


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
        listed = r["listed"] if "listed" in r else r.get("jlpt")  # `jlpt` is the pre-registry name
        rows.append([
            r["word"],
            r.get("kana") or r.get("reading") or "",
            r.get("kanji") or "",
            " / ".join(r.get("gloss") or []),
            level_label(r.get("rating")),
            ("listed" if listed else "inferred") if r.get("rating") else "",
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
# Japanese keeps its own labels; other languages get neutral ones, and prune() drops
# whichever of these a language never fills.
WORD_COLUMNS = [
    col("Word", "word"), col("Kana" if "hiragana" in SCRIPTS else "Reading", "reading"),
    col("Kanji" if "kanji" in SCRIPTS else "Other form", "word"), col("Meaning"),
    col("Level", NUM), col("On list", NUM), col("Graded by", NUM), col("Matched", NUM),
    col("Status", "status"),
    col("Unit", NUM, "num"), col("Unit name", NUM), col("Source", NUM),
    col("Script", NUM), col("Rōmaji" if CODE == "ja" else "Romanisation", "reading"), col("Audio", "", "audio"),
]


def rating_note() -> str:
    if not LEVELS:
        return ""
    if TEST_SOURCE and OFFICIAL:
        where = f"a real {TEST_SOURCE.upper()} entry"
    elif TEST_SOURCE:
        where = "a frequency band (an approximation, not an exam list)"
    else:
        where = "a test list -- none is fetched for this language yet, so every level is inferred"
    return f" Level is difficulty ({LEVELS[0]} easiest); “On list” says whether it came from {where} or was inferred."


def lexicon_dataset() -> dict | None:
    if not LEXICON.exists():
        return None
    rows = _word_rows(LEXICON)
    rows.sort(key=lambda r: (r[9] if r[9] is not None else 10**6, r[0]))
    return prune({
        "id": "lexicon",
        "connection": "Profile",
        "title": f"{LANG['name']} Lexicon",
        "note": "Every word the connections and resources contribute, deduplicated." + rating_note(),
        "columns": WORD_COLUMNS,
        "facets": [4, 5, 6, 8, 11],
        "lockCol": 8,
        "sort": 9,          # course order reads better than alphabetical
        "rows": rows,
    }, keep=(0, 8))


def names_dataset() -> dict | None:
    if not NAMES.exists():
        return None
    rows = _word_rows(NAMES)
    if not rows:
        return None
    rows.sort(key=lambda r: (r[9] if r[9] is not None else 10**6, r[0]))
    return prune({
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
    }, keep=(0, 8))


def wordlist_datasets() -> list[dict]:
    """Raw word tables for the active language, one dataset per connection."""
    datasets = []
    for path in sorted(CONNECTIONS.glob(f"*/data/languages/*/{LANG['name'].lower()}.csv")):
        connection = path.relative_to(CONNECTIONS).parts[0]
        language = LANG["name"]
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
                {"1": "seen", "0": "not yet"}.get(r.get("seen") or "", ""),
                audio[len(AUDIO_PREFIX):] if audio.startswith(AUDIO_PREFIX) else audio,
            ])
        units = any(r[0] is not None for r in rows)
        datasets.append(prune({
            "id": f"{connection.lower()}-{language.lower()}",
            "connection": connection,
            "title": f"{connection} {language} Wordlist",
            "note": "Every word the course teaches, in course order. Unit is where it is first introduced."
                    if units else "Every card in the deck. “Seen” means reviewed at least once.",
            "columns": [
                col("Unit", NUM, "num"), col("Unit name", NUM), col("Topic", NUM),
                col("Word", "word"), col("Reading", "reading"), col("Meaning"),
                col("Script", NUM), col("Seen", NUM), col("Audio", "", "audio"),
            ],
            "facets": [6, 7],
            "lockCol": None,
            "rows": rows,
        }, keep=(3,)))
    return datasets


def test_datasets() -> list[dict]:
    """Test vocabulary lists for the active language, e.g. Resources/Tests/Japanese/jlpt-n5.csv."""
    datasets = []
    folder = RESOURCES / "Tests" / LANG["name"]
    for path in sorted(folder.glob("*.csv")) if folder.exists() else []:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            raw = list(csv.DictReader(fh))
        if not raw:
            continue
        level = raw[0].get("level") or path.stem
        rows = [[r.get("expression", ""), r.get("reading", ""), r.get("meaning", ""), r.get("tags", "")] for r in raw]
        source = path.stem.split("-")[0].upper()
        # "Japanese JLPT N5", but "Chinese HSK1" rather than "Chinese HSK HSK1".
        named = level if level.upper().startswith(source) or not OFFICIAL else f"{source} {level}"
        datasets.append(prune({
            "id": f"tests-{path.stem}",
            "connection": "Tests",
            "title": f"{LANG['name']} {named}",
            "note": f"{len(rows):,} words expected at this level." if OFFICIAL else
                    f"{len(rows):,} words in this frequency band -- an approximation, not an exam list.",
            "columns": [col("Expression", "word"), col("Reading", "reading"), col("Meaning"), col("Tags", NUM)],
            "facets": [],
            "lockCol": None,
            "rows": rows,
        }, keep=(0,)))
    # Easiest level first, in the registry's order, rather than alphabetical (N1 first).
    order = {lv.upper(): i for i, lv in enumerate(LEVELS)}
    datasets.sort(key=lambda d: order.get(d["title"].rsplit(" ", 1)[-1].upper(), 99))
    return datasets


PAGE = """<!doctype html>
<html lang="__CODE__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Language-Agent — __LANGUAGE__</title>
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
  Anki: "Your deck — every card, and which ones you have already reviewed.",
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
    const cmp = ds.columns[sortCol].type === "num" ? x - y : String(x).localeCompare(String(y), DATA.lang);
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
  const a = btn.dataset.a;  // stripped of AUDIO_PREFIX when it had it; other hosts stay whole
  player.src = /^https?:/.test(a) ? a : AUDIO_PREFIX + a;
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
    subtitle = f"{LANG['name']} · generated {date.today().isoformat()}"
    if counts:
        subtitle += f" · {counts.get('usable', 0):,} of {counts.get('total', 0):,} words unlocked"

    payload = json.dumps({"lang": CODE, "profiles": profiles, "datasets": datasets},
                         ensure_ascii=False, separators=(",", ":"))
    page = (
        PAGE.replace("__LANGUAGE__", LANG["name"]).replace("__CODE__", CODE)
        .replace("__DATA__", payload)
        .replace("__AUDIO_PREFIX__", AUDIO_PREFIX)
        .replace("__SUBTITLE__", subtitle)
    )
    OUT.write_text(page, encoding="utf-8")

    print(f"language: {LANG['name']} ({CODE})")
    print(f"profiles: {len(profiles)} ({', '.join(p['connection'] for p in profiles) or 'none'})")
    for d in datasets:
        print(f"  {d['connection']:<10} {d['title']:<34} {len(d['rows']):>6,} rows")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")

    if args.open:
        webbrowser.open(OUT.as_uri())


if __name__ == "__main__":
    main()
