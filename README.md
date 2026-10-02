# Language-Agent

Practise Japanese by chatting with Claude, using only the words your Duolingo course has
taught you so far. It remembers what you knew, what you hesitated on, and what was new.

## Setup

You need Python 3.9+, [Claude Code](https://claude.com/claude-code), and a Duolingo
account with a public profile. Nothing to install.

```bash
git clone https://github.com/Jackicus/Language-Agent.git
cd Language-Agent
claude
```

Then type:

```
/setup
```

It asks for your Duolingo username (your profile name, not your email), downloads the
reference data (~20MB, a minute or two), and builds your word list.

Then type:

```
/chat
```

That's it.

## Day to day

| Type | When |
|---|---|
| `/chat` | Have a conversation in Japanese at your level |
| `/quiz` | Get tested on your words |
| `/sync` | After studying on Duolingo, to unlock the new words |

## Without Claude Code

```bash
python setup.py <duolingo-username>   # first run
python setup.py --sync                # after studying
python setup.py --check               # is everything in place?
```

## Your data

`Profile/` holds your word list and everything you have shown you know. It is
git-ignored and cannot be re-downloaded, so back it up. Everything else is re-fetched by
`/sync`. Transcripts go in `Chats/`.

How it works under the hood: [CLAUDE.md](CLAUDE.md).
