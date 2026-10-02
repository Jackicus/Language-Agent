#!/usr/bin/env python3
"""One command from nothing to a lexicon /chat can use.

    python setup.py                      full first run (needs username.txt or a username)
    python setup.py <duolingo-username>  write Connections/Duolingo/username.txt, then full run
    python setup.py --check              doctor: what is present / missing / stale; no network
    python setup.py --sync               daily refresh: Duolingo + build + showcase
    python setup.py --refresh            full run, re-fetching JLPT and JMdict even if present
    python setup.py --no-showcase        skip build_showcase.py (combinable)

Every successful run ends with one machine-readable line:  SUMMARY {...json...}
"""

import sys

# The real floor: build_lexicon.py uses str.removeprefix and dict | dict (3.9). Kept
# above every other line so an old interpreter gets this sentence, not a traceback.
MIN_PYTHON = (3, 9)
if sys.version_info < MIN_PYTHON:
    sys.exit("Language-Agent needs Python %d.%d or newer; this is %d.%d. Install a newer Python and re-run."
             % (MIN_PYTHON + sys.version_info[:2]))

import argparse
import collections
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
DUO = ROOT / "Connections" / "Duolingo"
FETCH = DUO / "data" / "fetch"
USERNAME = DUO / "username.txt"
SCRIPTS = ROOT / "Profile" / "data" / "scripts"
LEXICON = ROOT / "Profile" / "lexicon.jsonl"
JLPT = [ROOT / "Resources" / "Tests" / "Japanese" / f"jlpt-n{n}.csv" for n in (5, 4, 3, 2, 1)]
JMDICT = ROOT / "Resources" / "Dictionary" / "Japanese" / "jmdict.csv"
STALE_AFTER = 24 * 3600  # Duolingo artefacts older than a day are worth a --sync

# The last line of a traceback when the network, not the code, is at fault.
NETWORK_RE = re.compile(r"^(urllib\.error\.\w+|socket\.\w+|ssl\.\w+|http\.client\.\w+|TimeoutError|"
                        r"Connection\w*Error|BrokenPipeError)\b")


@dataclass
class Step:
    title: str
    script: Path
    args: list = field(default_factory=list)
    outputs: list = field(default_factory=list)  # artefacts this step writes
    kind: str = "duolingo"                       # duolingo | resource | build | showcase
    host: str = "duome.eu"
    hint: str = ""


STEPS = [
    Step("Refreshing duome's copy of your profile", FETCH / "refresh-user-profile.py",
         hint="Check the Duolingo username (it must match your profile exactly) and that the profile is public."),
    Step("Fetching account profile", FETCH / "fetch-user-data.py", outputs=[DUO / "profile.json"]),
    Step("Fetching unit tree", FETCH / "fetch-progress.py", outputs=[DUO / "progress.json"],
         hint="Make sure Japanese is your active course in Duolingo, then re-run."),
    Step("Fetching course word list", FETCH / "fetch-word-lists.py", ["en", "ja"],
         outputs=[DUO / "data" / "languages" / "English" / "japanese.csv"]),
    Step("Fetching JLPT word lists", ROOT / "Resources" / "Tests" / "data" / "fetch" / "fetch-jlpt.py",
         outputs=JLPT, kind="resource", host="GitHub"),
    Step("Fetching JMdict dictionary", ROOT / "Resources" / "Dictionary" / "data" / "fetch" / "fetch-jmdict.py",
         outputs=[JMDICT], kind="resource", host="GitHub"),
    Step("Building lexicon", SCRIPTS / "build_lexicon.py", outputs=[LEXICON], kind="build", host=""),
    Step("Building showcase", SCRIPTS / "build_showcase.py", outputs=[ROOT / "showcase.html"],
         kind="showcase", host=""),
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def age(path: Path) -> str:
    secs = time.time() - path.stat().st_mtime
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs / size:.0f}{unit}"
    return f"{secs:.0f}s"


def stats() -> dict:
    """`lexicon.py stats` as a dict, or {} when there is no lexicon to read."""
    if not LEXICON.exists():
        return {}
    proc = subprocess.run([sys.executable, str(SCRIPTS / "lexicon.py"), "stats"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else {}
    except ValueError:
        return {}


def run_step(n: int, total: int, step: Step) -> float:
    """Run one step, streaming its output. Exits the whole run on failure."""
    print(f"\n[{n}/{total}] {step.title}", flush=True)
    started = time.monotonic()
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    tail = collections.deque(maxlen=12)
    traceback = []  # held back: shown only if the failure turns out not to be the network
    proc = subprocess.Popen([sys.executable, str(step.script), *step.args], cwd=step.script.parent, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if traceback or line.startswith("Traceback (most recent call last)"):
                traceback.append(line)
            else:
                print("    " + line, flush=True)
            tail.append(line)
        code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        sys.exit(f"\ninterrupted during [{n}/{total}] {step.title}")
    if code == 0:
        took = time.monotonic() - started
        print(f"    done in {took:.1f}s")
        return took

    last = next((l.strip() for l in reversed(tail) if l.strip()), "(no output)")
    print(f"\nFAILED at [{n}/{total}] {step.title} ({rel(step.script)}, exit {code})", file=sys.stderr)
    if traceback and NETWORK_RE.match(last):
        print(f"    could not reach {step.host or 'the network'}: {last}", file=sys.stderr)
        hint = f"Check your internet connection and re-run; {step.host} is sometimes slow or briefly down."
    else:
        for line in (traceback[-12:] if traceback else list(tail)[-6:]):
            print("    " + line, file=sys.stderr)
        hint = step.hint or f"Re-run python setup.py; to debug, run it alone: cd {rel(step.script.parent)} && " \
                            f"python {step.script.name} {' '.join(step.args)}".rstrip()
    print(f"try: {hint}", file=sys.stderr)
    sys.exit(code or 1)


def check() -> int:
    """Print what exists and how old it is. No network. 0 when /chat has words to use."""
    rows, missing, stale = [(USERNAME, None)], [], []
    rows += [(out, step) for step in STEPS for out in step.outputs]
    print(f"{'status':<8} {'age':>5}  artefact")
    for path, step in rows:
        state, when = "missing", "-"
        if path.exists():
            state, when = "ok", age(path)
            secs = time.time() - path.stat().st_mtime
            if step and step.kind == "duolingo" and secs > STALE_AFTER:
                state = "stale"
            if step and step.kind in ("build", "showcase"):
                inputs = [o for s in STEPS if s.kind in ("duolingo", "resource") for o in s.outputs] \
                    if step.kind == "build" else [LEXICON]
                if any(i.exists() and i.stat().st_mtime > path.stat().st_mtime for i in inputs):
                    state = "stale"
        (missing if state == "missing" else stale if state == "stale" else []).append(rel(path))
        note = f"  ({USERNAME.read_text(encoding='utf-8').strip()})" if path == USERNAME and path.exists() else ""
        print(f"{state:<8} {when:>5}  {rel(path)}{note}")

    s = stats()
    through, usable = s.get("through_unit"), s.get("usable_for_chat", 0)
    ready = bool(s) and usable > 0 and through is not None
    if s:
        print(f"\nlexicon: {s.get('total', 0):,} words · through unit {through} · {usable:,} usable for chat")
    if ready:
        print("READY for /chat" + ("  (some artefacts are stale: python setup.py --sync)" if stale else ""))
    else:
        why = "no lexicon yet" if not s else "no unit recorded" if through is None else "no usable words"
        cmd = "python setup.py" if USERNAME.exists() else "python setup.py <your-duolingo-username>"
        print(f"NOT READY ({why}) -- run  {cmd}  (or type /setup in Claude Code)")
    print("SUMMARY " + json.dumps({"ready": ready, "through_unit": through, "usable": usable,
                                   "total": s.get("total", 0), "missing": missing, "stale": stale}))
    return 0 if ready else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username", nargs="?", help="your Duolingo username (written to username.txt)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report what is present/missing/stale; no network")
    mode.add_argument("--sync", action="store_true", help="daily refresh; JLPT and JMdict only if missing")
    mode.add_argument("--refresh", action="store_true", help="full run, re-fetching JLPT and JMdict")
    ap.add_argument("--no-showcase", action="store_true", help="skip building showcase.html")
    args = ap.parse_args()

    if args.check:
        if args.username:
            ap.error("--check takes no username")
        return check()

    old = None
    if args.username:
        name = args.username.strip().lstrip("@")
        if not re.fullmatch(r"[\w.-]+", name):
            ap.error(f"{args.username!r} does not look like a Duolingo username")
        old = USERNAME.read_text(encoding="utf-8").strip() if USERNAME.exists() else None
        USERNAME.write_text(name + "\n", encoding="utf-8")
        print(f"username: {name}" + (f" (was {old})" if old and old != name else "") + f" -> {rel(USERNAME)}")
    elif not USERNAME.exists() or not USERNAME.read_text(encoding="utf-8").strip():
        print("No Duolingo username yet -- run  python setup.py <your-duolingo-username>", file=sys.stderr)
        return 2

    before = stats()
    steps = [s for s in STEPS if not (args.no_showcase and s.kind == "showcase")]
    started, skipped = time.monotonic(), []
    try:
        for n, step in enumerate(steps, 1):
            if step.kind == "resource" and not args.refresh and all(p.exists() for p in step.outputs):
                print(f"\n[{n}/{len(steps)}] {step.title} -- skipped, already present (--refresh to re-fetch)")
                skipped.append(step.script.name)
                continue
            run_step(n, len(steps), step)
    except SystemExit:
        if old and args.username and old != USERNAME.read_text(encoding="utf-8").strip():
            USERNAME.write_text(old + "\n", encoding="utf-8")  # a typo must not replace a working name
            print(f"restored username.txt to {old}", file=sys.stderr)
        raise

    after = stats()
    if not after:
        print("The build finished but lexicon.py stats could not read the result.", file=sys.stderr)
        return 1
    usable = after.get("usable_for_chat", 0)
    summary = {
        "through_unit": after.get("through_unit"), "usable": usable, "total": after.get("total"),
        "new_usable": usable - before["usable_for_chat"] if before else 0, "first_run": not before,
        "username": USERNAME.read_text(encoding="utf-8").strip(),
        "mode": "sync" if args.sync else "refresh" if args.refresh else "setup",
        "skipped": skipped, "seconds": round(time.monotonic() - started, 1),
    }
    if not args.no_showcase:
        summary["showcase"] = str(ROOT / "showcase.html")
    change = "first run" if summary["first_run"] else f"{summary['new_usable']:+,} since last run"
    print(f"\nready: {usable:,} words usable for chat (through unit {summary['through_unit']}), "
          f"{change} · {summary['seconds']}s")
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
