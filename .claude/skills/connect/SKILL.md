---
name: connect
description: Add or change a word source after setup — an Anki deck export or a Duolingo account — then rebuild. Triggered only when the learner types /connect.
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: true
---

# Connect a Source

`/connect anki <path> [deck name]` or `/connect duolingo <username>`. Each is one
`setup.py` run; this skill only builds the command and reports.

## When to use

Only on an explicit `/connect`. Never auto-invoke — this writes connection data and
rebuilds the lexicon.

## 1. Work out the command

- **`anki <path>`** — `python setup.py --anki "<path>"`, plus `--deck "<name>"` if they
  named a deck. Quote both. The deck is read into the language already being practised,
  and `/sync` re-reads it from then on.
- **`duolingo <username>`** — `python setup.py <username>` (strip a leading `@` or a
  pasted profile URL). A *different* account than the saved one decides the language
  again from its active course.
- **Neither given** — one `AskUserQuestion`: `Which source do you want to connect?`,
  options `Anki deck`, `Duolingo account`; then ask for the path or username (typed via
  Other).

## 2. Run it

From the project root, with a 10-minute timeout. Show the `[n/N] …` step headers, not
the full log.

On failure show the failed step and its hint and stop. For Anki the common ones: the
file is not an export (Anki → File → Export → *Anki Deck Package (.apkg)*), it holds
several decks (re-run with a deck name), or the export needs *Support older Anki
versions* ticked.

## 3. Report

From the JSON after `SUMMARY`: "{language_name}: {usable} words usable now
({new_usable:+} from this source)." One line.

## Rules

- Only `/connect` triggers this skill.
- One source per run. Never edit `setup.py` or connection data to make it pass.
