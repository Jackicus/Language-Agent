# Connections

A connection is one of **your** accounts or collections — something that knows what you
have studied. Each one reads its source and writes a word table; `build_lexicon.py` merges
every table for the active language into `Profile/<code>/lexicon.jsonl`, tagging each word
with the connection's folder name as its source. Nothing downstream knows where a word
came from.

| Connection | Reads | Gates words by |
|---|---|---|
| `Duolingo/` | duome.eu (course vocabulary + your unit progress) | `unit` ≤ your position |
| `Anki/` | an exported `.apkg` or `collection.anki2` | `seen` = a card was reviewed |

## The table contract

```
Connections/<Name>/profile.json                                   {"courses": {"<from>-<code>": {"active": bool, "through_unit": int|null, ...}}}
Connections/<Name>/data/languages/<FromLanguageName>/<languagename>.csv   e.g. English/french.csv

unit, unit_name, unit_topic, position, word, reading, gloss, script, repeat_units, audio, seen
```

`unit` is empty for connections without units; `seen` is empty for unit-gated ones and
`1`/`0` otherwise. `gloss` is pipe-separated. `script` comes from the language plugin
(`Profile/data/scripts/languages/`) or falls back to `latin`/`mixed`. Language names come
from `languages.json`. The full contract is CONTRACTS.md §5.

## Adding one

- Make `Connections/<Name>/` with code under `data/fetch/` (stdlib only) and a short
  `README.md`; everything else at the root is generated and git-ignored.
- Have the fetcher write the CSV above for the language in `Profile/profile.json`, plus a
  `profile.json` with a `courses` entry marked `active`.
- Never write learner evidence (`confidence`, `seen_count`, `srs`) — only
  `build_lexicon.py` touches the lexicon.
