---
name: quiz
description: Test the learner on words they have been taught, using forced-choice questions, then record what they got right and wrong. Triggered only when the learner types /quiz.
allowed-tools: Bash, AskUserQuestion
disable-model-invocation: true
---

# Vocabulary Quiz

Ask multiple-choice questions drawn from the learner's unlocked words, then write the
results back to the lexicon.

This exists because `/chat` cannot measure much. A conversation only shows you the words
the learner chose to use; it never shows you the ones they quietly avoided. A quiz picks
the words, so a wrong answer is real evidence and so is a right one.

## When to use

Only on an explicit `/quiz`. Never auto-invoke — this writes to the lexicon.

## 0. Preflight

```bash
python setup.py --check
```

If it exits non-zero, the lexicon is missing or not usable yet. Tell the learner to type
`/setup` and stop.

## 1. Pull the items

```bash
cd Profile/data/scripts
python lexicon.py quiz --count 8
```

Add `--direction en2jp` if the learner asks to be tested the other way (English prompt,
Japanese options). That direction is harder — it tests production, not recognition.

Items come back already prioritised: words the review schedule says are due, then
`shaky`, then the least-tested `exposed`, with `known` only filling the round. If the
learner asks for a narrower round, add `--only due`, `--only shaky` or `--only new`
(never-tested words). `python lexicon.py review --compact` shows what is due, if they ask.
Particles and the copula are never quizzed.

Each item comes back with `prompt`, `options` (already shuffled), `answer`, and `word`.
**Do not invent options or reorder them.** The distractors are drawn from the same JLPT
rating on purpose; substituting your own turns "did they know this word" into "did they
recognise any of these".

If `items` is empty, report the error it returns and stop.

## 2. Ask

Use `AskUserQuestion`, up to 4 items per call — so a default round of 8 is two calls.

- `question` — the item's `prompt`, phrased as a question: `What does 食べる [たべる] mean?`
  (for `en2jp`: `Which word means "to eat"?`)
- `header` — a short tag, e.g. the item's `rating` (`N5`) or `Word 3`
- `options` — the item's `options`, in the order given, one per option `label`
- `description` — keep it neutral (`—`). Anything written here is a hint.
- `multiSelect` — always `false`

Don't reveal the answer between calls. Grade at the end.

## 3. Grade

Compare each answer against the item's `answer` string.

- Correct → `known`
- Wrong → `shaky`
- The learner picked "Other" or wrote their own text → **skip it**, mark nothing. You do
  not know what they meant.

## 4. Write it back

One call, at the end, never mid-round:

```bash
python Profile/data/scripts/lexicon.py mark 食べる known そうです shaky
```

Use each item's `word` exactly. Where two records share a spelling it comes as
`word[reading]` (`分[ふん]`) — quote those, since the shell treats brackets as a glob.
If the output lists anything under `not_in_lexicon` or `ambiguous`, say so; everything
else was written in that one call. `known` and `shaky` also reschedule the word for
review, so the next round brings back what was missed.

A round that dies halfway should leave nothing behind.

## 5. Report

Show the score, then each wrong answer as `word [reading] — what they picked → what it
means`. Offer to run another round. Keep it to a few lines: no streaks, no badges.

## Rules

- Only `/quiz` triggers this skill.
- Options come from `lexicon.py quiz`, unchanged.
- Batch all writes to the end.
- Wrong answers demote to `shaky` even from `known` — that is the point of testing.
- Never quiz a word that isn't in the returned items; the script already filters to what
  the learner has actually been taught.
