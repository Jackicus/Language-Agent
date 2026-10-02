# Anki

Reads your Anki cards into the word table for the active language, and records which
ones you have actually reviewed. A note with at least one reviewed card gets `seen=1`;
the lexicon build promotes those words from `unseen` to `exposed` and nothing more.

## Export from Anki

1. **File → Export…**
2. Export format: **Anki Deck Package (`*.apkg`)**, and pick the deck (or "All Decks").
3. Tick **Include scheduling information** — without it every card looks unreviewed and
   `seen` is all `0`.
4. On Anki 2.1.50 or newer, also tick **Support older Anki versions**. The newer format
   (`collection.anki21b`) is zstd-compressed and Python's standard library cannot read it;
   the script will tell you if you forgot.

Alternatively point it at the live `collection.anki2` in your Anki profile folder
(`~/.local/share/Anki2/<profile>/` on Linux, `%APPDATA%\Anki2\<profile>\` on Windows,
`~/Library/Application Support/Anki2/<profile>/` on macOS). Close Anki first.

## Run

```bash
python Connections/Anki/data/fetch/fetch-anki.py deck.apkg --list          # what decks are in it
python Connections/Anki/data/fetch/fetch-anki.py deck.apkg --deck "Japanese"
python Connections/Anki/data/fetch/fetch-anki.py deck.apkg --field-word 2 --field-gloss 3
```

Fields count from 1 in the order Anki's note editor shows them. The default guess is
field 1 = word, field 2 = English meaning; it prints the guess per note type and three
sample rows, so re-run with `--field-word` / `--field-gloss` (and optionally
`--field-reading`) if they look wrong. `[sound:…]`, HTML and Anki furigana
(`食[た]べる` → word `食べる`, reading `たべる`) are stripped.

The language is the active one in `Profile/profile.json`. Output:

```
data/languages/English/<language>.csv   the word table (no units; `seen` is 1/0)
profile.json                            file, deck, note and seen counts, timestamp
```

Then rebuild the lexicon: `python Profile/data/scripts/build_lexicon.py`.
