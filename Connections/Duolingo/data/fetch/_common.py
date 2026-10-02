"""Shared plumbing for the Duolingo source scripts.

duome.eu is an unofficial Duolingo mirror. It is the only remaining way to get at
course vocabulary and per-unit progress, since Duolingo's own vocabulary endpoints
were withdrawn in 2023. Everything here is plain HTTP against public pages.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://duome.eu"
UA = "Mozilla/5.0 (compatible; Language-Agent/1.0)"

# scripts live at Sources/Duolingo/data/fetch/, so the source root is three up.
HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent.parent
DATA = SOURCE_ROOT / "data"
# Word lists are grouped by the language you learn FROM: languages/English/japanese.csv
LANGUAGES = DATA / "languages"
# User data sits at the source root, not under data/ -- it is about the account, not the course.
PROFILE = SOURCE_ROOT / "profile.json"
PROFILE_IMAGE = SOURCE_ROOT / "profile.png"
PROGRESS = SOURCE_ROOT / "progress.json"
ASSETS = SOURCE_ROOT / "assets"

# The profile's stat icons are CSS background images on class names, not <img> tags --
# .icon.exp, .streak, .lingot, .voc, .badge.ruby and so on. To collect them we read the
# stylesheet, map each class token to the image it paints, and download those.
CLASS_RE = re.compile(r'class="([^"]*)"')
BG_URL_RE = re.compile(r"""url\(\s*['"]?(/x/[^)'"]+)['"]?\s*\)""")

# Leading bytes -> format. Duolingo's avatar CDN answers with Content-Type: image,
# which says nothing, so sniff the file instead of trusting the header.
MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",
}

# duome uses ISO-ish codes in URLs; we store under readable folder names.
LANG_NAMES = {
    "ja": "Japanese", "ko": "Korean", "zs": "Chinese", "en": "English",
    "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ru": "Russian", "nl": "Dutch", "sv": "Swedish",
}

TAG_RE = re.compile(r"<[^>]+>")

# Every course row in the profile's Languages tab. The active one carries class "this".
COURSE_RE = re.compile(
    r'<li class="(\w+)-(\w+)-course([^"]*)">.*?'
    r'data-name="([^"]*)".*?'
    r'title="([^"]*)"[^>]*>S</b>.*?'
    r'title="([^"]*)"[^>]*>U</b>.*?'
    r'title="([^"]*)"[^>]*>W</b>.*?'
    r'data-xp="\d+" class="__xp ">(\d+)</b>',
    re.S,
)
ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#039;": "'", "&nbsp;": " "}


def lang_name(code: str) -> str:
    """Folder name for a language code, falling back to the code itself."""
    return LANG_NAMES.get(code.lower(), code.lower())


def username() -> str:
    """The Duolingo username this workspace belongs to."""
    path = SOURCE_ROOT / "username.txt"
    if not path.exists():
        raise SystemExit(f"{path} not found -- run  python setup.py <your-duolingo-username>  from the project root.")
    name = path.read_text(encoding="utf-8").strip()
    if not name:
        raise SystemExit(f"{path} is empty.")
    return name


def clean(raw: str) -> str:
    """Strip tags, decode the handful of entities duome emits, collapse whitespace."""
    text = TAG_RE.sub("", raw)
    for entity, char in ENTITIES.items():
        text = text.replace(entity, char)
    return " ".join(text.split())


def get(path: str) -> str:
    """GET a duome page and return its HTML."""
    url = path if path.startswith("http") else f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")


def post_json(path: str, payload: dict) -> dict:
    """POST a form body to duome and decode the JSON reply."""
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + "/",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def profile_html(user: str) -> str:
    return get(f"/{user}")


def duolingo_id(html: str) -> str | None:
    """Duolingo's numeric user id, which the refresh endpoint needs.

    It is not printed as text anywhere -- the only reliable copy is inside the avatar
    URL, e.g. //simg-ssl.duolingo.com/avatars/1103448031/...
    """
    m = re.search(r"/avatars/(\d+)/", html)
    if m:
        return m.group(1)
    # Fallback: the click handler posts the id literally.
    m = re.search(r"who:\s*'(\d+)'", html)
    return m.group(1) if m else None


def parse_courses(html: str) -> dict[str, dict]:
    """Every course on the account, keyed "en-ja".

    Only the active course gets a unit tree from duome -- the rest carry summary stats
    only. fetch-progress.py fills in through_unit for whichever one is active.
    """
    courses: dict[str, dict] = {}
    for m in COURSE_RE.finditer(html):
        src, dst, classes, name, score, units, words, xp = m.groups()
        courses[f"{src}-{dst}"] = {
            "from_language": src,
            "learning_language": dst,
            "from": lang_name(src),
            "language": clean(name) or lang_name(dst),
            "active": "this" in classes.split(),
            "xp": int(xp),
            "score": clean(score) or None,
            "units": clean(units) or None,
            "words": clean(words) or None,
            # Filled by fetch-progress.py; null means "no tree scraped for this course".
            "through_unit": None,
            "units_completed": None,
            "units_total": None,
            "wordlist": None,
        }
    return courses


def class_tokens(html_fragment: str) -> list[str]:
    """Every distinct class name used inside a fragment, in first-seen order."""
    seen: dict[str, None] = {}
    for match in CLASS_RE.finditer(html_fragment):
        for token in match.group(1).split():
            seen.setdefault(token, None)
    return list(seen)


def stylesheet_assets(css: str, tokens: list[str]) -> dict[str, str]:
    """For each class token, the image its CSS rule paints (last rule wins, as in CSS)."""
    found: dict[str, str] = {}
    for rule in css.split("}"):
        selector, _, body = rule.partition("{")
        url = BG_URL_RE.search(body)
        if not url:
            continue
        for token in tokens:
            # Word-boundary so `.exp` does not also match `.expand`.
            if re.search(rf"\.{re.escape(token)}(?![\w-])", selector):
                found[token] = url.group(1)
    return found


def download_assets(html_fragment: str, css: str, dest: Path) -> dict[str, str]:
    """Save every image the fragment's classes reference. Returns token -> local path."""
    assets = stylesheet_assets(css, class_tokens(html_fragment))
    dest.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}
    for token, url in sorted(assets.items()):
        suffix = Path(url).suffix or ".svg"
        out = dest / f"{token}{suffix}"
        req = urllib.request.Request(BASE + url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                out.write_bytes(resp.read())
        except Exception as exc:  # a missing icon should not sink the whole scrape
            print(f"  warning: could not fetch {url} ({exc})")
            continue
        saved[token] = f"{dest.name}/{out.name}"
    return saved


def load_profile() -> dict:
    """Read the existing profile so a script can update part of it without clobbering."""
    return json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}


def image_format(blob: bytes) -> str | None:
    """Identify an image by its leading bytes, or None if it isn't one we know."""
    for magic, name in MAGIC.items():
        if blob.startswith(magic):
            return name
    return None


def download_image(url: str, dest: Path) -> tuple[int, str | None]:
    """Fetch an image to dest. Returns (bytes written, detected format).

    duome emits protocol-relative URLs (//simg-ssl...), which urllib will not open,
    so they get an explicit scheme first.
    """
    if url.startswith("//"):
        url = "https:" + url
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        blob = resp.read()

    fmt = image_format(blob)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return len(blob), fmt


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
