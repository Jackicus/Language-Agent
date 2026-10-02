---
name: switch
description: Change the language being practised — keeps the previous language's evidence, then fetches and builds the new one. Triggered only when the learner types /switch.
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: true
---

# Switch Language

`/switch <language>` — e.g. `/switch french`, `/switch fr`. There is one active language
at a time; switching changes which one `/chat`, `/quiz` and `/sync` use.

## When to use

Only on an explicit `/switch`. Never auto-invoke — this changes the active language.

## 1. Which language

Map the argument to a code from `languages.json` (`ja zh ko fr de es it pt`; names or
codes, any case). No argument, or one that is not in the registry → one
`AskUserQuestion` (header `Language`): `Which language do you want to practise?` Pick
one, or choose Other and type German, Spanish, Italian or Portuguese. Options
`Japanese`, `Chinese`, `Korean`, `French`.

If it is already the active language (`python setup.py --check`, first line), say so and
stop.

## 2. Warn, then switch

Tell the learner, in two sentences, before running anything:

- Their {old language} words and everything they have shown they know stay in
  `Profile/<old code>/`, untouched; `/switch` back restores them exactly.
- The next sync downloads {new language}'s reference data, if any, and builds its word
  list from their sources — their Duolingo course in that language (it should be the
  *active* course in Duolingo for unit progress) and/or an Anki deck.

Then:

```bash
python setup.py --language <code> --check
```

This only writes the language and reports; no network.

## 3. Build it

- `NOT READY … run python setup.py --sync` — the new language has a source. Run
  `python setup.py --sync` now (10-minute timeout), show the `[n/N]` step headers, and
  report from `SUMMARY`: "{language_name}: {usable} words ready." Then `/chat`. If
  `usable` is 0 and the log says `skipped, your Duolingo account has no … course`, say
  that their Duolingo account does not study it yet: start the course in Duolingo and
  `/sync`, or `/connect anki <path>`.
- `NOT READY … python setup.py <your-duolingo-username>` or a `No source` message — there
  is nothing to build {new language} from yet. Say so and point at
  `/connect anki <path>` (or `/setup` for a Duolingo account). Stop.
- `READY` — they have practised it before; nothing to fetch. Report the usable count.

## Rules

- Only `/switch` triggers this skill.
- Never delete or move anything under `Profile/`; switching is just the `language` key.
