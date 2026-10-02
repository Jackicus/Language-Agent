"""Chinese (Mandarin, simplified): hanzi, with pinyin as the reading.

The Japanese kanji ideas carry straight over: a compound is graded at its hardest
character (composite), a listed word inside a longer one lends it a level (contains),
and every character weighs 2. There is no inflection, so lemmas() is always empty.
"""

from __future__ import annotations

import unicodedata

# Structural particles and the commonest grammatical characters: never quizzed, never a
# composite part or contains piece on their own.
PARTICLES = frozenset("的 了 吗 呢 吧 啊 着 过 地 得 们 么 嘛 呀 哦".split())
NEUTRAL = frozenset(" 　，。！？、；：,.!?;:()（）·")


def is_hanzi(ch: str) -> bool:
    return "CJK UNIFIED" in unicodedata.name(ch, "") or ch in "〇々"


class Chinese:
    code = "zh"

    @staticmethod
    def script_of(word: str) -> str:
        chars = [ch for ch in word if ch not in NEUTRAL]
        return "hanzi" if chars and all(is_hanzi(ch) for ch in chars) else "mixed"

    @staticmethod
    def tokens(word: str) -> list[str]:
        """Characters, for all-hanzi words. Pinyin or Latin text is never split."""
        chars = [ch for ch in word if ch not in NEUTRAL]
        return list(word) if chars and all(is_hanzi(ch) or ch in NEUTRAL for ch in word) else []

    @staticmethod
    def is_content(word: str) -> bool:
        return word.strip() not in PARTICLES

    @staticmethod
    def lemmas(word: str) -> list[str]:
        return []  # Mandarin does not inflect

    @staticmethod
    def weight(piece: str) -> int:
        return sum(2 if is_hanzi(ch) else (0 if ch in NEUTRAL else 1) for ch in piece)

    @staticmethod
    def reading_label(record: dict) -> str:
        reading = record.get("reading")
        return reading if reading and reading != record.get("word") else ""

    @staticmethod
    def name_rating(word: str, levels):
        """As hard as the hardest listed character; a character no list has is the
        hardest level. None for a name with no hanzi at all."""
        order = levels.order
        hanzi = [ch for ch in word if is_hanzi(ch)]
        if not hanzi or not order:
            return None
        known = [levels[ch] for ch in hanzi if ch in levels]
        if len(known) < len(hanzi):
            return order[-1], "name-hanzi"
        return max(known, key=order.index), "name-hanzi"

    @staticmethod
    def normalise(text: str) -> str:
        return unicodedata.normalize("NFC", text).strip()

    @staticmethod
    def fields(word: str, entry: dict | None) -> dict:
        entry = entry or {}
        return {"reading": entry.get("reading") or None, "headword": entry.get("headword") or None}


LANGUAGE = Chinese()
