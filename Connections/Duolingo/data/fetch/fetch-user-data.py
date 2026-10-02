#!/usr/bin/env python3
"""Scrape the account-level facts off a duome profile into profile.json + profile.png.

This is everything that is true of the learner regardless of language: XP, streak,
lingots, league, account age, the avatar, and when duome last spoke to Duolingo.
Per-language progress lives in fetch-progress.py instead.

Run refresh-user-profile.py first, or you will faithfully record stale numbers.

Usage:
    python fetch-user-data.py            # username from username.txt
    python fetch-user-data.py Jackicuss
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

import _common as duome

PERSON_RE = re.compile(r'<div class="person">(.*?)</div>\s*</div>', re.S)
STATS_RE = re.compile(r'<div class="stats cCCC">(.*?)</div>\s*</div>', re.S)


def first(pattern: str, html: str, group: int = 1) -> str | None:
    m = re.search(pattern, html, re.S)
    return duome.clean(m.group(group)) if m else None


def parse_person(html: str) -> dict:
    """The header block: avatar, name, XP, streak, lingots, word count, league."""
    block = PERSON_RE.search(html)
    block = block.group(1) if block else html

    # The counters are icon-labelled spans; aria-label carries the value in words.
    labels = dict(re.findall(r'aria-label="(\d+)\s+(\w+)', block))
    counts = {kind: int(value) for value, kind in labels.items()}

    return {
        "username": first(r'<h1 class="username">(.*?)</h1>', block),
        "display_name": first(r'<span class="json-name">(.*?)</span>', block),
        "avatar": first(r'<img[^>]+src="([^"]+)"', block),
        "xp": int(re.sub(r"\D", "", first(r'<span class="json-xp">(.*?)</span>', block) or "0") or 0),
        "streak_days": counts.get("days"),
        "lingots": counts.get("lingots"),
        "words": counts.get("words"),
        "league": first(r'<div title="([^"]*)"[^>]*class="[^"]*badge', block),
    }


def parse_stats(html: str) -> dict:
    """The small grey block: timezone, account age, last duome sync."""
    block = STATS_RE.search(html)
    block = block.group(1) if block else html
    return {
        "timezone": first(r"Timezone:\s*([^<]+)", block),
        "created": first(r"Created:\s*([^<]+)", block),
        "streak_extended": first(r'Streak Extended:\s*<span[^>]*>(.*?)</span>', block),
        "duome_last_update": first(r'Last update:\s*(.*?)</span>', block),
        "achievement": first(r'<div title="([^"]*)"[^>]*class="[^"]*achievement', block),
    }


def main() -> None:
    user = sys.argv[1] if len(sys.argv) > 1 else duome.username()
    html = duome.profile_html(user)

    # Course-level detail (through_unit, tree size) is owned by fetch-progress.py, so
    # carry forward anything it already wrote rather than resetting it here.
    previous = duome.load_profile().get("courses", {})
    courses = duome.parse_courses(html)
    for key, course in courses.items():
        for field in ("through_unit", "units_completed", "units_total", "wordlist"):
            if previous.get(key, {}).get(field) is not None:
                course[field] = previous[key][field]

    profile = {
        "source": "duome.eu",
        "duolingo_id": duome.duolingo_id(html),
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **parse_person(html),
        **parse_stats(html),
        "courses": courses,
    }

    if not profile["username"]:
        raise SystemExit(f"Could not parse /{user} -- duome's markup may have changed.")

    # profile.json and profile.png are a set -- fetch the avatar alongside the facts.
    size, fmt = 0, None
    if profile.get("avatar"):
        size, fmt = duome.download_image(profile["avatar"], duome.PROFILE_IMAGE)
        profile["avatar_file"] = duome.PROFILE_IMAGE.name

    # The stat icons (XP, streak, lingots, words, league badge) are CSS backgrounds
    # rather than <img> tags, so they come from the stylesheet rather than the markup.
    person = PERSON_RE.search(html)
    profile["assets"] = duome.download_assets(
        person.group(1) if person else html, duome.get("/style.css"), duome.ASSETS
    )

    out = duome.PROFILE
    duome.write_json(out, profile)

    print(f"{profile['username']} ({profile['display_name']})")
    print(f"  {profile['xp']} XP · {profile['streak_days']} day streak · {profile['lingots']} lingots · {profile['words']} words")
    print(f"  league: {profile['league']}")
    print(f"  duome last synced: {profile['duome_last_update']}")
    if size:
        print(f"  avatar: {duome.PROFILE_IMAGE.name} ({fmt}, {size:,} bytes)")
        if fmt != "png":
            # Saved regardless so nothing is lost, but then the filename is a lie.
            print(f"  note: that is {fmt or 'an unrecognised format'}, not png")
    else:
        print("  note: no avatar on this profile")
    if profile["assets"]:
        print(f"  assets: {len(profile['assets'])} -> {', '.join(sorted(profile['assets']))}")
    print(f"  courses: {len(courses)}")
    for key, c in courses.items():
        mark = "*" if c["active"] else " "
        unit = f", through unit {c['through_unit']}" if c["through_unit"] is not None else ""
        print(f"   {mark} {key} {c['language']}: {c['xp']} XP{unit}")
    print(f"wrote {out.relative_to(duome.SOURCE_ROOT.parent.parent)} + {duome.PROFILE_IMAGE.name}")


if __name__ == "__main__":
    main()
