"""lexicon.py: the read side /chat and /quiz rely on.

Pure helpers are called directly. Commands that touch files run through main() with
every Path global of the module remapped into a temp directory, so the real
Profile/lexicon.jsonl is never read or written.
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

import lexicon as lx


def rec(word, confidence, unit=None, gloss=("x",), **extra):
    return {"word": word, "confidence": confidence, "unit": unit, "gloss": list(gloss), **extra}


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        stack = _support.sandbox(lx, self.root)
        self.addCleanup(stack.close)
        _support.assert_sandboxed(self, lx, self.root)
        lx.PROFILE.parent.mkdir(parents=True, exist_ok=True)

    def write_profile(self, data):
        lx.PROFILE.write_text(json.dumps(data), encoding="utf-8")

    def write_lexicon(self, records):
        lx.lexicon_path().parent.mkdir(parents=True, exist_ok=True)
        lx.lexicon_path().write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")

    def read_lexicon(self):
        return {r["word"]: r for r in (json.loads(l) for l in lx.lexicon_path().read_text(encoding="utf-8").splitlines() if l.strip())}

    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["lexicon.py", *argv]), redirect_stdout(out):
            lx.main()
        return out.getvalue()


class TestUsable(unittest.TestCase):
    RECORDS = [
        rec("unseen-early", "unseen", unit=1),
        rec("exposed-early", "exposed", unit=1),
        rec("exposed-at", "exposed", unit=5),
        rec("exposed-late", "exposed", unit=9),
        rec("shaky-early", "shaky", unit=2),
        rec("known-early", "known", unit=3),
        rec("exposed-no-unit", "exposed", unit=None),
        rec("no-confidence", None, unit=1),
    ]

    def words(self, through):
        return {r["word"] for r in lx.usable(self.RECORDS, through)}

    def test_unseen_never_usable(self):
        for through in (None, 0, 5, 100):
            self.assertNotIn("unseen-early", self.words(through))
            self.assertNotIn("no-confidence", self.words(through))

    def test_no_position_means_confidence_only(self):
        self.assertEqual(self.words(None), {"exposed-early", "exposed-at", "exposed-late",
                                            "shaky-early", "known-early", "exposed-no-unit"})

    def test_position_gates_exposed(self):
        words = self.words(5)
        self.assertIn("exposed-early", words)
        self.assertIn("exposed-at", words)          # inclusive
        self.assertNotIn("exposed-late", words)

    def test_unitless_words_pass_the_gate(self):
        """Test-only words have no unit and count as unit 0."""
        self.assertIn("exposed-no-unit", self.words(0))

    def test_learner_evidence_within_position(self):
        words = self.words(5)
        self.assertIn("shaky-early", words)
        self.assertIn("known-early", words)


class TestGlossLabel(unittest.TestCase):
    def test_first_two(self):
        self.assertEqual(lx.gloss_label(rec("食べる", "known", gloss=["eat", "eats", "eating"])), "eat/eats")

    def test_truncated_to_60(self):
        label = lx.gloss_label(rec("w", "known", gloss=["a" * 50, "b" * 50]))
        self.assertEqual(len(label), 60)
        self.assertEqual(label, "a" * 50 + "/" + "b" * 9)

    def test_empty_falls_back_to_word(self):
        self.assertEqual(lx.gloss_label(rec("ね", "known", gloss=[])), "ね")
        self.assertEqual(lx.gloss_label(rec("ね", "known", gloss=["", ""])), "ね")

    def test_blank_entries_skipped(self):
        self.assertEqual(lx.gloss_label(rec("w", "known", gloss=["", "tea", "", "green tea"])), "tea/green tea")


class TestCurrentUnit(SandboxCase):
    def test_explicit_wins(self):
        self.write_profile({"connections": {"Duolingo": {"through_unit": 20}}})
        self.assertEqual(lx.current_unit(7), 7)
        self.assertEqual(lx.current_unit(0), 0)    # 0 is a value, not "unset"

    def test_max_over_connections(self):
        self.write_profile({"connections": {"Duolingo": {"through_unit": 20},
                                            "Anime": {"through_unit": 35},
                                            "Music": {"through_unit": None},
                                            "Other": {}}})
        self.assertEqual(lx.current_unit(None), 35)

    def test_nothing_recorded(self):
        self.assertIsNone(lx.current_unit(None))           # no profile.json at all
        self.write_profile({"connections": {"Duolingo": {"through_unit": None}}})
        self.assertIsNone(lx.current_unit(None))


class TestSetUnit(SandboxCase):
    def setUp(self):
        super().setUp()
        self.write_lexicon([
            rec("a", "unseen", unit=1),
            rec("b", "exposed", unit=8),
            rec("c", "shaky", unit=8),
            rec("d", "known", unit=8, seen_count=4),
            rec("e", "unseen", unit=None),
        ])

    def test_advance_promotes_unseen_only(self):
        self.run_cli("set-unit", "10")
        lex = self.read_lexicon()
        self.assertEqual(lex["a"]["confidence"], "exposed")
        self.assertEqual(lex["c"]["confidence"], "shaky")
        self.assertEqual(lex["d"]["confidence"], "known")
        self.assertEqual(lex["e"]["confidence"], "unseen")   # no unit, nothing to compare

    def test_retreat_never_touches_evidence(self):
        self.run_cli("set-unit", "2")
        lex = self.read_lexicon()
        self.assertEqual(lex["b"]["confidence"], "unseen")    # exposed is the marker's own
        self.assertEqual(lex["c"]["confidence"], "shaky")
        self.assertEqual((lex["d"]["confidence"], lex["d"]["seen_count"]), ("known", 4))

    def test_recorded_against_connection(self):
        self.run_cli("set-unit", "10")
        self.assertEqual(lx.current_unit(None), 10)
        self.assertEqual(json.loads(lx.PROFILE.read_text())["connections"]["Duolingo"]["through_unit"], 10)


class TestMark(SandboxCase):
    def setUp(self):
        super().setUp()
        self.write_lexicon([rec("食べる", "exposed", unit=1, seen_count=2), rec("飲む", "exposed", unit=1)])

    def test_mark_records_evidence(self):
        self.run_cli("mark", "食べる", "known", "飲む", "shaky")
        lex = self.read_lexicon()
        self.assertEqual((lex["食べる"]["confidence"], lex["食べる"]["seen_count"]), ("known", 3))
        self.assertEqual((lex["飲む"]["confidence"], lex["飲む"]["seen_count"]), ("shaky", 1))
        self.assertTrue(lex["食べる"].get("last_seen"))

    def test_unknown_level_rejected_without_writing(self):
        before = lx.lexicon_path().read_bytes()
        with self.assertRaises(SystemExit):
            self.run_cli("mark", "食べる", "mastered")
        self.assertEqual(lx.lexicon_path().read_bytes(), before)

    def test_missing_word_reported(self):
        out = json.loads(self.run_cli("mark", "存在しない", "known"))
        self.assertIn("存在しない", out["not_in_lexicon"])


class TestImportIsSideEffectFree(unittest.TestCase):
    def test_sandbox_redirects_every_path(self):
        """Every Path global, including any LEXICON_DIR override, lands in the temp dir."""
        with tempfile.TemporaryDirectory() as tmp:
            with _support.sandbox(lx, Path(tmp)):
                _support.assert_sandboxed(self, lx, Path(tmp))


if __name__ == "__main__":
    unittest.main()
