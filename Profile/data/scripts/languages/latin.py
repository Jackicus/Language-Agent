"""Latin-script languages: French, German, Spanish, Italian, Portuguese.

One module, five languages: `for_code(code)` returns the plugin for one of them, with
that language's function words, irregular verbs and suffix rules. `LANGUAGE` is the
language-neutral default (no lemmas, no function words) for callers that have no code;
build_lexicon and lexicon.py always go through languages.plugin(code), which prefers
the factory.

Matching keeps accents: normalise() is casefold + NFC, so café and cafe are different
keys and the a/à, ou/où, si/sí pairs stay apart. Accent-insensitive comparison happens
only in the build's inflection tier, and only as a tie-breaker (an accent-exact
candidate wins), because lemma rules cannot track accent shifts (achète -> acheter).

The lessons carried over from Japanese (CLAUDE.md, "Grading"):

  * every lemma rule has a guard: a minimum stem, irregulars hardcoded so they never
    fall through to the regular rule (est must not become "e" + "er"), and a function
    word is never produced or reduced
  * articles are never stripped: l'homme does not become homme, and a multi-word entry
    is graded by composite / contains, where a lone article never counts as a part
  * meaning overlap is the build's tie-breaker between candidates, never a gate
"""

from __future__ import annotations

import unicodedata

# Function words: articles, the commonest prepositions, conjunctions and pronoun clitics.
# is_content() is False for exactly these -- they are never quizzed, never a composite
# part, never a contains piece, never a lemma.
FUNCTION = {
    "fr": "le la les l' un une des du de d' à au aux et ou mais en y ne pas que qui se s' "
          "je j' tu il elle on nous vous ils elles me m' te t' ce c' qu' n'",
    "de": "der die das den dem des ein eine einen einem einer eines und oder aber zu im am "
          "an auf in mit von vom zum zur ich du er sie es wir ihr sich nicht",
    "es": "el la los las lo un una unos unas y o pero de del a al en que se me te le les "
          "nos os yo tú él ella no",
    "it": "il lo la i gli le l' un uno una un' e o ma di del della dei degli delle a al alla "
          "in nel nella che si mi ti ci vi io tu lui lei non",
    "pt": "o a os as um uma uns umas e ou mas de do da dos das em no na nos nas que se me "
          "te eu tu ele ela não",
}

# Irregular forms -> lemma. A form listed here never reaches the suffix rules.
IRREGULAR = {
    "fr": {"suis": "être", "es": "être", "est": "être", "sommes": "être", "êtes": "être",
           "sont": "être", "été": "être", "ai": "avoir", "as": "avoir", "a": "avoir",
           "avons": "avoir", "avez": "avoir", "ont": "avoir", "eu": "avoir",
           "vais": "aller", "vas": "aller", "va": "aller", "allons": "aller", "allez": "aller",
           "vont": "aller", "fais": "faire", "fait": "faire", "faisons": "faire",
           "faites": "faire", "font": "faire", "peux": "pouvoir", "peut": "pouvoir",
           "peuvent": "pouvoir", "veux": "vouloir", "veut": "vouloir", "veulent": "vouloir",
           "dois": "devoir", "doit": "devoir", "sais": "savoir", "sait": "savoir",
           "prends": "prendre", "prend": "prendre", "prennent": "prendre",
           "viens": "venir", "vient": "venir", "viennent": "venir", "yeux": "œil"},
    "de": {"bin": "sein", "bist": "sein", "ist": "sein", "sind": "sein", "seid": "sein",
           "war": "sein", "waren": "sein", "habe": "haben", "hast": "haben", "hat": "haben",
           "hatte": "haben", "wird": "werden", "wirst": "werden", "kann": "können",
           "kannst": "können", "will": "wollen", "willst": "wollen", "muss": "müssen",
           "musst": "müssen", "mag": "mögen", "magst": "mögen", "weiß": "wissen",
           "weißt": "wissen", "isst": "essen", "liest": "lesen", "sieht": "sehen",
           "siehst": "sehen", "gibt": "geben", "gibst": "geben", "nimmt": "nehmen",
           "nimmst": "nehmen", "spricht": "sprechen", "sprichst": "sprechen",
           "fährt": "fahren", "fährst": "fahren", "schläft": "schlafen", "läuft": "laufen"},
    "es": {"soy": "ser", "eres": "ser", "es": "ser", "somos": "ser", "sois": "ser", "son": "ser",
           "era": "ser", "fue": "ser", "estoy": "estar", "estás": "estar", "está": "estar",
           "estamos": "estar", "están": "estar", "tengo": "tener", "tienes": "tener",
           "tiene": "tener", "tienen": "tener", "voy": "ir", "vas": "ir", "va": "ir",
           "vamos": "ir", "van": "ir", "hago": "hacer", "haces": "hacer", "hace": "hacer",
           "he": "haber", "has": "haber", "ha": "haber", "han": "haber", "hay": "haber",
           "puedo": "poder", "puede": "poder", "quiero": "querer", "quiere": "querer",
           "digo": "decir", "dice": "decir", "sé": "saber", "sabe": "saber"},
    "it": {"sono": "essere", "sei": "essere", "è": "essere", "siamo": "essere",
           "siete": "essere", "era": "essere", "ho": "avere", "hai": "avere", "ha": "avere",
           "abbiamo": "avere", "avete": "avere", "hanno": "avere", "vado": "andare",
           "vai": "andare", "va": "andare", "vanno": "andare", "faccio": "fare", "fai": "fare",
           "fa": "fare", "fanno": "fare", "posso": "potere", "può": "potere",
           "voglio": "volere", "vuole": "volere", "devo": "dovere", "deve": "dovere",
           "so": "sapere", "sa": "sapere", "dico": "dire", "dice": "dire"},
    "pt": {"sou": "ser", "és": "ser", "é": "ser", "somos": "ser", "são": "ser", "era": "ser",
           "foi": "ser", "estou": "estar", "estás": "estar", "está": "estar",
           "estamos": "estar", "estão": "estar", "tenho": "ter", "tens": "ter", "tem": "ter",
           "temos": "ter", "têm": "ter", "vou": "ir", "vais": "ir", "vai": "ir", "vamos": "ir",
           "vão": "ir", "faço": "fazer", "faz": "fazer", "fazem": "fazer", "posso": "poder",
           "pode": "poder", "quero": "querer", "quer": "querer", "sei": "saber",
           "sabe": "saber", "digo": "dizer", "diz": "dizer"},
}

# (ending, replacements) -- longest endings first. A candidate is generated for each
# replacement; the build keeps whichever is actually listed. Plurals and the regular
# present / participle endings only: enough to reach a dictionary form, short enough to
# reason about.
SUFFIXES = {
    "fr": [("issons", ["ir"]), ("issez", ["ir"]), ("issent", ["ir"]), ("aient", ["er"]),
           ("geons", ["ger"]), ("çons", ["cer"]),          # mangeons, commençons
           ("ons", ["er", "re", "ir"]), ("ez", ["er", "re", "ir"]), ("ent", ["er", "re", "ir"]),
           ("ées", ["er"]), ("és", ["er"]), ("ée", ["er"]), ("é", ["er"]),
           ("ais", ["er"]), ("ait", ["er"]), ("aux", ["al"]), ("es", ["er", ""]),
           ("is", ["ir"]), ("it", ["ir"]), ("e", ["er"]), ("s", [""]), ("x", [""])],
    "de": [("est", ["en"]), ("st", ["en"]), ("et", ["en"]), ("en", ["", "en"]),
           ("er", [""]), ("e", ["en", ""]), ("t", ["en"]), ("n", [""]), ("s", [""])],
    "es": [("amos", ["ar"]), ("emos", ["er"]), ("imos", ["ir"]), ("áis", ["ar"]),
           ("éis", ["er"]), ("ís", ["ir"]), ("ado", ["ar"]), ("ido", ["er", "ir"]),
           ("as", ["ar", "a"]), ("an", ["ar"]), ("es", ["er", "ir", ""]), ("en", ["er", "ir"]),
           ("o", ["ar", "er", "ir"]), ("a", ["ar"]), ("e", ["er", "ir"]), ("s", [""])],
    "it": [("iamo", ["are", "ere", "ire"]), ("ate", ["are"]), ("ete", ["ere"]), ("ite", ["ire"]),
           ("ano", ["are"]), ("ono", ["ere", "ire"]), ("ato", ["are"]), ("uto", ["ere"]),
           ("ito", ["ire"]), ("o", ["are", "ere", "ire"]), ("i", ["o", "e", "are", "ere", "ire"]),
           ("a", ["are"]), ("e", ["a", "ere", "ire"])],
    "pt": [("amos", ["ar"]), ("emos", ["er"]), ("imos", ["ir"]), ("ões", ["ão"]),
           ("ado", ["ar"]), ("ido", ["er", "ir"]), ("as", ["ar", "a"]), ("am", ["ar"]),
           ("es", ["er", "ir", ""]), ("em", ["er", "ir"]), ("o", ["ar", "er", "ir"]),
           ("a", ["ar"]), ("e", ["er", "ir"]), ("s", [""])],
}

MIN_STEM = 3  # letters left after the ending comes off: "les" must not become "le" + ...


def _letters(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


class Latin:
    def __init__(self, code: str | None):
        self.code = code
        self.function = frozenset(FUNCTION.get(code, "").split())
        self.irregular = IRREGULAR.get(code, {})
        self.suffixes = SUFFIXES.get(code, [])

    def __repr__(self) -> str:
        return f"<latin plugin {self.code or 'generic'}>"

    @staticmethod
    def normalise(text: str) -> str:
        """casefold + NFC, accents kept; curly apostrophes unified."""
        text = unicodedata.normalize("NFC", text).replace("’", "'").replace("ʼ", "'")
        return " ".join(text.casefold().split())

    @staticmethod
    def script_of(word: str) -> str:
        """latin when every letter is a Latin letter (digits, spaces, punctuation are
        neutral), else mixed."""
        letters = [ch for ch in word if ch.isalpha()]
        if letters and all(unicodedata.name(ch, "").startswith("LATIN") for ch in letters):
            return "latin"
        return "mixed"

    def tokens(self, word: str) -> list[str]:
        """Words, split on spaces. A single word is one token, so it never splits and is
        never searched for substrings (carte must not contain car)."""
        return self.normalise(word).split() if word.strip() else []

    def is_content(self, word: str) -> bool:
        return self.normalise(word) not in self.function

    def lemmas(self, word: str) -> list[str]:
        """Dictionary-form candidates for one inflected word. Guards:

          multi-word entries   never reduced -- graded as composites instead
          function words       never reduced, never produced (les -/-> le)
          irregulars           hardcoded and final: est -> être, never est -> "e"+"er"
          minimum stem         MIN_STEM letters must remain after the ending
        """
        w = self.normalise(word)
        if not w or " " in w or not self.is_content(w):
            return []
        if w in self.irregular:
            return [self.irregular[w]]
        out: list[str] = []
        for ending, replacements in self.suffixes:
            if not w.endswith(ending):
                continue
            stem = w[: -len(ending)]
            if _letters(stem) < MIN_STEM:
                continue
            for rep in replacements:
                form = stem + rep
                if form != w and self.is_content(form) and form not in out:
                    out.append(form)
        return out

    @staticmethod
    def weight(piece: str) -> int:
        """Letters: every letter carries about as much as any other."""
        return _letters(piece)

    @staticmethod
    def reading_label(record: dict) -> str:
        reading = record.get("reading")
        return reading if reading and reading != record.get("word") else ""

    @staticmethod
    def name_rating(word: str, levels):
        """No script signal for Latin names: a short name is easy, a long one one level
        harder. Never the hardest -- a name is not exam vocabulary."""
        order = levels.order
        if not order:
            return None
        return (order[0] if _letters(word) <= 8 else order[min(1, len(order) - 1)]), "name-length"

    @staticmethod
    def fields(word: str, entry: dict | None) -> dict:
        entry = entry or {}
        return {"reading": entry.get("reading") or None, "headword": entry.get("headword") or None}


def for_code(code: str | None) -> Latin:
    return Latin(code)


LANGUAGE = Latin(None)
