"""Shared plumbing for the Duolingo source scripts.

duome.eu is an unofficial Duolingo mirror. It is the only remaining way to get at
course vocabulary and per-unit progress, since Duolingo's own vocabulary endpoints
were withdrawn in 2023. Everything here is plain HTTP against public pages.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://duome.eu"
UA = "Mozilla/5.0 (compatible; Language-Agent/1.0)"

# scripts live at Connections/Duolingo/data/fetch/, so the source root is three up.
HERE = Path(__file__).resolve().parent
SOURCE_ROOT = HERE.parent.parent
PROJECT_ROOT = SOURCE_ROOT.parent.parent
# The language registry and the per-language plugins are owned by the project, not by
# this connection; read them, never write them.
REGISTRY = PROJECT_ROOT / "languages.json"
PLUGINS = PROJECT_ROOT / "Profile" / "data" / "scripts"
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

# duome uses Duolingo's course codes in URLs, which are not always ISO: Mandarin is
# `zs`, not `zh`. This table is only the fallback for codes the registry does not know.
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
    """Readable name for a language code: the registry first, then LANG_NAMES, then the code."""
    entry = language(code)
    if entry:
        return entry["name"]
    return LANG_NAMES.get(code.lower(), code.lower())


def registry() -> dict:
    """languages.json, without its `_doc` key. Empty if the file is missing or unreadable."""
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def language(code: str) -> dict | None:
    """The registry entry for a course code, with its registry key under "code".

    Accepts either the registry key (`zh`) or duome's course code (`zs`), and finally
    matches on name, so a registry whose `duolingo` field is stale still resolves.
    """
    code = code.lower()
    reg = registry()
    for key, entry in reg.items():
        if str(entry.get("duolingo") or "").lower() == code:
            return {"code": key, **entry}
    if code in reg:
        return {"code": code, **reg[code]}
    name = LANG_NAMES.get(code)
    for key, entry in reg.items():
        if name and entry.get("name") == name:
            return {"code": key, **entry}
    return None


def duome_code(code: str) -> str:
    """The course code duome wants in its URLs for a registry key or duome code."""
    entry = registry().get(code.lower())
    return str(entry.get("duolingo") or code) if entry else code


def wordlist_path(src: str, dst: str) -> Path:
    """data/languages/<FromName>/<languagename>.csv -- the CONTRACTS section-5 location."""
    return LANGUAGES / lang_name(src) / f"{lang_name(dst).lower()}.csv"


def load_plugin(plugin: str | None):
    """The language plugin's LANGUAGE object, or None if it is absent or fails to import.

    Plugins live in Profile/data/scripts/languages/ and are owned elsewhere, so a
    missing or broken one degrades to the generic classifier instead of failing.
    """
    if not plugin:
        return None
    if not (PLUGINS / "languages" / f"{plugin}.py").exists():
        return None
    if str(PLUGINS) not in sys.path:
        sys.path.insert(0, str(PLUGINS))
    try:
        module = importlib.import_module(f"languages.{plugin}")
    except Exception as exc:  # someone else's code; never let it sink a scrape
        print(f"  warning: language plugin {plugin!r} failed to import ({exc}); using generic script detection")
        return None
    lang = getattr(module, "LANGUAGE", None)
    return lang if callable(getattr(lang, "script_of", None)) else None


# Unicode block -> script label. Only labels the active language's registry lists are
# ever emitted; CJK ideographs take whichever of kanji/hanzi/hanja that language uses.
_BLOCKS = (("HIRAGANA", "hiragana"), ("KATAKANA", "katakana"), ("HANGUL", "hangul"), ("LATIN", "latin"))
_IDEOGRAPH = ("kanji", "hanzi", "hanja")


def generic_script(word: str, scripts: list[str] | tuple[str, ...] = ()) -> str:
    """Fallback script classifier: a registry script if the word uses exactly one, else latin/mixed."""
    kinds = set()
    for ch in word:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if "IDEOGRAPH" in name:  # CJK unified/compatibility ideographs, and 々
            kinds.add(next((s for s in _IDEOGRAPH if s in scripts), "ideograph"))
            continue
        for block, label in _BLOCKS:
            if name.startswith(block) or f" {block} " in f" {name} ":
                kinds.add(label)
                break
        else:
            kinds.add("other")
    if len(kinds) == 1:
        kind = kinds.pop()
        if kind == "latin" or kind in scripts:
            return kind
    return "mixed"


def script_classifier(code: str):
    """script_of for a course: the language plugin's if there is one, else the generic one."""
    entry = language(code) or {}
    scripts = tuple(entry.get("scripts") or ())
    plugin = load_plugin(entry.get("plugin"))
    if plugin is not None:
        allowed = {*scripts, "latin", "mixed"}

        def classify(word: str) -> str:
            # CONTRACTS section 5: a registry script, latin or mixed. Anything else the
            # plugin answers (e.g. "other") goes to the generic classifier instead.
            try:
                label = plugin.script_of(word)
            except Exception:
                label = None
            return label if label in allowed else generic_script(word, scripts)
        return classify, f"plugin {entry.get('plugin')}"
    return (lambda word: generic_script(word, scripts)), "generic"


def active_course() -> tuple[str, str] | None:
    """(from, to) of the course this account's profile.json marks active, if any."""
    for course in load_profile().get("courses", {}).values():
        if course.get("active") and course.get("from_language") and course.get("learning_language"):
            return course["from_language"], course["learning_language"]
    return None


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
