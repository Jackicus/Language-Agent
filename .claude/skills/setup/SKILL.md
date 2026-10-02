---
name: setup
description: First run — connect the learner's Duolingo account, download the reference data, and build the lexicon so /chat and /quiz have words to use. Triggered only when the learner types /setup.
allowed-tools: Bash, Read, AskUserQuestion
disable-model-invocation: true
---

# First Run

Turn a fresh clone into something `/chat` can use, without the learner needing to know
the pipeline exists. `setup.py` does the work; this skill asks the one question it needs,
runs it, and explains the result in plain words.

## When to use

Only on an explicit `/setup`. Never auto-invoke — this writes the username, downloads
data and rebuilds the lexicon. Safe to re-run: learner evidence is never overwritten.

## 1. Say what is about to happen

One short paragraph, before asking anything:

- It reads their Duolingo progress and builds a word list from it.
- The first run downloads about 20MB (the JMdict dictionary and the JLPT lists) and takes
  a couple of minutes. Later runs are faster.

## 2. Get the username

Read `Connections/Duolingo/username.txt`.

- **It exists** — ask with `AskUserQuestion` whether to keep it: options `Keep <name>`
  and `Use a different account`. If they keep it, the command is `python setup.py`.
- **It is missing, or they want a different one** — ask with `AskUserQuestion` for the
  Duolingo username (they type it via "Other"). Say in the question that it is the
  **public profile name** shown on their Duolingo profile, not their email, and that the
  data comes from duome.eu, an unofficial Duolingo mirror — so the profile must be
  **public**. The command is `python setup.py <username>`.

Strip a leading `@` or a pasted profile URL down to the bare name.

## 3. Run it

From the project root, with a 10-minute timeout:

```bash
python setup.py <username>
```

Tell the learner it has started. When it returns, show the `[n/8] ...` step headers so
they can see what ran — not the full log.

## 4. On failure

`setup.py` exits non-zero and prints the failed step, the child's last lines, and a
hint. Show the step and the hint, add one plain sentence of your own, and **stop**. Do
not retry with guessed fixes. The common cases:

- **Profile not found / no response from Duolingo** — the username is wrong or the
  profile is private. Ask them to check the spelling on their profile page and that
  Duolingo's privacy setting allows a public profile, then type `/setup` again.
- **`through_unit` is null** — the account has no active Japanese course, so there is
  no position to unlock words from. Ask which unit they are on and offer:
  `python Profile/data/scripts/lexicon.py set-unit N`. Then run
  `python setup.py --check` to confirm it is ready.
- **A network step failed** (GitHub, duome) — usually transient. Suggest `/setup` again
  in a minute.

## 5. On success

The last line is `SUMMARY {...}` — parse the JSON after the word `SUMMARY`. Report in
two or three lines, plain words, no jargon:

> You're on unit {through_unit}. {usable} words are ready to chat with (out of {total}
> in the lexicon). Type `/chat` to start a conversation, or `/quiz` to be tested.

If `through_unit` is `null` here, treat it as the failure case above.

Then offer to open the showcase — the browsable page of everything — if `showcase` is
not null: `xdg-open showcase.html` (`open` on macOS). Only on a yes.

## Rules

- Only `/setup` triggers this skill.
- One question at a time; never ask for an email or password — none is needed.
- On failure, stop after explaining. Never edit `setup.py` or the data to make it pass.
- Report the SUMMARY numbers as given; do not recount from the lexicon.
