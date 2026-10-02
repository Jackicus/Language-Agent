---
name: setup
description: First run — connect the learner's Duolingo account (and optionally an Anki deck), work out the language, download the reference data, and build the lexicon so /chat and /quiz have words to use. Triggered only when the learner types /setup.
allowed-tools: Bash, Read, AskUserQuestion
disable-model-invocation: true
---

# First Run

Turn a fresh clone into something `/chat` can use, without the learner needing to know
the pipeline exists. `setup.py` does the work; this skill asks the few questions it
needs, runs it, and explains the result in plain words.

The language is chosen **once**. Normally it comes from the learner's active Duolingo
course and is never asked at all; the language question below only appears when that
cannot work.

## When to use

Only on an explicit `/setup`. Never auto-invoke — this writes the username and the
language, downloads data and rebuilds the lexicon. Safe to re-run: learner evidence is
never overwritten.

## 1. Say what is about to happen

One short paragraph, before asking anything:

- It reads their Duolingo progress (and an Anki deck, if they have one) and builds a word
  list from it, in the language their Duolingo course teaches.
- The first run may download reference data — about 20MB for Japanese (a dictionary and
  the JLPT lists) — and take a couple of minutes. Later runs are faster.

## 2. See what is already there

```bash
python setup.py --check
```

No network, safe to run any time. Note two things from its output:

- **The first line** — `language: Japanese (ja)` if a language is already chosen, or
  `language: not chosen yet`.
- **The `username.txt` row** — `ok … (name)` if a Duolingo username is saved.

## 3. Ask about the sources — one AskUserQuestion, two questions

**Question 1, Duolingo** (header `Duolingo`):

- **A username is saved** — `Keep <name>?`, options `Keep <name>`,
  `Use a different account`, `I don't use Duolingo`.
- **None saved** — `What is your Duolingo username? Type it via Other.` Say in the
  question that it is the **public profile name** shown on their Duolingo profile, not
  their email, and that the data comes from duome.eu, an unofficial Duolingo mirror — so
  the profile must be **public**. Options: `I don't use Duolingo`, `Where do I find it?`
  (on that one, explain briefly and ask again).

**Question 2, Anki** (header `Anki`): `Do you have an Anki deck to connect? It is
optional — you can add one later with /connect.` Options `No`, `Yes`.

Then, one at a time, only the follow-ups that apply:

- **Use a different account** → ask for the username (typed via Other).
- **Anki: Yes** → ask for the path to the exported file (typed via Other), options
  `Skip Anki for now`, `How do I export one?` (Anki → File → Export → *Anki Deck
  Package (.apkg)*; then ask again). If they mention a deck name, keep it for `--deck`.

Strip a leading `@` or a pasted profile URL down to the bare username. Anki is never a
blocker: if they skip it, carry on with Duolingo alone.

## 4. The language question — only when it cannot be inferred

Ask it **only** when Duolingo is not a source (they picked `I don't use Duolingo`) **and**
the `--check` first line said `not chosen yet`. In every other case setup.py already
knows the language — from the saved profile or from the active Duolingo course — and
asking would be asking twice.

One `AskUserQuestion` (header `Language`), names from `languages.json` in file order,
Japanese first. Options hold the first four; the rest are named in the question for
Other:

> **Which language do you want to practise?** Pick one, or choose Other and type German,
> Spanish, Italian or Portuguese.
>
> Options: `Japanese`, `Chinese`, `Korean`, `French`

Map the answer to its code (`ja zh ko fr de es it pt`) for `--language`.

If they use neither Duolingo nor Anki, there is nothing to build a word list from: say
so in one sentence, mention `/connect` for later, and stop.

## 5. Run it

From the project root, with a 10-minute timeout, building the command from the answers:

```bash
python setup.py [<username>] [--language <code>] [--anki <path> [--deck <name>]]
```

- `Keep <name>` → no username argument. A different account → the new username (its
  active course decides the language again).
- `--language` only when step 4 asked it.
- `--anki` only when they gave a path; quote it, paths often contain spaces.

Tell the learner it has started. When it returns, show the `[n/N] ...` step headers and
the `Language: …` line so they can see what ran — not the full log.

## 6. On failure

`setup.py` exits non-zero and prints the failed step, the child's last lines, and a
hint. Show the step and the hint, add one plain sentence of your own, and **stop**. Do
not retry with guessed fixes. The common cases:

- **Exit 2, "does not support yet"** — their active Duolingo course is a language this
  project cannot build. This is the one failure where you continue: ask the language
  question from step 4, then re-run the same command with `--language <code>` added.
- **Profile not found / no response from Duolingo** — the username is wrong or the
  profile is private. Ask them to check the spelling on their profile page and that
  Duolingo's privacy setting allows a public profile, then type `/setup` again.
- **`through_unit` is null with Duolingo as a source and nothing usable** — the account
  has no active course in that language, so there is no position to unlock words from.
  Ask which unit they are on and offer
  `python Profile/data/scripts/lexicon.py set-unit N`, then `python setup.py --check`.
- **Anki step failed** — usually the wrong file or several decks in one export. Show the
  hint; `/connect anki <path>` retries just that later.
- **A network step failed** (GitHub, duome) — usually transient. Suggest `/setup` again
  in a minute.

## 7. On success

The last line is `SUMMARY {...}` — parse the JSON after the word `SUMMARY`. Report in
two or three lines, plain words, no jargon, naming the language:

> You're set up for {language_name}, on unit {through_unit}. {usable} words are ready to
> chat with (out of {total} in the lexicon). Type `/chat` to start a conversation, or
> `/quiz` to be tested.

Drop the unit clause when `through_unit` is null and `connections` is only `anki` — the
words came from the cards they have reviewed, which is normal.

Then offer to open the showcase — the browsable page of everything — if `showcase` is
not null: `xdg-open showcase.html` (`open` on macOS). Only on a yes.

## Rules

- Only `/setup` triggers this skill.
- The language is asked at most once, and only when Duolingo cannot supply it.
- One question at a time after step 3; never ask for an email or password — none is needed.
- On failure, stop after explaining (the unsupported-course case is the one exception).
  Never edit `setup.py` or the data to make it pass.
- Report the SUMMARY numbers as given; do not recount from the lexicon.
