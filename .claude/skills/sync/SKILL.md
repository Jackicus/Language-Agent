---
name: sync
description: Daily refresh after studying — re-pull Duolingo progress, re-read a connected Anki deck, rebuild the lexicon, and report which words just unlocked. Triggered only when the learner types /sync.
allowed-tools: Bash
disable-model-invocation: true
---

# Daily Sync

Pull today's progress into the lexicon of the language being practised, so words from
the units just finished (or the Anki cards just reviewed) become usable in `/chat` and
`/quiz`.

## When to use

Only on an explicit `/sync`. Never auto-invoke — this rebuilds the lexicon. Safe to run
any number of times: it only promotes `unseen` → `exposed`, never discards evidence.

## 1. Check it has been set up

```bash
python setup.py --check
```

The first line names the language: `language: French (fr)`. Use that name in
everything you say below.

- First line `language: not chosen yet`, or a `NOT READY` line that asks for a
  username — the project has never been set up. Tell the learner to type `/setup` and
  **stop**.
- `READY`, or `NOT READY … run python setup.py --sync` — carry on. The second case is
  normal right after `/switch`: the new language has a source but no lexicon yet.

## 2. Sync

From the project root, with a 10-minute timeout:

```bash
python setup.py --sync
```

This re-pulls from Duolingo, re-reads the Anki deck if one is connected for this
language, and rebuilds the lexicon and the showcase. It skips the test lists and the
dictionary when they are already present, so it is quick — except the first sync after a
`/switch`, which downloads the new language's reference data.

On failure, show the failed step and its hint, and stop. A "profile not found" or "no
response" failure means the username changed or the profile went private — point at
`/setup`. An Anki failure usually means the exported file moved — point at
`/connect anki <path>`.

## 3. Report

Parse the JSON after `SUMMARY` on the last line. One or two lines, naming
`language_name`:

- `new_usable` > 0 — "{language_name}: unit {through_unit}, +{new_usable} new words
  unlocked ({usable} usable now). Try `/quiz --only new` to meet them."
- `new_usable` = 0 — "{language_name}: unit {through_unit}, nothing new unlocked —
  finish a unit on Duolingo and `/sync` again. {usable} words usable."
- `first_run` is true — this was the first build for this language: "{usable}
  {language_name} words ready." and nothing about what changed.

When `through_unit` is null and `connections` is only `anki`, leave out the unit and say
"from your Anki deck" instead; nudge them to review cards rather than finish a unit.
If `connections` includes `anki` alongside Duolingo, add "(Anki deck re-read)".

If the output printed a `note: your active Duolingo course is …` line, pass it on in one
sentence: unit progress only updates for the course that is active in Duolingo.

No streaks, no badges.

## Rules

- Only `/sync` triggers this skill.
- Never set up → `/setup`, never a partial fix.
- Report the SUMMARY numbers as given; do not recount.
