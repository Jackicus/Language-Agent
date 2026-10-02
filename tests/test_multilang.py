"""Multi-language behaviour of build_lexicon and lexicon.py (CONTRACTS sections 1, 3, 5, 9).

  * listed / rating with a six-level language (CEFR: A1 = 6 .. C2 = 1)
  * the `seen` promotion rule (Anki-style connections without units)
  * the per-language Profile layout, and the flat -> ja/ migration
  * discovery picks only the active language's table from each connection
  * the dictionary loader refuses the old JMdict header
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import _support
from _support import CEFR, entry, jlpt

import build_lexicon as bl
import languages
import lexicon as lx
from test_build import COURSE_COLUMNS, read_jsonl, write_csv, write_jsonl


def row(word, gloss, unit="", seen="", reading=""):
    return {"unit": unit, "unit_name": f"Unit {unit}" if unit != "" else "", "unit_topic": "",
            "position": 1, "word": word, "reading": reading, "gloss": gloss, "script": "latin",
            "repeat_units": "", "audio": "", "seen": seen}


FR_TESTS = [
    jlpt("A1", "chat", "", "cat"),
    jlpt("A1", "manger", "", "to eat"),
    jlpt("A1", "le", "", "the"),
    jlpt("A2", "acheter", "", "to buy"),
    jlpt("B1", "pomme", "", "apple"),
    jlpt("B2", "terre", "", "earth, ground"),
    jlpt("C2", "pourtant", "", "however"),
    jlpt("A1", "café", "", "coffee"),
]
FR_DICTIONARY = [entry("chat", senses="cat", pos="n"), entry("pomme de terre", senses="potato", pos="n")]

DUOLINGO_FR = [
    row("chat", "cat", unit=1),
    row("chats", "cats", unit=1),
    row("mangeons", "we eat", unit=2),
    row("achète", "buys", unit=3),
    row("le chat", "the cat", unit=3),
    row("pomme terre", "apple earth", unit=4),
    row("pourtant", "however", unit=9),
    row("Paris", "Paris", unit=2),
    row("croissant", "croissant", unit=2),
]
ANKI_FR = [
    row("pourtant", "however", seen="1"),       # past the Duolingo position, but met in Anki
    row("pomme", "apple", seen="1"),
    row("terre", "earth", seen="0"),
]


class Tree(unittest.TestCase):
    """A throwaway project tree; every Path global of both scripts is remapped into it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for module in (bl, lx):
            stack = _support.sandbox(module, self.root)
            self.addCleanup(stack.close)
            _support.assert_sandboxed(self, module, self.root)

    def profile(self) -> dict:
        return json.loads(bl.PROFILE.read_text(encoding="utf-8")) if bl.PROFILE.exists() else {}

    def set_language(self, code_or_name):
        bl.PROFILE.parent.mkdir(parents=True, exist_ok=True)
        bl.PROFILE.write_text(json.dumps({"language": code_or_name}), encoding="utf-8")

    def build(self, *argv) -> str:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["build_lexicon.py", *argv]), redirect_stdout(out):
            bl.main()
        return out.getvalue()

    def cli(self, *argv) -> str:
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["lexicon.py", *argv]), redirect_stdout(out):
            lx.main()
        return out.getvalue()


class FrenchTree(Tree):
    through_unit = 3

    def setUp(self):
        super().setUp()
        duo = self.root / "Connections" / "Duolingo"
        write_csv(duo / "data" / "languages" / "English" / "french.csv", COURSE_COLUMNS, DUOLINGO_FR)
        # A Japanese table in the same connection must be ignored while French is active.
        write_csv(duo / "data" / "languages" / "English" / "japanese.csv", COURSE_COLUMNS,
                  [row("すし", "sushi", unit=1)])
        (duo / "profile.json").write_text(json.dumps({"courses": {"en-fr": {
            "from_language": "en", "learning_language": "fr", "active": True,
            "through_unit": self.through_unit, "wordlist": "data/languages/English/french.csv"}}}),
            encoding="utf-8")
        anki = self.root / "Connections" / "Anki"
        write_csv(anki / "data" / "languages" / "English" / "french.csv", COURSE_COLUMNS, ANKI_FR)
        (anki / "profile.json").write_text(json.dumps({"courses": {"en-fr": {"through_unit": None}}}),
                                           encoding="utf-8")
        # File names follow the registry's sources: Tests/French/<source>-a1.csv,
        # Dictionary/French/<source>.csv (any CSV when the registry names none).
        spec = languages.spec("fr")
        tests_source = spec["tests"].get("source") or "freq"
        dictionary_source = spec["dictionary"].get("source") or "dictionary"
        write_csv(self.root / "Resources" / "Tests" / "French" / f"{tests_source}-a1.csv",
                  _support.TEST_COLUMNS, FR_TESTS)
        write_csv(self.root / "Resources" / "Dictionary" / "French" / f"{dictionary_source}.csv",
                  _support.DICTIONARY_COLUMNS, FR_DICTIONARY)
        self.set_language("fr")
        self.build()
        self.lex = read_jsonl(bl.lexicon_path("fr"))
        self.names = read_jsonl(bl.names_path("fr"))


class TestSixLevelGrading(FrenchTree):
    def test_easiest_is_six_hardest_is_one(self):
        self.assertEqual((self.lex["chat"]["listed"], self.lex["chat"]["rating"]), (True, 6))
        self.assertEqual((self.lex["pourtant"]["listed"], self.lex["pourtant"]["rating"]), (True, 1))
        self.assertEqual(self.lex["pomme"]["rating"], 4)     # B1

    def test_plural_inflection(self):
        rec = self.lex["chats"]
        self.assertEqual((rec["listed"], rec["rating"], rec["rating_source"], rec["matched"]),
                         (True, 6, "inflection", "chat"))

    def test_accent_insensitive_lemma_is_a_tie_breaker(self):
        """achète -> achèter by rule; only the accent-folded lookup reaches acheter."""
        rec = self.lex["achète"]
        self.assertEqual((rec["rating_source"], rec["matched"], rec["rating"]), ("inflection", "acheter", 5))

    def test_accent_never_folded_for_exact_tiers(self):
        """cafe is not the listed café: at most an inferred grade (stem, via the sense)."""
        g = _support.grader([jlpt("A1", "café", "", "coffee")], code="fr")
        listed, _, how, _ = g.grade("cafe", ["coffee"], None)
        self.assertFalse(listed)
        self.assertNotIn(how, ("expression", "reading", "variant", "inflection"))
        self.assertEqual(g.grade("cafe", ["bistro"], None), (False, None, None, None))

    def test_article_never_a_composite_part(self):
        rec = self.lex["le chat"]
        self.assertNotEqual(rec["rating_source"], "composite")
        self.assertEqual((rec["rating_source"], rec["matched"]), ("contains", "chat"))

    def test_multiword_composite_at_hardest_part(self):
        rec = self.lex["pomme terre"]
        self.assertEqual((rec["listed"], rec["rating"], rec["rating_source"], rec["matched"]),
                         (False, 3, "composite", "pomme+terre"))

    def test_single_word_never_searched_for_substrings(self):
        """croissant must not inherit from any listed piece inside it."""
        self.assertEqual(self.lex["croissant"]["rating_source"], "course-position")
        self.assertEqual(self.lex["croissant"]["rating"], 6)

    def test_names_split(self):
        self.assertIn("Paris", self.names)
        self.assertNotIn("Paris", self.lex)
        self.assertEqual(self.names["Paris"]["rating"], 6)

    def test_generic_fields(self):
        rec = self.lex["chat"]
        self.assertEqual(rec["headword"], "chat")
        self.assertNotIn("kana", rec)
        self.assertEqual(rec["language"], "French")
        self.assertEqual(sorted(rec["sources"]), ["duolingo", "tests"])

    def test_course_rating_bands(self):
        self.assertEqual([bl.course_rating(u, CEFR) for u in (1, 100, 101, 900, 5000)], [6, 6, 5, 2, 1])
        self.assertEqual([bl.course_rating(u, _support.JA_LEVELS) for u in (100, 250, 500, 800, 801)],
                         [5, 4, 3, 2, 1])


class TestSeenPromotion(FrenchTree):
    def test_seen_promotes_past_the_unit_gate(self):
        rec = self.lex["pourtant"]                          # Duolingo unit 9 > position 3
        self.assertEqual(rec["confidence"], "exposed")
        self.assertTrue(rec["seen"])
        self.assertEqual(sorted(rec["sources"]), ["anki", "duolingo", "tests"])
        self.assertEqual(rec["unit"], 9)                    # Anki never displaces the unit

    def test_seen_without_units(self):
        self.assertEqual(self.lex["pomme"]["confidence"], "exposed")

    def test_unseen_card_stays_unseen(self):
        self.assertEqual(self.lex["terre"]["confidence"], "unseen")
        self.assertNotIn("seen", self.lex["terre"])

    def test_seen_never_demotes_or_overrides_evidence(self):
        path = bl.lexicon_path("fr")
        records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        for r in records:
            if r["word"] == "pourtant":
                r["confidence"] = "shaky"
            if r["word"] == "pomme":
                r["confidence"] = "known"
        write_jsonl(path, records)
        self.build()
        lex = read_jsonl(path)
        self.assertEqual(lex["pourtant"]["confidence"], "shaky")
        self.assertEqual(lex["pomme"]["confidence"], "known")

    def test_connection_without_units_has_no_position(self):
        connections = self.profile()["connections"]
        self.assertEqual(connections["Duolingo"]["through_unit"], 3)
        self.assertIsNone(connections["Anki"]["through_unit"])

    def test_lexicon_py_lets_seen_words_through_the_gate(self):
        words = {r["word"] for r in lx.usable(list(self.lex.values()), 3)}
        self.assertIn("pourtant", words)


class TestDiscovery(FrenchTree):
    def test_only_active_language_table(self):
        self.assertNotIn("すし", self.lex)
        self.assertNotIn("すし", self.names)

    def test_root_override(self):
        other = self.root / "elsewhere"
        write_csv(other / "Connections" / "Mine" / "data" / "languages" / "English" / "french.csv",
                  COURSE_COLUMNS, [row("bonjour", "hello", seen="1")])
        try:
            self.build("--root", str(other))
        finally:
            bl.CONNECTIONS, bl.RESOURCES = self.root / "Connections", self.root / "Resources"
        lex = read_jsonl(bl.lexicon_path("fr"))
        self.assertEqual(set(lex), {"bonjour"})
        self.assertEqual(lex["bonjour"]["sources"], ["mine"])


class TestPerLanguageLayout(FrenchTree):
    def test_written_under_code(self):
        self.assertTrue(bl.lexicon_path("fr").exists())
        self.assertEqual(bl.lexicon_path("fr"), bl.PROFILE_DIR / "fr" / "lexicon.jsonl")
        self.assertFalse((bl.PROFILE_DIR / "lexicon.jsonl").exists())
        self.assertEqual(self.profile()["language"], "fr")

    def test_lexicon_py_reads_active_language(self):
        stats = json.loads(self.cli("stats"))
        self.assertEqual(stats["language"], "fr")
        self.assertEqual(stats["total"], len(self.lex))
        self.assertEqual(list(stats["by_rating"]), CEFR)

    def test_tests_command_any_number_of_levels(self):
        report = json.loads(self.cli("tests"))
        self.assertEqual(list(report["levels"]), [l for l in CEFR if l in report["levels"]])
        self.assertIn("C2", report["levels"])
        self.assertIn("A1", report["levels"])

    def test_quiz_labels_use_registry_levels(self):
        out = json.loads(self.cli("quiz", "--count", "3", "--seed", "1"))
        for item in out["items"]:
            self.assertIn(item["rating"], CEFR)

    def test_switching_language_keeps_both(self):
        fr_bytes = bl.lexicon_path("fr").read_bytes()
        duo = self.root / "Connections" / "Duolingo" / "data" / "languages" / "English"
        write_csv(self.root / "Resources" / "Tests" / "Japanese" / "jlpt-n5.csv", _support.TEST_COLUMNS,
                  [jlpt("N5", "すし", "すし", "sushi")])
        self.assertTrue((duo / "japanese.csv").exists())
        self.build("--language", "ja")
        self.assertEqual(self.profile()["language"], "ja")
        self.assertTrue(bl.lexicon_path("ja").exists())
        self.assertEqual(bl.lexicon_path("fr").read_bytes(), fr_bytes)
        self.assertNotIn("Anki", self.profile()["connections"])   # positions belong to a language


class TestMigration(Tree):
    LEX = [{"word": "も", "confidence": "known", "seen_count": 2, "first_seen": "2026-01-01",
            "last_seen": "2026-02-02", "srs": {"box": 2, "due": "2026-03-01", "last": "2026-02-02"}}]

    def setUp(self):
        super().setUp()
        write_jsonl(bl.PROFILE_DIR / "lexicon.jsonl", self.LEX)
        write_jsonl(bl.PROFILE_DIR / "names.jsonl", [{"word": "たなか", "confidence": "exposed"}])
        self.flat = (bl.PROFILE_DIR / "lexicon.jsonl").read_bytes()
        self.flat_names = (bl.PROFILE_DIR / "names.jsonl").read_bytes()

    def test_moves_byte_for_byte(self):
        moved = languages.migrate_flat(bl.PROFILE_DIR, "ja")
        self.assertEqual(moved, ["lexicon.jsonl", "names.jsonl"])
        self.assertEqual((bl.PROFILE_DIR / "ja" / "lexicon.jsonl").read_bytes(), self.flat)
        self.assertEqual((bl.PROFILE_DIR / "ja" / "names.jsonl").read_bytes(), self.flat_names)
        self.assertFalse((bl.PROFILE_DIR / "lexicon.jsonl").exists())

    def test_never_over_an_existing_ja(self):
        (bl.PROFILE_DIR / "ja").mkdir()
        self.assertEqual(languages.migrate_flat(bl.PROFILE_DIR, "ja"), [])
        self.assertTrue((bl.PROFILE_DIR / "lexicon.jsonl").exists())

    def test_only_for_japanese(self):
        self.assertEqual(languages.migrate_flat(bl.PROFILE_DIR, "fr"), [])

    def test_lexicon_py_migrates_on_first_read(self):
        out = json.loads(self.cli("look", "も"))
        self.assertEqual(out["も"]["confidence"], "known")
        self.assertEqual((bl.PROFILE_DIR / "ja" / "lexicon.jsonl").read_bytes(), self.flat)

    def test_missing_language_defaults_to_ja_and_is_written(self):
        self.assertFalse(bl.PROFILE.exists())
        self.assertEqual(languages.active_code(bl.PROFILE), "ja")
        self.assertEqual(self.profile()["language"], "ja")

    def test_legacy_language_name_mapped_to_code(self):
        self.set_language("Japanese")
        self.assertEqual(languages.active_code(bl.PROFILE), "ja")
        self.assertEqual(self.profile()["language"], "ja")

    def test_unknown_language_rejected(self):
        self.set_language("Klingon")
        with self.assertRaises(SystemExit):
            languages.active_code(bl.PROFILE)


class TestDictionarySchema(Tree):
    def test_old_header_refused(self):
        write_csv(bl.RESOURCES / "Dictionary" / "Japanese" / "jmdict.csv",
                  ["kanji", "kana", "kanji_all", "kana_all", "pos", "senses", "common"], [])
        with self.assertRaises(SystemExit) as ctx:
            bl.load_dictionary("Japanese", "jmdict")
        self.assertIn("fetch-jmdict.py", str(ctx.exception))

    def test_generic_header_loads(self):
        write_csv(bl.RESOURCES / "Dictionary" / "Japanese" / "jmdict.csv", _support.DICTIONARY_COLUMNS,
                  [_support.jmdict("お茶", "おちゃ", senses="green tea")])
        rows = bl.load_dictionary("Japanese", "jmdict")
        self.assertEqual((rows[0]["headword"], rows[0]["reading"]), ("お茶", "おちゃ"))

    def test_unknown_test_levels_dropped(self):
        write_csv(bl.RESOURCES / "Tests" / "French" / "x-a1.csv", _support.TEST_COLUMNS,
                  [jlpt("A1", "chat", "", "cat"), jlpt("N5", "すし", "", "sushi")])
        with redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
            rows = bl.load_tests("French", "x", CEFR)
        self.assertEqual([r["expression"] for r in rows], ["chat"])


if __name__ == "__main__":
    unittest.main()
