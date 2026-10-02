#!/usr/bin/env python3
"""Scrape per-language course progress off a duome profile.

The profile page carries a hidden tab holding the whole course tree, one cell per unit.
A completed unit's cell is `skill green`; an untouched one is `skill gray`. That is the
only place the learner's actual position is exposed -- duome shows no unit numbers in
the visible UI, and Duolingo's own progress endpoints are long gone.

Output: progress.json (at the source root -- this is user data, not course data)

Two things duome cannot give you:

  * Only the ACTIVE course gets a tree. Other courses appear in the Languages tab with
    summary stats only, so `courses` below lists them all but `units` covers just the
    one you are currently studying. To get another tree, switch course in Duolingo and
    refresh.
  * The `/level/N` in each unit's URL is the number of levels that unit *offers*, not
    the learner's crown level -- untouched units carry it too. Course metadata, not
    progress.

Run refresh-user-profile.py first, or every unit will read as uncompleted.

Usage:
    python fetch-progress.py            # username from username.txt
    python fetch-progress.py Jackicuss
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

import _common as duome

SECTION_RE = re.compile(r'<div class="path-section-delimiter"><hr><span>(.*?)</span>')

# One unit cell: the tile (green = done, gray = not), then the crown link, then the name.
CELL_RE = re.compile(
    r'<div class="skill-cell[^"]*">\s*'
    r'<a[^>]+href="[^"]*?/unit/(\d+)/level/(\d+)"[^>]*class="big skill (\w+)[^"]*"></a>'
    r'.*?<b class="[^"]*" title="[^"]*">(.*?)</b>',
    re.S,
)



def parse_units(html: str) -> list[dict]:
    """Walk the tree in document order so each unit picks up the section above it."""
    sections = [(m.start(), duome.clean(m.group(1))) for m in SECTION_RE.finditer(html)]

    def section_for(pos: int) -> str | None:
        current = None
        for start, name in sections:
            if start < pos:
                current = name
            else:
                break
        return current

    units = []
    for m in CELL_RE.finditer(html):
        number, levels, state, name = m.groups()
        units.append(
            {
                "unit": int(number),
                "name": duome.clean(name),
                "section": section_for(m.start()),
                "levels": int(levels),
                "completed": state == "green",
            }
        )
    return units




def main() -> None:
    user = sys.argv[1] if len(sys.argv) > 1 else duome.username()
    html = duome.profile_html(user)

    units = parse_units(html)
    if not units:
        raise SystemExit("No course tree found -- duome's markup may have changed.")

    done = [u for u in units if u["completed"]]
    through = max((u["unit"] for u in done), default=0)

    # Which course is this tree? The tab header names the language being learned.
    m = re.search(r'<span class="flag (\w+) under"></span><span class="flag m (\w+)"></span>', html)
    src, dst = (m.group(1), m.group(2)) if m else ("en", "ja")
    language = duome.lang_name(dst)

    progress = {
        "source": "duome.eu",
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "username": user,
        "course": f"{src}-{dst}",
        "language": language,
        "through_unit": through,
        "units_completed": len(done),
        "units_total": len(units),
        "sections": sorted({u["section"] for u in units if u["section"]}),
        "units": units,
    }

    out = duome.PROGRESS
    duome.write_json(out, progress)

    # The unit tree lives here, but the headline numbers belong on the course entry in
    # profile.json -- that is the one registry of what this account is studying.
    profile = duome.load_profile()
    if not profile:
        print("  note: no profile.json yet -- run fetch-user-data.py to record the course summary")
    else:
        courses = profile.setdefault("courses", {})
        key = f"{src}-{dst}"
        course = courses.setdefault(key, {"from_language": src, "learning_language": dst, "language": language})
        course.update(
            {
                "through_unit": through,
                "units_completed": len(done),
                "units_total": len(units),
                "wordlist": f"data/languages/{duome.lang_name(src)}/{language.lower()}.csv",
            }
        )
        duome.write_json(duome.PROFILE, profile)

    last = done[-1] if done else None
    print(f"{user} -- {language} (from {src})")
    print(f"  completed {len(done)}/{len(units)} units across {len(progress['sections'])} sections")
    if last:
        print(f"  furthest unit: {last['unit']} \"{last['name']}\" ({last['section']})")
    print("  note: duome renders a tree for the ACTIVE course only; others stay summary-only")
    print(f"wrote {out.relative_to(duome.SOURCE_ROOT.parent.parent)} + course {src}-{dst} in profile.json")


if __name__ == "__main__":
    main()
