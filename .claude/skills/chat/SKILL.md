---
name: chat
description: Hold a conversation in the learner's language restricted to words the learner has actually been taught, then record what they knew, hesitated on, or missed. Triggered only when the learner types /chat.
allowed-tools: Read, Write, Bash
disable-model-invocation: true
---

# Constrained-Vocabulary Chat

Talk to the learner in the language they are practising, using **only words in their
lexicon**. The constraint is
the whole point: comprehensible input at exactly their level, which no general chat can
give them. Then record what the conversation revealed.

## When to use

Only on an explicit `/chat`. Never auto-invoke — this session writes to the lexicon and
the transcript, and a false trigger would corrupt both.

## 0. Preflight

```bash
python setup.py --check
```

If it exits non-zero, the lexicon is missing or not usable yet. Tell the learner to type
`/setup` (or `/sync`, if the output suggests `python setup.py --sync`) and stop.

The first line names the language: `language: French (fr)`. Call it **the language**
below, and use its name whenever you talk about it — never assume Japanese.

## 1. Load the working vocabulary

```bash
cd Profile/data/scripts
python lexicon.py stats
python lexicon.py vocab --compact
```

`stats` gives the course position and how many words are usable. `vocab --compact` is the
allow-list, one word per line as `word[reading] gloss/gloss` — the bracketed reading is
whatever the language shows next to a word (kana for Japanese, pinyin for Chinese) and is
simply absent for languages that need none. It is followed by up to two summary lines:

- `recycle (shaky or due): …` — words the learner got wrong or that the review schedule
  says are due. Work these in (see §3).
- `structural …: …` — the language's structural words (particles, articles, copula,
  common prepositions — whatever the language has), listed once rather than with their
  meaningless one-per-line glosses.

`through_unit` can be `null` when the words come from an Anki deck rather than a course;
that is fine — the preflight already confirmed there are usable words.

If the list is under ~50 words, say so and keep the conversation to greetings and single
nouns rather than pretending fluency is possible.

## 2. The vocabulary rule

**Every word you produce in the language must appear in the allow-list.** No exceptions
for words that are "obvious", common, or that you assume they picked up elsewhere —
including cognates and loanwords that look like English.

Structural words and inflections are the one carve-out: you may use the language's
structural words, which `vocab --compact` lists on its trailing `structural` line, and
you may inflect any listed word — conjugate a listed verb, make a listed noun plural,
agree a listed adjective — since courses teach these structurally rather than as lexical
entries. (For Japanese that line holds は/が/を/に/の and です; ます-forms of listed verbs
are fine.)

When you genuinely need a word that isn't available:

- Prefer working around it with words that are.
- If it's unavoidable, introduce it explicitly — write it with its reading (if the
  language uses one) and gloss, flag it as new, and add it at the end with
  `mark <word> exposed`.

Never silently reach outside the list. A conversation the learner half-understands is the
failure mode this whole project exists to avoid.

## 3. Conversing

- Open in the language at their level. For a small lexicon, one short sentence.
- Keep your turns to roughly the length of theirs, or slightly longer — comprehensible
  input works at i+1, not i+5.
- Put an English gloss in parentheses after your line **only** while the usable count is
  under ~300 words. Above that, let them ask.
- Recycle the words on the `recycle` line deliberately — they are the ones needing
  retrieval practice.
- Correct by recasting: reply naturally using the corrected form rather than stopping to
  mark work. Save explicit correction for the end-of-session summary.
- Follow the learner's interests. This is a conversation, not a drill.

## 4. Track as you go

Keep a running note of, for each word that came up:

- **known** — they used or understood it unprompted
- **shaky** — they hesitated, misused it, or asked what it meant
- **exposed** — you introduced it this session

Do not write to the lexicon mid-conversation. Batch it at the end — a chat that dies
halfway should not leave half-applied state.

## 5. End of session

When the learner says they're done (or types `/chat` again to stop), do three things.

**Write the transcript** to `Chats/YYYY-MM-DD-HHMM.md`:

```markdown
# Chat — {date}
Language: {language} · Unit: {through_unit} · Usable vocabulary: {count} words

## Transcript
{the conversation, in the language and English as it happened}

## Observations
- Confident: {words}
- Shaky: {words, with what went wrong}
- Introduced: {words}

## Next time
{one or two specific things to revisit}
```

**Update the lexicon** in a single call:

```bash
python Profile/data/scripts/lexicon.py mark 食べる known そうです shaky あたらしい exposed
```

(The words above are Japanese examples; use the session's own.) A word can be given in
any spelling the lexicon knows — for Japanese kanji, kana reading, or a variant — and
`mark` finds the record. Read the JSON it returns: words under `not_in_lexicon` were skipped,
and words under `ambiguous` matched several records — re-run `mark` for just those,
using the `word[reading]` key it lists, quoted (`'分[ふん]'`), since the shell treats
brackets as a glob. Everything else is already written; do not repeat it.

**Show a short summary** — how many turns, what went well, what to revisit. Keep it to a
few lines. No score, no streak, no badges.

## Rules

- Only `/chat` triggers this skill.
- Every word you produce in the language is in the allow-list, a structural word, an
  inflection of a listed word, or explicitly introduced.
- Batch all writes to the end.
- Never mark a word `known` on a single correct use of something they were just shown —
  that's `exposed` becoming `shaky` at best.
- Recasts over corrections during the conversation.
