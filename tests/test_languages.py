"""The registry and the plugin interface (CONTRACTS.md sections 2 and 6).

Every plugin is exercised through languages.plugin(code), the one interface the build
and lexicon.py use, with hand-built inputs only.
"""

from __future__ import annotations

import unittest

import _support  # noqa: F401  (path shim)
from _support import CEFR, JA_LEVELS

import languages

CALLABLES = ("script_of", "tokens", "is_content", "lemmas", "weight", "reading_label",
             "name_rating", "normalise", "fields")
LATIN = ("fr", "de", "es", "it", "pt")


class TestRegistry(unittest.TestCase):
    def test_codes_and_doc_key(self):
        reg = languages.registry()
        self.assertNotIn("_doc", reg)
        for code in ("ja", "zh", "ko", *LATIN):
            self.assertIn(code, reg)
            self.assertTrue(reg[code]["name"])

    def test_levels_easiest_first(self):
        self.assertEqual(languages.levels("ja"), JA_LEVELS)
        self.assertEqual(languages.levels("fr"), CEFR)

    def test_rating_is_len_minus_index(self):
        self.assertEqual(languages.rating_of("N5", JA_LEVELS), 5)
        self.assertEqual(languages.rating_of("N1", JA_LEVELS), 1)
        self.assertEqual(languages.rating_of("A1", CEFR), 6)
        self.assertEqual(languages.rating_of("C2", CEFR), 1)
        self.assertIsNone(languages.rating_of("N9", JA_LEVELS))

    def test_label_inverts_rating(self):
        for order in (JA_LEVELS, CEFR):
            for label in order:
                self.assertEqual(languages.label_of(languages.rating_of(label, order), order), label)
        self.assertIsNone(languages.label_of(None, CEFR))
        self.assertIsNone(languages.label_of(7, CEFR))

    def test_unknown_code_is_an_error(self):
        with self.assertRaises(SystemExit):
            languages.spec("xx")


class TestEveryPluginHasTheInterface(unittest.TestCase):
    def test_callables(self):
        for code in languages.registry():
            plugin = languages.plugin(code)
            for name in CALLABLES:
                self.assertTrue(callable(getattr(plugin, name, None)), f"{code}.{name}")

    def test_basic_contract(self):
        levels = languages.Levels(CEFR)
        for code in languages.registry():
            L = languages.plugin(code)
            scripts = set(languages.spec(code)["scripts"]) | {"mixed"}
            for word in ("x", "コーヒー", "café", "咖啡", "사과", "OK"):
                self.assertIn(L.script_of(word), scripts, f"{code} {word}")
                self.assertIsInstance(L.tokens(word), list)
                self.assertIsInstance(L.lemmas(word), list)
                self.assertIsInstance(L.weight(word), int)
                self.assertIsInstance(L.normalise(word), str)
            self.assertEqual(L.reading_label({"word": "w"}), "")
            result = L.name_rating("Name", levels)
            self.assertTrue(result is None or isinstance(result, (str, tuple)))
            self.assertIsInstance(L.fields("w", None), dict)

    def test_latin_factory_per_code(self):
        plugins = {code: languages.plugin(code) for code in LATIN}
        self.assertEqual(len({id(p) for p in plugins.values()}), len(LATIN))
        self.assertEqual(plugins["de"].lemmas("ist"), ["sein"])
        self.assertEqual(plugins["fr"].lemmas("est"), ["être"])


class TestJapanese(unittest.TestCase):
    L = languages.plugin("ja")

    def test_script(self):
        self.assertEqual(self.L.script_of("コーヒー"), "katakana")   # ー takes its neighbours' script
        self.assertEqual(self.L.script_of("たべます"), "hiragana")
        self.assertEqual(self.L.script_of("人々"), "kanji")
        self.assertEqual(self.L.script_of("お茶"), "mixed")
        self.assertEqual(self.L.script_of("Tシャツ"), "mixed")      # never "other"
        self.assertEqual(self.L.script_of("WiFi"), "mixed")

    def test_tokens_kanji_only(self):
        self.assertEqual(self.L.tokens("何月"), ["何", "月"])
        self.assertEqual(self.L.tokens("すし"), [])

    def test_particles_not_content(self):
        for w in ("は", "を", "です", "さん"):
            self.assertFalse(self.L.is_content(w), w)
        self.assertTrue(self.L.is_content("日本"))

    def test_lemmas_guarded(self):
        self.assertEqual(self.L.lemmas("たべます"), ["たべる"])
        self.assertEqual(self.L.lemmas("します"), ["する"])
        self.assertEqual(self.L.lemmas("しましょう"), ["する"])
        self.assertEqual(self.L.lemmas("さんは"), [])               # particles never stripped

    def test_weight_and_reading(self):
        self.assertEqual(self.L.weight("日本"), 4)
        self.assertEqual(self.L.weight("にほん"), 3)
        self.assertEqual(self.L.reading_label({"word": "食べる", "kana": "たべる"}), "たべる")
        self.assertEqual(self.L.reading_label({"word": "たべる", "kana": "たべる"}), "")

    def test_name_rating_uses_order(self):
        levels = languages.Levels(JA_LEVELS, {"田": "N5", "鈴": "N2"})
        self.assertEqual(self.L.name_rating("鈴田", levels), ("N2", "name-kanji"))
        self.assertEqual(self.L.name_rating("鷹", levels), ("N1", "name-kanji"))
        self.assertEqual(self.L.name_rating("たなか", levels), ("N5", "name-kana"))

    def test_fields(self):
        entry = _support.jmdict("お茶", "おちゃ")
        self.assertEqual(self.L.fields("おちゃ", entry), {"kana": "おちゃ", "kanji": "お茶"})
        self.assertEqual(self.L.fields("ピザ", None), {"kana": "ピザ", "kanji": None})


class TestLatin(unittest.TestCase):
    fr, de, es, it, pt = (languages.plugin(c) for c in LATIN)

    def test_normalise_keeps_accents(self):
        self.assertEqual(self.fr.normalise("Café"), "café")
        self.assertNotEqual(self.fr.normalise("café"), self.fr.normalise("cafe"))
        self.assertEqual(self.fr.normalise("l’homme"), "l'homme")

    def test_script(self):
        self.assertEqual(self.fr.script_of("garçon"), "latin")
        self.assertEqual(self.fr.script_of("pomme de terre"), "latin")
        self.assertEqual(self.fr.script_of("café 咖啡"), "mixed")

    def test_tokens_split_words_only(self):
        self.assertEqual(self.fr.tokens("pomme de terre"), ["pomme", "de", "terre"])
        self.assertEqual(self.fr.tokens("carte"), ["carte"])     # one token: never split

    def test_articles_not_content(self):
        for L, w in ((self.fr, "les"), (self.de, "der"), (self.es, "el"), (self.it, "gli"), (self.pt, "os")):
            self.assertFalse(L.is_content(w), w)
            self.assertEqual(L.lemmas(w), [], w)               # never reduced

    def test_plural_and_verb_lemmas(self):
        self.assertIn("chat", self.fr.lemmas("chats"))
        self.assertIn("parler", self.fr.lemmas("parlons"))
        self.assertIn("gehen", self.de.lemmas("gehst"))
        self.assertIn("hablar", self.es.lemmas("hablamos"))
        self.assertIn("parlare", self.it.lemmas("parliamo"))
        self.assertIn("falar", self.pt.lemmas("falamos"))

    def test_irregulars_final(self):
        self.assertEqual(self.fr.lemmas("est"), ["être"])
        self.assertEqual(self.es.lemmas("soy"), ["ser"])
        self.assertEqual(self.it.lemmas("è"), ["essere"])

    def test_min_stem_guard(self):
        """les -> le would be an article; bus -> bu is a fragment."""
        self.assertEqual(self.fr.lemmas("bus"), [])
        self.assertNotIn("le", self.fr.lemmas("les"))

    def test_never_produces_function_word(self):
        for L in (self.fr, self.de, self.es, self.it, self.pt):
            for w in ("dess", "unos", "dels", "dass", "ones"):
                for lemma in L.lemmas(w):
                    self.assertTrue(L.is_content(lemma), (L, w, lemma))

    def test_multiword_never_reduced(self):
        self.assertEqual(self.fr.lemmas("les chats"), [])

    def test_weight_counts_letters(self):
        self.assertEqual(self.fr.weight("le chat"), 6)


class TestChinese(unittest.TestCase):
    L = languages.plugin("zh")

    def test_characters(self):
        self.assertEqual(self.L.tokens("咖啡"), ["咖", "啡"])
        self.assertEqual(self.L.tokens("kafei"), [])
        self.assertEqual(self.L.weight("冰咖啡"), 6)
        self.assertEqual(self.L.script_of("咖啡"), "hanzi")

    def test_no_inflection(self):
        self.assertEqual(self.L.lemmas("吃了"), [])

    def test_particles(self):
        self.assertFalse(self.L.is_content("的"))
        self.assertTrue(self.L.is_content("咖啡"))

    def test_name_rating(self):
        levels = languages.Levels(["HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"], {"王": "HSK3", "小": "HSK1"})
        self.assertEqual(self.L.name_rating("小王", levels), ("HSK3", "name-hanzi"))
        self.assertEqual(self.L.name_rating("鑫", levels), ("HSK6", "name-hanzi"))
        self.assertIsNone(self.L.name_rating("Li", levels))


class TestKorean(unittest.TestCase):
    L = languages.plugin("ko")

    def test_particle_stripped_only_with_two_syllables_left(self):
        self.assertEqual(self.L.lemmas("사과는"), ["사과"])
        self.assertEqual(self.L.lemmas("학교에서"), ["학교"])
        self.assertEqual(self.L.lemmas("책은"), [])    # 책 alone is one syllable: homophone magnet

    def test_particle_alone_never_matches(self):
        for p in ("는", "에서", "을", "이"):
            self.assertFalse(self.L.is_content(p))
            self.assertEqual(self.L.lemmas(p), [])

    def test_polite_endings(self):
        self.assertIn("먹다", self.L.lemmas("먹어요"))
        self.assertIn("가다", self.L.lemmas("갑니다"))
        self.assertEqual(self.L.lemmas("해요"), ["하다"])

    def test_syllables_never_split(self):
        self.assertEqual(self.L.tokens("사과"), [])
        self.assertEqual(self.L.tokens("사과 주스"), ["사과", "주스"])
        self.assertEqual(self.L.script_of("사과"), "hangul")


if __name__ == "__main__":
    unittest.main()
