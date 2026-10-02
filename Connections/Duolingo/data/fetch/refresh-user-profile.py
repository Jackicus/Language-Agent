#!/usr/bin/env python3
"""Ask duome.eu to re-pull this profile from Duolingo.

duome caches. Until you refresh, the page serves whatever it last saw -- which can be
months stale, with every unit showing as uncompleted. The site exposes this as a small
refresh control next to the username; behind it is a plain form POST:

    POST /aggiorna.php   who=<duolingo numeric id>   -> JSON

So no browser automation is needed. Run this before fetch-user-data / fetch-progress,
or those will happily record stale numbers.

Usage:
    python refresh-user-profile.py            # username from username.txt
    python refresh-user-profile.py Jackicuss
"""

from __future__ import annotations

import sys

import _common as duome


def main() -> None:
    user = sys.argv[1] if len(sys.argv) > 1 else duome.username()

    html = duome.profile_html(user)
    uid = duome.duolingo_id(html)
    if not uid:
        raise SystemExit(f"Could not find a Duolingo id on /{user} -- is the username right?")

    print(f"refreshing {user} (duolingo id {uid}) ...")
    data = duome.post_json("/aggiorna.php", {"who": uid})

    if not data.get("id"):
        # duome returns a bodyless reply when the Duolingo profile is set to private.
        raise SystemExit("No response from Duolingo -- the profile is likely in private mode.")

    xp = data.get("totalXp")
    if xp is None:
        xp = sum(lang.get("points", 0) for lang in data.get("languages") or [])
    streak = data.get("streak") or data.get("site_streak")

    print(f"refreshed: {data.get('username')} -- {xp} XP, {streak} day streak, {data.get('rupees')} lingots")
    print("duome now holds current data; run fetch-user-data.py and fetch-progress.py to record it.")


if __name__ == "__main__":
    main()
