# Language-Agent

Practise Japanese by talking, inside Claude Code. The conversation only uses words your
Duolingo course has already taught you, so you understand what you read. After each
session it records which words you knew, which you hesitated on, and which were new —
and the next session works those back in.

## Requirements

- Python 3.9 or newer. Nothing to `pip install`.
- [Claude Code](https://claude.com/claude-code).
- A Duolingo account studying Japanese, with a **public** profile. Progress is read from
  duome.eu, an unofficial Duolingo mirror, which can only see public profiles.

## Quickstart

1. Open Claude Code in this folder: `cd Language-Agent && claude`
2. Type `/setup` and give your Duolingo username (the profile name, not your email).
   The first run downloads about 20MB and takes a couple of minutes.
3. Type `/chat`.

## Skills

| Type | What it does |
|---|---|
| `/setup` | First run: connects your Duolingo account and builds your word list |
| `/chat` | A Japanese conversation using only words you have been taught |
| `/quiz` | Multiple-choice questions on your words; records right and wrong |
| `/sync` | Run after studying on Duolingo — unlocks the words from new units |

The skills that write anything only run when you type them. Claude will not start them
on its own.

## Without Claude Code

Everything the skills read comes from two scripts:

```bash
python setup.py <duolingo-username>        # first run; later just: python setup.py --sync
python setup.py --check                    # what's present, missing or stale
python Profile/data/scripts/lexicon.py stats   # where you are and how many words are usable
```

`python Profile/data/scripts/build_showcase.py --open` writes `showcase.html`, a
browsable page of your account, word list and JLPT coverage.

## Where your data lives

- `Profile/` — **yours.** The lexicon and what you have shown you know. It cannot be
  re-downloaded, so back it up. The data files are git-ignored.
- `Connections/` — your Duolingo account data. Regenerable: `setup.py --sync` re-fetches it.
- `Resources/` — the JLPT lists and the JMdict dictionary. Same for everyone, regenerable.
- `Chats/` — one transcript per `/chat` session.

## Design

How words are matched, graded and tracked is in [CLAUDE.md](CLAUDE.md).
