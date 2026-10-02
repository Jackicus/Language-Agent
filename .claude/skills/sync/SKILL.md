---
name: sync
description: Daily refresh after studying on Duolingo — re-pull progress, rebuild the lexicon, and report which words just unlocked. Triggered only when the learner types /sync.
allowed-tools: Bash
disable-model-invocation: true
---

# Daily Sync

Pull today's Duolingo progress into the lexicon, so words from the units just finished
become usable in `/chat` and `/quiz`.

## When to use

Only on an explicit `/sync`. Never auto-invoke — this rebuilds the lexicon. Safe to run
any number of times: it only promotes `unseen` → `exposed`, never discards evidence.

## 1. Check it has been set up

```bash
python setup.py --check
```

If it exits non-zero, the project has never been set up (or something is missing). Tell
the learner to type `/setup` and **stop**.

## 2. Sync

From the project root, with a 10-minute timeout:

```bash
python setup.py --sync
```

This re-pulls from Duolingo, rebuilds the lexicon and the showcase. It skips the JLPT
lists and the dictionary when they are already present, so it is quick.

On failure, show the failed step and its hint, and stop. A "profile not found" or "no
response" failure means the username changed or the profile went private — point at
`/setup`.

## 3. Report

Parse the JSON after `SUMMARY` on the last line. One or two lines:

- `new_usable` > 0 — "Unit {through_unit}, +{new_usable} new words unlocked
  ({usable} usable now). Try `/quiz --only new` to meet them."
- `new_usable` = 0 — "Unit {through_unit}, nothing new unlocked — finish a unit on
  Duolingo and `/sync` again. {usable} words usable."

No streaks, no badges.

## Rules

- Only `/sync` triggers this skill.
- Not ready → `/setup`, never a partial fix.
- Report the SUMMARY numbers as given; do not recount.
