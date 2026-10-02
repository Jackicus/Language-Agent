# Language-Agent

Practise a language by chatting with Claude, using only the words your course has taught
you so far. It remembers what you knew, what you hesitated on, and what was new.

Works with Japanese, Chinese, Korean, French, German, Spanish, Italian, Portuguese.

## Setup

You need Python 3.9+, [Claude Code](https://claude.com/claude-code), and a Duolingo
account with a public profile or an Anki deck. Nothing to install.

```bash
git clone https://github.com/Jackicus/Language-Agent.git
cd Language-Agent
claude
```

Then type:

```
/setup
```

It asks for your Duolingo username (your profile name, not your email) and whether you
have an Anki deck, picks up the language from your active Duolingo course, downloads the
reference data (~20MB for Japanese, a minute or two), and builds your word list.

Then type:

```
/chat
```

That's it.

## Connect

| Source | What it gives | How |
|---|---|---|
| Duolingo | the course's words, unlocked unit by unit as you progress | `/setup`, or `/connect duolingo <username>` |
| Anki | your deck's cards; the ones you have reviewed count as met | `/connect anki <export.apkg>` |

## Day to day

| Type | When |
|---|---|
| `/chat` | Have a conversation in your language at your level |
| `/quiz` | Get tested on your words |
| `/sync` | After studying on Duolingo or Anki, to unlock the new words |
| `/switch` | Practise a different language; the old one's progress is kept |

## Without Claude Code

```bash
python setup.py <duolingo-username>               # first run; language from your active course
python setup.py --language fr --anki deck.apkg    # no Duolingo: say the language, give a deck
python setup.py --sync                            # after studying
python setup.py --check                           # is everything in place?
```

## Your data

`Profile/` holds your word lists — one folder per language — and everything you have
shown you know. It is git-ignored and cannot be re-downloaded, so back it up. Everything
else is re-fetched by `/sync`. Transcripts go in `Chats/`.

How it works under the hood: [CLAUDE.md](CLAUDE.md).
