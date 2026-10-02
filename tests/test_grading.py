"""The grading tiers of build_lexicon.Grader, each pinned to the false positive that earned it.

See CLAUDE.md, "Grading: jlpt and rating are separate". Every fixture here is a hand-built
miniature of the real JLPT list / JMdict, so a failure points at a rule, not at data drift.
Some levels are deliberately contrived (月 at N3) so that "hardest part wins" is observable.
"""

from __future__ import annotations

import unittest

import _support  # noqa: F401  (path shim)
from _support import jlpt, jmdict

import build_lexicon as bl

LISTED_TIERS = {"expression", "reading", "inflection", "variant"}

TESTS = [
    # inflection
    jlpt("N5", "食べる", "たべる", "to eat"),
    jlpt("N5", "する", "する", "to do, to make"),
    jlpt("N5", "知る", "しる", "to know, to understand"),
    jlpt("N5", "来る", "くる", "to come"),
    jlpt("N5", "着る", "きる", "to wear"),
    jlpt("N3", "酢", "す", "vinegar"),
    jlpt("N5", "三", "さん", "three"),
    jlpt("N5", "日本", "にほん", "Japan"),
    jlpt("N5", "の", "の", "possessive particle"),
    jlpt("N4", "学ぶ", "まなぶ", "to learn; to study"),
    jlpt("N5", "帰る", "かえる", "to go home, to return"),
    jlpt("N4", "変える", "かえる", "to change, to alter"),
    jlpt("N5", "言う", "いう", "to say"),
    jlpt("N5", "ます", "ます", "polite verb ending"),
    # contains
    jlpt("N4", "カー", "カー", "car"),
    jlpt("N3", "パス", "パス", "pass"),
    jlpt("N3", "ファン", "ファン", "fan"),
    jlpt("N5", "コーヒー", "コーヒー", "coffee"),
    # composite
    jlpt("N5", "何", "なに", "what"),
    jlpt("N3", "月", "つき", "moon, month"),          # contrived: harder than 何
    jlpt("N5", "中", "なか", "inside, middle"),
    jlpt("N4", "国", "くに", "country"),
    jlpt("N3", "死", "し", "death"),
    jlpt("N3", "棚", "たな", "shelf"),
    jlpt("N1", "蚊", "か", "mosquito"),
    # variant / reading
    jlpt("N5", "友達", "ともだち", "friend"),
    jlpt("N5", "お茶", "おちゃ", "green tea"),
    jlpt("N2", "統計", "とうけい", "statistics"),
    jlpt("N4", "字", "じ", "character, letter"),
]


class GraderCase(unittest.TestCase):
    tests = TESTS

    @classmethod
    def setUpClass(cls):
        cls.grader = bl.Grader(cls.tests)

    def grade(self, word, gloss, entry=None):
        return self.grader.grade(word, gloss, entry)

    def assertNotListed(self, result, msg=None):
        jlpt_flag, _, how, _ = result
        self.assertFalse(jlpt_flag, msg)
        self.assertNotIn(how, LISTED_TIERS, msg)


# ------------------------------------------------------------------- listed tiers
class TestExpressionAndReading(GraderCase):
    def test_exact_expression(self):
        self.assertEqual(self.grade("コーヒー", ["coffee"]), (True, "N5", "expression", "コーヒー"))

    def test_kana_reading_of_kanji_entry(self):
        self.assertEqual(self.grade("おちゃ", ["green tea"]), (True, "N5", "reading", "お茶"))

    def test_pick_prefers_easiest_level(self):
        g = bl.Grader([jlpt("N2", "酢", "す", "vinegar"), jlpt("N3", "酢", "す", "vinegar")])
        self.assertEqual(g.grade("酢", ["vinegar"], None)[1], "N3")


class TestInflection(GraderCase):
    def test_tabemasu_reduces_to_taberu(self):
        self.assertEqual(self.grade("たべます", ["eat", "eats"]), (True, "N5", "inflection", "食べる"))

    def test_shimasu_is_suru_not_shiru(self):
        jlpt_flag, level, how, via = self.grade("します", ["do", "does"])
        self.assertEqual((how, via), ("inflection", "する"))
        self.assertNotEqual(via, "知る")

    def test_shimasu_never_hits_shiru_even_when_suru_unlisted(self):
        """The regular rule turns します into しる. With する absent the irregular table
        must still keep it off 知る rather than fall through to the regular rule."""
        g = bl.Grader([jlpt("N5", "知る", "しる", "to know")])
        self.assertNotEqual(g.grade("します", ["do"], None)[3], "知る")

    def test_kimasu_is_kuru(self):
        self.assertEqual(self.grade("きます", ["come"])[3], "来る")

    def test_one_char_dictionary_form_rejected(self):
        """し + ましょう reduces (godan) to す, which would hit 酢 "vinegar"."""
        g = bl.Grader([jlpt("N3", "酢", "す", "vinegar")])
        self.assertEqual(g.grade("しましょう", ["let's do"], None), (False, None, None, None))
        g = bl.Grader([jlpt("N3", "酢", "す", "vinegar")])
        self.assertNotEqual(g.grade("しませんでした", ["did not do"], None)[3], "酢")

    def test_bare_one_char_word_does_not_reduce(self):
        g = bl.Grader([jlpt("N3", "酢", "す", "vinegar")])
        self.assertNotEqual(g.grade("し", ["four"], None)[3], "酢")

    def test_shimashou_is_not_shiru(self):
        """BUG: IRREGULAR only covers します/しました/しません. しましょう and しませんでした
        fall through to the regular rule, become しる, and hit 知る ("to know") -- exactly
        the false positive the irregular table exists to stop. Same for きましょう -> 着る.
        Remove this decorator once IRREGULAR covers every POLITE_SUFFIX."""
        self.assertNotEqual(self.grade("しましょう", ["let's do"])[3], "知る")
        self.assertNotEqual(self.grade("しませんでした", ["did not do"])[3], "知る")
        self.assertNotEqual(self.grade("きましょう", ["let's come"])[3], "着る")

    def test_particle_ha_never_stripped(self):
        """さんは -> さん would hit 三 "three"."""
        result = self.grade("さんは", ["Mr.", "Ms."])
        self.assertNotListed(result)
        self.assertNotEqual(result[3], "三")

    def test_particle_no_never_stripped(self):
        """日本の may *contain* 日本, but it is not the listed word."""
        result = self.grade("日本の", ["Japanese"])
        self.assertNotListed(result)
        self.assertNotEqual(result[2], "inflection")

    def test_manabimasu_without_shared_sense(self):
        """"learns" and "to learn; to study" share no exact sense: overlap is a
        tie-breaker, not a gate."""
        self.assertEqual(self.grade("学びます", ["learns"]), (True, "N4", "inflection", "学ぶ"))

    def test_sense_overlap_breaks_ties_between_homophones(self):
        """かえります reduces to かえる = 帰る (N5) or 変える (N4). The gloss decides,
        even against the easier level."""
        self.assertEqual(self.grade("かえります", ["change"])[3], "変える")
        self.assertEqual(self.grade("かえります", ["go home"])[3], "帰る")


class TestVariant(GraderCase):
    def test_kanji_spelling_followed(self):
        entry = jmdict("友達", "ともだち", kanji_all="友達|友だち")
        self.assertEqual(self.grade("友だち", ["friend"], entry), (True, "N5", "variant", "友達"))

    def test_kana_reading_not_followed_toukei(self):
        """JMdict lists とうけい as a reading of 東京; following it lands on 統計."""
        entry = jmdict("東京", "とうきょう", kana_all="とうきょう|とうけい", senses="Tokyo")
        for word in ("東京", "とうきょう"):
            result = self.grade(word, ["Tokyo"], entry)
            self.assertNotEqual(result[3], "統計", word)
            self.assertFalse(result[0], word)

    def test_kana_reading_not_followed_ji(self):
        """時 reads じ in compounds; じ is also 字 "character"."""
        entry = jmdict("時", "とき", kana_all="とき|じ", senses="time|hour|o'clock")
        result = self.grade("時", ["time", "o'clock"], entry)
        self.assertNotEqual(result[3], "字")
        self.assertFalse(result[0])


# ----------------------------------------------------------------- inferred tiers
class TestComposite(GraderCase):
    def test_compound_scored_at_hardest_part(self):
        self.assertEqual(self.grade("何月", ["what month"]), (False, "N3", "composite", "何+月"))

    def test_kana_never_segmented_sushi(self):
        """す (vinegar) + し (death)."""
        result = self.grade("すし", ["sushi"])
        self.assertNotEqual(result[2], "composite")
        self.assertIsNone(result[1])

    def test_kana_never_segmented_tanaka(self):
        """たな (shelf) + か (mosquito)."""
        result = self.grade("たなか", ["Tanaka"])
        self.assertNotEqual(result[2], "composite")
        self.assertIsNone(result[1])

    def test_single_kana_piece_not_used_inside_kanji_word(self):
        """日本の must not split as 日本 + の even with の on the list."""
        self.assertNotEqual(self.grade("日本の", ["Japanese"])[2], "composite")

    def test_jmdict_kanji_form_tried(self):
        """ちゅうごく is unsplittable as kana but resolves to 中国 -> 中 + 国."""
        index = bl.index_dictionary([jmdict("中国", "ちゅうごく", senses="China")])
        entry = bl.best_entry("ちゅうごく", ["China"], index)
        self.assertEqual(self.grade("ちゅうごく", ["China"], entry), (False, "N4", "composite", "中+国"))


class TestContains(GraderCase):
    def test_soccer_not_from_car(self):
        self.assertNotEqual(self.grade("サッカー", ["soccer"])[3], "カー")

    def test_pasta_not_from_pass(self):
        self.assertNotEqual(self.grade("パスタ", ["pasta"])[3], "パス")

    def test_fantasy_not_from_fan(self):
        """ファン clears the weight guard (3) but covers only 50% of the word."""
        self.assertNotEqual(self.grade("ファンタジー", ["fantasy"])[3], "ファン")

    def test_to_iimasu_not_from_masu(self):
        self.assertNotEqual(self.grade("と言います", ["is called"])[3], "ます")

    def test_iced_coffee_inherits_from_coffee(self):
        self.assertEqual(self.grade("アイスコーヒー", ["iced coffee"]), (False, "N5", "contains", "コーヒー"))

    def test_kanji_piece_clears_weight_guard(self):
        """日本 is two characters but weighs 4: kanji count double."""
        self.assertEqual(self.grade("日本の", ["Japanese"]), (False, "N5", "contains", "日本"))


class TestStem(GraderCase):
    def test_shared_sense_without_shared_stem_rejected(self):
        """Meaning alone pairs わたしの "mine" with 鉱山 "a mine"."""
        g = bl.Grader([jlpt("N1", "鉱山", "こうざん", "mine")])
        self.assertEqual(g.grade("わたしの", ["my", "mine"], None), (False, None, None, None))

    def test_shared_sense_and_stem_accepted(self):
        """つぎの -> 次 via the reading つぎ."""
        g = bl.Grader([jlpt("N5", "次", "つぎ", "next")])
        self.assertEqual(g.grade("つぎの", ["next"], None), (False, "N5", "stem", "次"))

    def test_ambiguous_levels_rejected(self):
        """Corroborated candidates at two different levels: no stem grade at all."""
        g = bl.Grader([jlpt("N5", "次", "つぎ", "next"), jlpt("N3", "継ぎ", "つぎ", "next")])
        self.assertIsNone(g.grade("つぎの", ["next"], None)[1])


# ------------------------------------------------------------- jlpt vs rating
class TestJlptRatingSeparation(GraderCase):
    def test_listed_word(self):
        jlpt_flag, level, _, _ = self.grade("コーヒー", ["coffee"])
        self.assertTrue(jlpt_flag)
        self.assertEqual(bl.level_num(level), 5)

    def test_unlisted_word_still_rated(self):
        jlpt_flag, level, _, _ = self.grade("アイスコーヒー", ["iced coffee"])
        self.assertFalse(jlpt_flag)
        self.assertEqual(bl.level_num(level), 5)


# ------------------------------------------------------------------ dictionary
class TestBestEntry(unittest.TestCase):
    def setUp(self):
        self.index = bl.index_dictionary([
            jmdict("元", "もと", kanji_all="元|本", senses="origin|source", common="1"),
            jmdict("本", "ほん", senses="book|volume", common="1"),
        ])

    def test_sense_picks_the_meaning_the_source_gave(self):
        self.assertEqual(bl.best_entry("本", ["book"], self.index)["kana"], "ほん")
        self.assertEqual(bl.best_entry("本", ["origin"], self.index)["kana"], "もと")

    def test_unknown_word(self):
        self.assertIsNone(bl.best_entry("無い", ["none"], self.index))

    def test_canonical_collapses_spellings(self):
        index = bl.index_dictionary([jmdict("お茶", "おちゃ", senses="green tea")])
        a = bl.canonical("おちゃ", bl.best_entry("おちゃ", ["tea"], index))
        b = bl.canonical("お茶", bl.best_entry("お茶", ["tea"], index))
        self.assertEqual(a, b)


# ----------------------------------------------------------------------- names
class TestLooksLikeName(unittest.TestCase):
    def test_names(self):
        # Not "J-pop": the docstring cites it, but "pop" is a lowercase token so the rule
        # (every token capitalised) rejects it. See the report.
        for gloss in (["Tanaka"], ["Toronto"], ["New York"], ["Naomi", "Naomi (name)"]):
            self.assertTrue(bl.looks_like_name(gloss), gloss)

    def test_demonym_is_vocabulary(self):
        for gloss in (["Japanese"], ["Japanese person"], ["Canadian"]):
            self.assertFalse(bl.looks_like_name(gloss), gloss)

    def test_empty(self):
        self.assertFalse(bl.looks_like_name([]))
        self.assertFalse(bl.looks_like_name(None))
        self.assertFalse(bl.looks_like_name([""]))

    def test_ordinary_words(self):
        self.assertFalse(bl.looks_like_name(["green tea"]))
        self.assertFalse(bl.looks_like_name(["Tanaka", "rice field"]))


class TestRateName(unittest.TestCase):
    def setUp(self):
        self.grader = bl.Grader([jlpt("N5", "田", "た", "rice field"), jlpt("N2", "鈴", "すず", "bell")])

    def test_hardest_kanji(self):
        self.assertEqual(self.grader.rate_name("鈴田"), ("N2", "name-kanji"))

    def test_unplaceable_kanji_is_n1(self):
        self.assertEqual(self.grader.rate_name("鷹"), ("N1", "name-kanji"))

    def test_kana_by_length(self):
        self.assertEqual(self.grader.rate_name("たなか"), ("N5", "name-kana"))
        self.assertEqual(self.grader.rate_name("トロントシティ"), ("N4", "name-kana"))


if __name__ == "__main__":
    unittest.main()
