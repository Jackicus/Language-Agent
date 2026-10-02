"""Korean: hangul, occasionally hanja.

Hangul syllables are phonetic, so -- like kana -- they segment into nonsense: a
single-word entry is never split into syllables for a composite (tokens() is [] unless
the entry has several words or is all hanja). Contains still runs over syllables,
guarded by weight and cover like everywhere else.

Particles attach directly to nouns (사과는, 학교에서), so lemmas() strips one -- the only
plugin that strips anything -- under the same guard Japanese earned the hard way: the
remainder must be at least two syllables and a content word, so a particle alone is never
the match (Japanese さんは -> さん hit 三, "three"). Polite verb endings reduce to the
dictionary 다 form by a short table.
"""

from __future__ import annotations

import unicodedata

# Longest first so 에서 is tried before 서-less 에.
PARTICLES = ("에서는", "에게서", "한테서", "으로는", "에서", "에게", "한테", "께서", "으로", "부터", "까지",
             "처럼", "보다", "하고", "이랑", "은", "는", "이", "가", "을", "를", "에", "의", "도",
             "와", "과", "로", "만", "랑")
STRUCTURAL = frozenset(PARTICLES) | {"이다", "입니다", "이에요", "예요"}

# Polite endings -> stem + 다. Irregulars first; each yields a dictionary form.
IRREGULAR = {"해요": "하다", "합니다": "하다", "했어요": "하다", "했습니다": "하다",
             "이에요": "이다", "예요": "이다", "입니다": "이다", "있어요": "있다", "없어요": "없다",
             "가요": "가다", "와요": "오다", "봐요": "보다", "줘요": "주다", "마셔요": "마시다"}
ENDINGS = ("었어요", "았어요", "습니다", "어요", "아요", "세요", "해요")

HANGUL_BASE, JONG_COUNT = 0xAC00, 28
RIEUL_B = 17  # ㅂ as a final consonant


def is_hangul(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3


def is_hanja(ch: str) -> bool:
    return "CJK UNIFIED" in unicodedata.name(ch, "")


def _syllables(text: str) -> int:
    return sum(1 for ch in text if is_hangul(ch) or is_hanja(ch))


def _drop_final(ch: str, final: int) -> str | None:
    """가 from 갑 (final ㅂ), or None when the syllable does not end in that consonant."""
    if not is_hangul(ch):
        return None
    offset = ord(ch) - HANGUL_BASE
    if offset % JONG_COUNT != final:
        return None
    return chr(ord(ch) - final)


class Korean:
    code = "ko"

    @staticmethod
    def script_of(word: str) -> str:
        kinds = set()
        for ch in word:
            if ch.isspace() or not ch.isalpha():
                continue
            kinds.add("hangul" if is_hangul(ch) else "hanja" if is_hanja(ch) else "other")
        return kinds.pop() if len(kinds) == 1 and "other" not in kinds else "mixed"

    @staticmethod
    def tokens(word: str) -> list[str]:
        parts = word.split()
        if len(parts) > 1:
            return parts
        if word and all(is_hanja(ch) for ch in word):
            return list(word)
        return []

    @staticmethod
    def is_content(word: str) -> bool:
        return word.strip() not in STRUCTURAL

    def lemmas(self, word: str) -> list[str]:
        """Guarded reductions. A particle on its own reduces to nothing; a stripped
        remainder must be >= 2 syllables and a content word."""
        w = word.strip()
        if not w or " " in w or not self.is_content(w):
            return []
        if w in IRREGULAR:
            return [IRREGULAR[w]]
        out: list[str] = []
        for ending in ENDINGS:
            if w.endswith(ending) and len(w) > len(ending):
                stem = w[: -len(ending)]
                out.append(stem + "다")
        if w.endswith("니다") and len(w) > 2:
            last = _drop_final(w[-3], RIEUL_B)  # 갑니다 -> 가 + 다
            if last:
                out.append(w[:-3] + last + "다")
        for particle in PARTICLES:
            if w.endswith(particle) and len(w) > len(particle):
                rest = w[: -len(particle)]
                if _syllables(rest) >= 2 and self.is_content(rest):
                    out.append(rest)
                break  # only the longest matching particle
        return [f for f in dict.fromkeys(out) if f != w and _syllables(f) >= 2]

    @staticmethod
    def weight(piece: str) -> int:
        return sum(2 if (is_hangul(ch) or is_hanja(ch)) else (0 if ch.isspace() else 1) for ch in piece)

    @staticmethod
    def reading_label(record: dict) -> str:
        reading = record.get("reading")
        return reading if reading and reading != record.get("word") else ""

    @staticmethod
    def name_rating(word: str, levels):
        """Hanja names take their hardest character's level; hangul names are easy if
        short."""
        order = levels.order
        if not order:
            return None
        hanja = [ch for ch in word if is_hanja(ch)]
        if hanja:
            known = [levels[ch] for ch in hanja if ch in levels]
            return (max(known, key=order.index) if len(known) == len(hanja) else order[-1]), "name-hanja"
        return (order[0] if _syllables(word) <= 3 else order[min(1, len(order) - 1)]), "name-hangul"

    @staticmethod
    def normalise(text: str) -> str:
        # NFC composes jamo into syllable blocks; Latin letters (rare) are casefolded.
        return unicodedata.normalize("NFC", text).strip().casefold()

    @staticmethod
    def fields(word: str, entry: dict | None) -> dict:
        entry = entry or {}
        return {"reading": entry.get("reading") or None, "headword": entry.get("headword") or None}


LANGUAGE = Korean()
