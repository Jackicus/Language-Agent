"""build_lexicon.main() end to end, against a throwaway tree in a temp directory.

The learner-evidence rule (CLAUDE.md, "Working notes") lives inside main(): upsert is a
closure and the restore loop is inline, so the only way to reach it is a whole build.
Every Path global of the module is remapped into the temp tree first.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

import _support
from _support import jlpt, jmdict

import build_lexicon as bl
import languages

COURSE_COLUMNS = ["unit", "unit_name", "unit_topic", "position", "word", "reading", "gloss",
                  "script", "repeat_units", "audio", "seen"]


def course_row(unit, word, gloss, reading="", repeat="", seen=""):
    return {"unit": unit, "unit_name": f"Unit {unit}", "unit_topic": "topic", "position": 1,
            "word": word, "reading": reading, "gloss": gloss,
            "script": languages.plugin("ja").script_of(word),
            "repeat_units": repeat, "audio": "", "seen": seen}


COURSE = [
    course_row(1, "おちゃ", "green tea|tea", reading="ocha"),
    course_row(1, "たべます", "eat|eats", reading="tabemasu"),
    course_row(2, "コーヒー", "coffee", reading="koohii"),
    course_row(2, "たなか", "Tanaka", reading="tanaka"),
    course_row(3, "アイスコーヒー", "iced coffee"),
    course_row(5, "ピザ", "pizza"),
    course_row(5, "がくせい", "student"),
]

TESTS = {
    "jlpt-n5.csv": [
        jlpt("N5", "お茶", "おちゃ", "green tea"),
        jlpt("N5", "食べる", "たべる", "to eat"),
        jlpt("N5", "コーヒー", "コーヒー", "coffee"),
        jlpt("N5", "学生", "がくせい", "student"),
    ],
}

DICTIONARY = [
    jmdict("お茶", "おちゃ", senses="green tea|tea"),
    jmdict("食べる", "たべる", pos="v1", senses="to eat"),
    jmdict("学生", "がくせい", senses="student"),
]

SRS = {"due": "2026-10-10", "interval": 4, "ease": 2.5}

PRIOR_LEXICON = [
    # Rich learner evidence, and stale derived fields that should be refreshed.
    {"word": "たべます", "gloss": ["STALE"], "rating": 1, "unit": 99, "confidence": "known",
     "seen_count": 3, "first_seen": "2026-01-01", "last_seen": "2026-09-30", "srs": SRS},
    # unseen, now reached (unit 1 <= 2): promote.
    {"word": "おちゃ", "confidence": "unseen", "seen_count": 0, "first_seen": "2026-01-01", "srs": None},
    # shaky, past the position (unit 3 > 2): evidence outranks the marker.
    {"word": "アイスコーヒー", "confidence": "shaky", "seen_count": 1, "first_seen": "2026-02-01",
     "last_seen": "2026-02-02", "srs": None},
    # exposed, past the position (unit 5 > 2): never demoted by a rebuild.
    {"word": "ピザ", "confidence": "exposed", "seen_count": 0, "first_seen": "2026-01-01", "srs": None},
    # unseen, still not reached: stays unseen.
    {"word": "がくせい", "confidence": "unseen", "seen_count": 0, "first_seen": "2026-01-01", "srs": None},
]
PRIOR_NAMES = [
    {"word": "たなか", "confidence": "known", "seen_count": 2, "first_seen": "2026-01-01",
     "last_seen": "2026-03-03", "srs": None},
]


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_jsonl(path: Path) -> dict[str, dict]:
    return {r["word"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


class BuildCase(unittest.TestCase):
    course = COURSE
    through_unit = 2
    prior_lexicon = PRIOR_LEXICON
    prior_names = PRIOR_NAMES

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        duo = self.root / "Connections" / "Duolingo"
        write_csv(duo / "data" / "languages" / "English" / "japanese.csv", COURSE_COLUMNS, self.course)
        (duo / "profile.json").write_text(json.dumps({"courses": {"en-ja": {
            "from_language": "en", "learning_language": "ja", "active": True,
            "through_unit": self.through_unit, "wordlist": "data/languages/English/japanese.csv",
        }}}), encoding="utf-8")
        for name, rows in TESTS.items():
            write_csv(self.root / "Resources" / "Tests" / "Japanese" / name,
                      ["level", "expression", "reading", "meaning", "tags"], rows)
        write_csv(self.root / "Resources" / "Dictionary" / "Japanese" / "jmdict.csv",
                  _support.DICTIONARY_COLUMNS, DICTIONARY)
        # The pre-registry flat layout: every build here also exercises the move to ja/.
        write_jsonl(self.root / "Profile" / "lexicon.jsonl", self.prior_lexicon)
        write_jsonl(self.root / "Profile" / "names.jsonl", self.prior_names)

        stack = _support.sandbox(bl, self.root)
        self.addCleanup(stack.close)
        _support.assert_sandboxed(self, bl, self.root)

    def build(self, *argv):
        with mock.patch.object(sys, "argv", ["build_lexicon.py", *argv]), redirect_stdout(io.StringIO()):
            bl.main()
        self.lexicon = read_jsonl(bl.lexicon_path("ja"))
        self.names = read_jsonl(bl.names_path("ja"))
        return self.lexicon


class TestLearnerEvidenceSurvives(BuildCase):
    def test_rich_evidence_untouched(self):
        rec = self.build()["たべます"]
        self.assertEqual(rec["confidence"], "known")
        self.assertEqual(rec["seen_count"], 3)
        self.assertEqual(rec["srs"], SRS)
        self.assertEqual(rec["first_seen"], "2026-01-01")
        self.assertEqual(rec["last_seen"], "2026-09-30")

    def test_derived_fields_refreshed(self):
        rec = self.build()["たべます"]
        self.assertEqual(rec["gloss"], ["eat", "eats"])
        self.assertEqual(rec["unit"], 1)
        self.assertEqual((rec["listed"], rec["rating"], rec["rating_source"]), (True, 5, "inflection"))

    def test_survives_two_rebuilds(self):
        self.build()
        rec = self.build()["たべます"]
        self.assertEqual((rec["confidence"], rec["seen_count"], rec["srs"]), ("known", 3, SRS))

    def test_names_keep_evidence(self):
        self.build()
        self.assertNotIn("たなか", self.lexicon)
        rec = self.names["たなか"]
        self.assertEqual((rec["confidence"], rec["seen_count"], rec["last_seen"]), ("known", 2, "2026-03-03"))


class TestCoursePosition(BuildCase):
    def test_unseen_promoted_when_reached(self):
        self.assertEqual(self.build()["おちゃ"]["confidence"], "exposed")

    def test_unseen_stays_unseen_when_not_reached(self):
        self.assertEqual(self.build()["がくせい"]["confidence"], "unseen")

    def test_exposed_never_demoted(self):
        self.assertEqual(self.build()["ピザ"]["confidence"], "exposed")

    def test_shaky_never_demoted(self):
        self.assertEqual(self.build()["アイスコーヒー"]["confidence"], "shaky")

    def test_known_never_changed_by_lower_override(self):
        self.assertEqual(self.build("--through-unit", "0")["たべます"]["confidence"], "known")

    def test_override_promotes(self):
        self.assertEqual(self.build("--through-unit", "5")["がくせい"]["confidence"], "exposed")

    def test_new_words(self):
        lex = self.build()
        self.assertEqual(lex["コーヒー"]["confidence"], "exposed")          # unit 2 <= 2
        self.assertEqual(lex["コーヒー"]["seen_count"], 0)
        self.assertEqual(lex["コーヒー"]["first_seen"], date.today().isoformat())
        self.assertIsNone(lex["コーヒー"]["srs"])
        self.assertEqual(lex["食べる"]["confidence"], "unseen")             # test-only, no unit


class TestMerge(BuildCase):
    def test_spellings_deduplicated(self):
        lex = self.build()
        self.assertNotIn("お茶", lex)
        self.assertEqual(sorted(lex["おちゃ"]["sources"]), ["duolingo", "tests"])
        self.assertEqual(lex["おちゃ"]["kanji"], "お茶")

    def test_listed_and_rating_separate(self):
        lex = self.build()
        self.assertEqual((lex["コーヒー"]["listed"], lex["コーヒー"]["rating"]), (True, 5))
        self.assertNotIn("jlpt", lex["コーヒー"])
        self.assertEqual((lex["アイスコーヒー"]["listed"], lex["アイスコーヒー"]["rating"],
                          lex["アイスコーヒー"]["rating_source"]), (False, 5, "contains"))

    def test_course_position_is_last_resort(self):
        rec = self.build()["ピザ"]
        self.assertEqual((rec["listed"], rec["rating"], rec["rating_source"]), (False, 5, "course-position"))

    def test_names_split_out(self):
        self.build()
        self.assertIn("たなか", self.names)
        self.assertEqual(self.names["たなか"]["rating_source"], "name-kana")

    def test_dry_run_writes_nothing(self):
        flat = bl.PROFILE_DIR / "lexicon.jsonl"
        before = flat.read_bytes()
        with mock.patch.object(sys, "argv", ["build_lexicon.py", "--dry-run"]), redirect_stdout(io.StringIO()):
            bl.main()
        self.assertEqual(flat.read_bytes(), before)        # not even migrated
        self.assertFalse(bl.lexicon_path("ja").parent.exists())
        self.assertFalse(bl.PROFILE.exists())

    def test_profile_mirrors_course_position(self):
        self.build()
        profile = json.loads(bl.PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile["connections"]["Duolingo"]["through_unit"], 2)


class TestFirstUnitWins(BuildCase):
    """CLAUDE.md: `unit` is the unit that first introduces the word.

    BUG: when two course rows resolve to the same JMdict entry (おちゃ in unit 1, お茶 in
    unit 66), upsert's `for field, value in extra.items(): record[field] = value` lets the
    LATER row overwrite unit / unit_name / romaji / repeat_units / audio. On the real
    data 607 of 609 such pairs end up with the later unit (おちゃ -> 66, すし -> 202).
    With course position 20, a fresh build marks them `unseen`, and lexicon.usable()
    drops them from chat even when confidence survives.
    """

    course = [course_row(1, "おちゃ", "green tea", reading="ocha"),
              course_row(66, "お茶", "green tea", reading="o-cha")]
    through_unit = 20
    prior_lexicon = []
    prior_names = []

    def test_earliest_unit_kept(self):
        rec = self.build()["おちゃ"]
        self.assertEqual(rec["unit"], 1)
        self.assertEqual(rec["confidence"], "exposed")

    def test_both_spellings_collapse(self):
        lex = self.build()
        self.assertIn("おちゃ", lex)
        self.assertNotIn("お茶", lex)


if __name__ == "__main__":
    unittest.main()
