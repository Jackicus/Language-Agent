"""Japanese: hiragana, katakana, kanji. A straight port of the pre-registry rules.

Every guard here was earned by a real false positive on the course data -- see
CLAUDE.md, "Grading". Changing one changes the Japanese lexicon.
"""

from __future__ import annotations

import unicodedata

GODAN_STEM = {"い": "う", "き": "く", "ぎ": "ぐ", "し": "す", "ち": "つ",
              "に": "ぬ", "び": "ぶ", "み": "む", "り": "る"}
POLITE_SUFFIXES = ("ませんでした", "ましょう", "ません", "ました", "ます")
# Every polite ending the regular rule handles, for both irregulars -- a gap falls through
# to the regular rule, and しましょう becomes しる and hits 知る, きましょう hits 着る.
IRREGULAR = {stem + suffix: [plain] for stem, plain in (("し", "する"), ("き", "来る"))
             for suffix in POLITE_SUFFIXES}

# Grammar the course teaches structurally rather than as vocabulary: particles, copula,
# honorifics. は is listed by hand because JMdict resolves the bare kana to 歯 ("tooth").
PARTICLES = frozenset(
    "は が を に で と も の か へ や ね よ な から まで より ので のに けど だけ など "
    "です ます だ である さん ちゃん くん さま".split()
)


def is_kanji(ch: str) -> bool:
    return "CJK UNIFIED" in unicodedata.name(ch, "")


def has_kanji(text: str) -> bool:
    return any(is_kanji(ch) for ch in text)


def is_kana(text: str) -> bool:
    return bool(text) and all(
        "HIRAGANA" in unicodedata.name(ch, "") or "KATAKANA" in unicodedata.name(ch, "") or ch in "ー・っッ"
        for ch in text
    )


# Marks that carry no script of their own: they take the script of the word around them.
NEUTRAL = frozenset("ー〜～・ 　、。！？!?;；,，()（）/／")


def _char_script(ch: str) -> str | None:
    if ch in "々〇":
        return "kanji"
    name = unicodedata.name(ch, "")
    if "CJK UNIFIED" in name:
        return "kanji"
    if name.startswith("HIRAGANA"):
        return "hiragana"
    if name.startswith("KATAKANA"):
        return "katakana"
    return None


class Japanese:
    code = "ja"

    @staticmethod
    def script_of(word: str) -> str:
        """hiragana, katakana or kanji when the word is written in one of them alone,
        else "mixed" -- including anything with a character none of them covers.

        ー (KATAKANA-HIRAGANA PROLONGED SOUND MARK) belongs to neither script on its own
        and takes the script of its neighbours, so コーヒー is katakana; so do spaces and
        punctuation (いい; よい is hiragana). 々 and 〇 count as kanji.
        """
        kinds = set()
        for ch in word:
            if ch in NEUTRAL:
                continue
            kind = _char_script(ch)
            kinds.add(kind or "other")
        if len(kinds) == 1 and "other" not in kinds:
            return kinds.pop()
        return "mixed"

    @staticmethod
    def tokens(word: str) -> list[str]:
        """Characters -- but only for words with kanji. Kana strings segment into
        nonsense: すし becomes す (vinegar) + し (death), たなか becomes たな + か."""
        return list(word) if has_kanji(word) else []

    @staticmethod
    def is_content(word: str) -> bool:
        return word not in PARTICLES

    @staticmethod
    def lemmas(word: str) -> list[str]:
        """Polite ます-forms back to dictionary form. Three guards:

          irregulars hardcoded   します would become しる and hit 知る
          one-char results out   し + ましょう reduces to す and hits 酢
          particles never stripped  さんは -> さん hits 三; nothing here strips them
        """
        if word in IRREGULAR:
            return IRREGULAR[word]
        for suffix in POLITE_SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix):
                stem = word[: -len(suffix)]
                forms = [stem + "る"]
                if stem[-1] in GODAN_STEM:
                    forms.append(stem[:-1] + GODAN_STEM[stem[-1]])
                return [f for f in forms if len(f) >= 2]
        return []

    @staticmethod
    def weight(piece: str) -> int:
        """A kanji is worth two kana, since there are far more of them."""
        return sum(2 if is_kanji(ch) else 1 for ch in piece)

    @staticmethod
    def reading_label(record: dict) -> str:
        kana = record.get("kana")
        return kana if kana and kana != record.get("word") else ""

    @staticmethod
    def name_rating(word: str, levels):
        """Kanji names are as hard as their hardest character; short kana names are easy.

        `levels` maps listed forms to labels and carries `.order` (easiest first)."""
        order = levels.order
        kanji_levels = [levels[ch] for ch in word if is_kanji(ch) and ch in levels]
        if kanji_levels:
            return max(kanji_levels, key=order.index), "name-kanji"
        if has_kanji(word):
            # Kanji we cannot place at all is not beginner material.
            return order[-1], "name-kanji"
        return (order[0] if len(word) <= 4 else order[min(1, len(order) - 1)]), "name-kana"

    @staticmethod
    def normalise(text: str) -> str:
        # Exact: kana/kanji have no case, and NFKC would fold the full-width Ｔ in Ｔシャツ.
        return text

    @staticmethod
    def fields(word: str, entry: dict | None) -> dict:
        entry = entry or {}
        headword, reading = entry.get("headword") or "", entry.get("reading") or ""
        kanji = headword if headword and headword != reading else ""
        return {
            "kana": reading or (word if is_kana(word) else None),
            "kanji": kanji or (word if has_kanji(word) else None),
        }


LANGUAGE = Japanese()
