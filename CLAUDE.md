# Language-Agent

A tracked chat space for learning **Japanese**. Open a terminal, talk, and the
conversation stays inside the vocabulary you have actually been taught — then what you
knew, hesitated on, and met for the first time gets recorded.

The shape of the whole thing: **connections form the Lexicon; the project uses the
Lexicon.** Duolingo units, JLPT lists, song lyrics, anime subtitles are all the same job
— read a source, emit words, merge. Nothing downstream needs to know where a word came
from.

```
Connections/<name>  ──fetch──>  raw tables  ──build_lexicon──>  Profile/lexicon.jsonl  ──>  /chat
```

The Lexicon lives under `Profile/` because it is **yours, not a source**. Connections are
replaceable and regenerable; the lexicon holds evidence about you that exists nowhere
else and can never be re-fetched.

## First run

- `/setup` once — asks for the Duolingo username, fetches everything, builds the lexicon.
- `/chat` daily — the conversation itself.
- `/sync` after studying on Duolingo — pulls new units, unlocks their words.
- `/quiz` to be tested on what has been unlocked.
- `python setup.py --check` when confused — what is present, missing or stale; no network.

## Layout

```
Connections/     YOUR accounts — things that know who you are. Only Duolingo so far.
Resources/       reference material that is the same for everyone: Tests, Dictionary
Profile/         you — lexicon.jsonl, names.jsonl, profile.json, and the build scripts
Chats/           chat transcripts, one file per session
showcase.html    generated browsable view of everything (see below)
.claude/skills/  the skills
_references/     cloned prior art — NOT part of this project, never import from it
```

The Connections/Resources split is the useful distinction: a connection is personal and
its data changes as you study; a resource is impersonal and changes only when the
upstream project publishes. Both feed the lexicon the same way.

## Skills

| Skill | What it does |
|---|---|
| `/setup` | First run: username, fetch, build; safe to re-run |
| `/chat` | Japanese conversation restricted to your lexicon; logs a transcript and updates confidence |
| `/quiz` | Forced-choice questions over the words you have been taught; records right and wrong |
| `/sync` | Daily refresh after Duolingo: `setup.py --sync`, reports newly unlocked words |

## Connections

Each connection folder holds its artifacts at the root and its code under `data/`.

### `Connections/Duolingo/`

duome.eu is an unofficial Duolingo mirror, and the only remaining way to get course
vocabulary and unit progress — Duolingo's own vocabulary endpoints were withdrawn in
2023. Run in this order; each script takes an optional username, defaulting to
`username.txt`.

```bash
cd Connections/Duolingo/data/fetch
python refresh-user-profile.py       # make duome re-pull from Duolingo — DO THIS FIRST
python fetch-user-data.py            # account facts + course registry -> profile.json, profile.png
python fetch-progress.py             # unit tree -> progress.json, and back-fills the course entry
python fetch-word-lists.py en ja     # course lexicon -> data/languages/English/japanese.csv
```

```
Connections/Duolingo/
  username.txt          who this account belongs to
  profile.json          account facts + the courses registry (see below)
  profile.png           the avatar; a set with profile.json, written by the same script
  assets/               stat icons — exp, streak, lingot, voc, league badge, flags
  progress.json         the unit tree for the active course
  data/fetch/           the scrapers
  data/languages/       course data, grouped by the language you learn FROM
    English/japanese.csv
```

The stat icons are **CSS background images on class names**, not `<img>` tags, so they
cannot be scraped from the markup. `fetch-user-data.py` collects the class tokens used
inside the profile element, resolves each against duome's stylesheet, and downloads
whatever it paints — which picks up the icons generically rather than by a hardcoded
list. Some results are sprite sheets (`flag.svg`, `icon.svg`); the usable singles are
`exp`, `streak`, `lingot`, `voc` and the league badge.

`profile.json` is the registry of what this account studies. Every course is keyed
`en-ja` style under `courses`, carrying XP, score, word count and `active`; the active
one also gets `through_unit`, `units_completed`, `units_total` and the path to its word
table. **Only the active course gets a tree** — duome renders the unit grid for whichever
course Duolingo currently considers active, so inactive ones stay summary-only with
`through_unit: null`. To get a tree for another language, switch course in Duolingo,
then refresh.

`refresh-user-profile.py` posts to duome's `/aggiorna.php` with your numeric Duolingo id
(read off the avatar URL). Without it duome serves whatever it last cached, which can be
months stale and shows **every unit as uncompleted** — silently wrong rather than
obviously broken, so never skip it.

`japanese.csv` is the full table: one row per word, `unit` being the unit that first
introduces it, `repeat_units` the later ones that revisit it. That column is the whole
trick — "which words do I have" becomes one comparison, no per-word tracking needed.

## Resources

Reference material, identical for every learner. Same folder shape as a connection.

### `Resources/Tests/`

Standardised exam vocabulary, for measuring coverage against a syllabus rather than
against a course.

```bash
python Resources/Tests/data/fetch/fetch-jlpt.py       # all five levels
python Resources/Tests/data/fetch/fetch-jlpt.py n5 n4
```

Writes `Japanese/jlpt-n5.csv` … `jlpt-n1.csv` (8,131 words: 718 / 668 / 2,140 / 1,906 /
2,699). Columns: `level`, `expression`, `reading`, `meaning`, `tags`.

**These lists are approximations.** JEES has published no official vocabulary list since
the 2010 revision, so every list in circulation is a community reconstruction from the
pre-2010 lists plus past-paper analysis. Source is
[open-anki-jlpt-decks](https://github.com/jamsinclair/open-anki-jlpt-decks), itself
derived from tanos.co.uk. Good enough to measure against; not a syllabus.

### `Resources/Dictionary/`

JMdict, the standard open Japanese–English dictionary. This resource exists because
Duolingo gives a surface form and a gloss and nothing else — for kanji-only entries
(東京, 私, 七時) it supplies **no reading at all**.

```bash
python Resources/Dictionary/data/fetch/fetch-jmdict.py          # ~22k common words
python Resources/Dictionary/data/fetch/fetch-jmdict.py --full   # ~200k, rarely needed
```

Writes `Japanese/jmdict.csv` with `kanji`, `kana`, `kanji_all`, `kana_all`, `pos`,
`senses`, `common`. Because each entry groups every spelling of one word, it doubles as a
**variant table**: look up たべもの and get 食べ物, which is the form the JLPT lists carry.
The "common" subset is used deliberately — the full file is mostly archaic vocabulary no
beginner course will ever surface.

The release filename carries a version and build timestamp, so `fetch-jmdict.py`
discovers the asset through the GitHub releases API rather than hardcoding a URL.

## The Lexicon (`Profile/`)

The merged word store, and the only thing `/chat` reads. It sits under `Profile/`, not
`Connections/`, because it is **yours** — connections are regenerable, this holds
evidence about you that can never be re-fetched.

```bash
cd Profile/data/scripts
python build_lexicon.py                  # merge connection tables -> lexicon.jsonl

python lexicon.py stats                  # coverage, confidence, course position
python lexicon.py tests                  # coverage against the JLPT levels
python lexicon.py vocab --compact        # the allow-list, prompt-ready
python lexicon.py mark 食べる known        # record what a session revealed (any spelling)
python lexicon.py look たべる             # full record for a word (any spelling)
python lexicon.py quiz --count 8         # multiple-choice items for /quiz
python lexicon.py quiz --only shaky      # ... or only due / shaky / new (never-tested) words
python lexicon.py review --compact       # words the review schedule says are due today
python lexicon.py set-unit 20            # manual position override
```

Skills talk to the lexicon through `lexicon.py`, never by reading `lexicon.jsonl`
directly — it's 10,672 records and won't fit in a prompt. `LEXICON_DIR=<dir>` points
every command at a copy of `lexicon.jsonl`/`names.jsonl`/`profile.json` (tests, dry
runs), and `LEXICON_TODAY=YYYY-MM-DD` fakes the date for scheduling.

- **Structural words** (particles, copula, さん: は が を に の か も です …) are never
  quizzed or used as distractors, and `vocab --compact` puts them on one trailing line.
- **`mark` resolves** a word by its record key, kanji form, kana reading or any variant.
  Unmatched and ambiguous words are reported in the output, not fatal; the rest is
  applied in one save. Where a spelling is shared (分 = ふん/ぶん) the key is `分[ふん]`.
- **`srs` is a Leitner schedule**, `{"box": 1-6, "due": date, "last": date}`, null until
  first marked. Box *n* waits 2^(n-1) days. `shaky` → box 1, due tomorrow. `known` → one
  box up (null counts as box 1), but only once due — an early correct answer changes
  nothing. `exposed`/`unseen` leave it alone. `quiz` asks due words first, then shaky,
  then the least-tested exposed, then known.

### What is in it

The **union** of the Duolingo course words and the JLPT test words, deduplicated on the
JMdict entry they resolve to — so おちゃ and お茶 are one record with
`sources: ["duolingo", "tests"]`, not two rows. Currently 10,672 words: 2,898
course-only, 5,739 test-only, 2,035 in both.

**Proper nouns go to `names.jsonl` instead.** たなか and トロント are not vocabulary, and
leaving them in would let "use words you know" mean reciting place names. They stay in
the Duolingo wordlist and get their own view in the showcase. A word counts as a name
when every token of every gloss is capitalised — with demonyms excluded, since
"Japanese" is ordinary vocabulary.

Fields, in record order:

| Identity | Grading | Provenance | Yours |
|---|---|---|---|
| `word`, `kana`, `kanji`, `romaji`, `gloss`, `hints`, `pos`, `script`, `variants` | `jlpt`, `rating`, `rating_source`, `matched` | `sources`, `unit`, `unit_name`, `unit_topic`, `audio` | `confidence`, `seen_count`, `first_seen`, `last_seen`, `srs` |

Everything except the last column is rebuilt from the connections and resources on every
run. Learner evidence is never overwritten — that rule is what makes it safe to
re-scrape daily.

**`gloss` is cleaned against the resolved entry; `hints` keeps the raw list.** Duolingo's
gloss is the union of every hint duome showed for the token in any sentence, so
homophones leak in: と carried "door" (戸) and "city" (都), は "tooth" (歯), さん "three"
(三) and "Mt." (山), ね "sleep" (寝). A course hint survives only if it agrees with a sense
of the JMdict entry the word resolved to — equal after lowercasing and dropping "to ",
trailing punctuation and parentheticals ("Mr." = "Mr", "(have) not" = "not"), or every
word of it appearing in one sense ("green tea" in "tea (esp. green or barley)").
Plurals and -ing/-ed count as the same word. A hint made only of function words must
match outright — as a subset, は's "with" rode along on "contrast **with** another
option". Duolingo's phrasing is kept where it agrees, since it is what the learner saw;
if nothing agrees, the entry's senses stand in — unless `best_entry` had to guess
between homophones, where nothing agreeing means the guess was wrong: しんろう "groom"
lands on 心労 and would otherwise become "anxiety". `hints` is written only where
cleaning dropped something (519 records). Test-list meanings are per-entry and are not
cleaned. Grading sees the cleaned gloss; `best_entry` sees the raw hints, since cleaning
needs an entry first. Names are judged on the raw hints too — a fallback to dictionary
senses would turn たなか back into vocabulary.

Cleaning exposed that **grammar has no English to overlap with**: は's hints are "is",
"with", "for" … and the one noun, "tooth", had resolved it to 歯. So when most hints are
function words, `best_entry` takes a particle/auxiliary/conjunction candidate whose
headword is the word (headword only — otherwise て lands on って). That moved five
words: は, な, し, ば off 歯, 名, 市, 場, and いる off 射る ("to shoot") onto 居る. 歯, 名
and 場 get their own test-list records back, し stops being folded into 市, and the test
list's 居る merges into いる — net +3 records.

**さん still cites 三, and that is not a gloss problem.** The `reading` tier fires on any
test row whose reading equals the word and never looks at meaning. Restricting it to
rows that are forms of the resolved entry was tried: it fixes かじ → 家事, しろ → 城,
さん, は, の, に — but moves ~75 words and exposes `best_entry` errors it was masking
(すき → 隙, りょうしん → 良心, きょうだい → 強+大). Fix entry resolution before guarding it.

Current fill: **100%** rated, 84% with a kana reading, 8,799 with a kanji form, 7,531
with spelling variants.

### Grading: `jlpt` and `rating` are separate

- **`jlpt`** (bool) — is this exact word actually in a JLPT list? Only this number means
  anything for exam readiness.
- **`rating`** (1–5, 5 = N5 easiest) — how hard is it, listed or not.

コーヒー is `jlpt: true, rating: 5`. アイスコーヒー is `jlpt: false, rating: 5` — not
listed, but it contains コーヒー and cannot be harder than its parts. Keeping them apart
means every word gets a usable difficulty without inflating exam coverage.

`rating_source` records which tier decided it. The first four mean "this is the listed
word"; the rest mean "not listed, but here is a defensible difficulty".

| Tier | `jlpt` | Rule | Count | Example |
|---|---|---|---|---|
| `expression` | ✅ | written exactly as the list has it | 7,145 | こんにちは |
| `reading` | ✅ | the kana reading of a kanji entry | 644 | おちゃ → お茶 |
| `inflection` | ✅ | polite form reduces to a listed dictionary form | 407 | 買います → 買う |
| `variant` | ✅ | a **kanji** spelling of the same word is listed | 28 | 友だち → 友達 |
| `composite` | ❌ | compound of listed parts, at its **hardest** part | 396 | 何月 → 何+月 |
| `contains` | ❌ | a listed word makes up most of it | 449 | アイスコーヒー → コーヒー |
| `stem` | ❌ | senses overlap **and** a written stem is shared | 194 | つぎの → 次 |
| `course-position` | ❌ | last resort: where the course introduces it | 1,409 | ピザ, コンビニ |

`contains` needs two guards, both earned from false positives: the piece must weigh ≥3
(kanji counting double) and cover ≥55% of the word. Without them サッカー inherits from
カー ("car"), パスタ from パス, ファンタジー from ファン, と言います from ます.

`course-position` is **not a JLPT judgement** — it is the only signal left for loanwords
the lists structurally ignore. Monotonic in course order and labelled as such, so it can
be filtered out wherever it would mislead.

Names are rated from their script instead: a kanji name takes its hardest character's
level, an unplaceable kanji name is N1, and short kana names are N5.

**`composite` is the fix for Duolingo teaching compounds as single "words".** 何月, 七月,
十二月 and 百円ショップ are not test entries; 何, 月, 七 and 円 are. Scored at the hardest
part, because a compound is only readable once you know all of it. Two guards:

- **kanji only.** Kana strings segment into nonsense — every kana sequence splits into
  "known" pieces, so すし becomes す (vinegar) + し (death) and たなか becomes たな + か.
  Kanji carries enough per character for the same greedy split to mean something.
- **the JMdict kanji form is tried too**, which is what reaches kana-written compounds:
  ちゅうごく is unsplittable as kana, but resolves to 中国 → 中 + 国. This is also how
  やきゅう gets N3 despite 野球 being absent from the lists — via 野 + 球.

**`variant` follows kanji spellings only.** Kana readings are homophone magnets: JMdict
lists とうけい as an alternate reading of 東京, and following it lands on 統計
("statistics"); 時's じ lands on 字. Restricting to kanji drops those and keeps
友だち → 友達, ご飯 → 御飯, れんしゅう → 練習.

The `inflection` tier exists because Duolingo teaches verbs in the polite ます-form while
the test lists give dictionary form. Undoing that is deterministic, so an exact hit on a
generated form is strong evidence on its own. It needs three structural guards, each
earned from a real false positive:

- **irregulars are hardcoded** — the regular rules turn します into しる, which hits 知る
  ("to know"). する and 来る are listed explicitly.
- **one-character results are rejected** — し reduces to す, which hits 酢 ("vinegar").
- **particles are never stripped** — tempting (日本の → 日本) but さんは reduces to さん and
  hits 三 ("three"), and どうが → どう. A particle changes the meaning, so there is
  nothing left to corroborate against.

Sense overlap is used as a *tie-breaker* here, not a gate: gating on it drops 学びます →
学ぶ, because "learns" and "to learn; to study" share no exact sense string.

That third guard is the important one. Matching on meaning alone is what recovers
conjugations (`たべます` → `食べる`) — the whole reason to do it — but unguarded it also
pairs わたしの ("my, **mine**") with 鉱山 ("a **mine**"), やきゅう with ナイター, and ロック
with 岩石. On this data pure-meaning matching came out **68% ambiguous**. Requiring a
shared leading stem (one kanji counting as much as two kana) keeps the conjugations and
drops the homonyms: 763 meaning candidates get rejected by it, and should be.

Coverage is measured against *words the lexicon could match to a level*, not the full
level — the course does not teach every JLPT word. `lexicon.py tests` reports progress
through what you have been exposed to, **not** readiness to sit the exam.

**N5 having more matched words than N1 is expected, not a bug.** The counts are lexicon
words per level, not list sizes, and Duolingo is a beginner course:

| Level | List has | Lexicon words | Distinct entries hit | Coverage of list |
|---|---|---|---|---|
| N5 | 718 | 921 | 638 | **89%** |
| N4 | 668 | 628 | 460 | 69% |
| N3 | 2,140 | 983 | 839 | 39% |
| N2 | 1,906 | 374 | 331 | 17% |
| N1 | 2,699 | 291 | 273 | **10%** |

921 N5 words against a 718-entry list is many-to-one: 八/八歳/八本/八冊/八個 all cite 八,
and つぎ/つぎの/次/次に all cite 次. The falling coverage from 89% to 10% is the real
signal, and it is the shape a beginner course should produce.

**The source list is incomplete, and that is the binding constraint.** It totals 8,131
entries against a published estimate of ~10,000 through N1, and is short at every level.
Verified absent: 野球, 寿司/すし, 弁護士, 警察官, 看護師, 美容院, 洗濯機, 掃除機 — all
ordinary N4–N3 vocabulary. Present and matching fine: 自転車, 飛行機, 新聞, 図書館, 冷蔵庫,
医者, 大学. Every mainstream free JLPT list (open-anki-jlpt-decks, yomitan-jlpt-vocab,
wkei/jlpt-vocab-api, Bluskyo) descends from Jonathan Waller's tanos.co.uk lists, so
**switching between them changes nothing** — wkei's copy was checked directly and lacks
the same words. Improving coverage means a different lineage, not a different repo.

**Sense comparison is exact, deliberately.** Senses are split on commas/semicolons,
lowercased, and `to ` stripped, then compared for equality. Loosening this to word-level
overlap was tested and rejected: it adds 381 matches, but they are compound-to-part
mismatches — バスてい→バス, エアコン→エアメール, 二階→二日, 三年生→三日, 日本の→日の丸. That
inflates coverage with wrong levels. Word-overlap is used only as a tie-breaker inside
the `inflection` tier, never as a matcher.

**Why ~1,990 words still have no level.** Not because matching failed — because they have
no level to find. 978 are katakana loanwords and foreign names (ピザ, ラーメン, カナダ,
ブラジルじん), 435 are phrases Duolingo teaches as single words (またあした, にすんでいます,
はありますか), 45 are bare particles (が, を, も), and the rest are words genuinely absent
from the lists (すし, 弁護士 — verified `NOT IN LISTS` against all 8,131 entries). Before
chasing this further, check whether the word is in `Resources/Tests/Japanese/*.csv` at
all, and whether JMdict gives it a kanji form that would decompose.

## Showcase

```bash
python Profile/data/scripts/build_showcase.py --open
```

Writes `showcase.html` at the root. Two sections:

- **Profile** — a card per connection: avatar with league badge, stat tiles using the
  scraped icons, league standing and account history, and a chip per course with a
  progress bar for the active one.
- **Connections** — one panel each: *Profile* (the Lexicon, marked as yours rather than a
  source), *Duolingo* (Japanese Wordlist), and *Tests* (Japanese JLPT N5…N1). Picking a
  chip loads it into the table below.

Tables are generic — each dataset declares its own columns, which facet filters it wants,
and whether it has a lock column. Sort on any column, free-text search, and a play button
on each Duolingo word's pronunciation clip. The lexicon defaults to unlocked words only.

It is **generated, not live**. A page opened over `file://` cannot `fetch()` its sibling
files — browsers treat every local read as cross-origin — so the data is baked in and
the avatar embedded as a data URI. That keeps it a single double-clickable file with no
server, at the cost of needing a rebuild after new data. Re-run it after
`build_lexicon.py`. Audio is the only thing fetched live, from Duolingo's CDN.

**Confidence ladder:** `unseen` → `exposed` (the course taught it) → `shaky` (hesitated
or got it wrong) → `known` (used unprompted). Only the last three are usable in chat.

## Working notes

- `build_lexicon.py` is the only thing that writes the lexicon. Connections may add words
  and refresh what they own (reading, gloss, unit, audio); they must **never** overwrite
  `confidence`, `seen_count`, `srs`. Advancing a unit can promote `unseen` → `exposed`
  and nothing else — demoting would discard evidence the learner actually produced.
- Two course spellings of one word (おちゃ unit 1, お茶 unit 66) merge into one record, and
  the **earliest** unit wins; every other unit goes to `repeat_units`. Last-row-wins put
  607 of 609 merged words at their later unit and locked おちゃ out of chat.
- Course position lives on the course entry in the connection's `profile.json`.
  `Profile/profile.json` mirrors it per connection for the learner's own view; the
  connection is the authority.
- Batch writes to the end of a session. A session that dies halfway should leave no
  half-applied state.
- Skills that write are gated with `disable-model-invocation: true`.
- `exposed` means *the course introduced this*, not *you know this*. Chat's job is to
  turn the first into the second.

## Gotchas found the hard way

- Kanji-only entries (東京, 私) carry **no `[romaji]` span** on duome. A parser that
  requires one silently drops ~3,000 words. Check the count against the profile's
  lexeme total.
- The `/level/N` in a unit's URL is how many levels that unit *offers*, not your crown
  level — untouched units carry it too. It is course metadata, not progress.
- The avatar CDN answers with `Content-Type: image` — no subtype, so it tells you
  nothing. Sniff the magic bytes instead; `_common.image_format()` does.
- Duolingo's word counter said 312; units 1–20 of the course list give 299. The gating
  approximation lands within ~4%, which is the evidence it works.
- A `position: sticky` table header does nothing inside a container that only scrolls
  horizontally — sticky pins to the nearest scrollport, and if the *page* is what scrolls
  vertically the header has nothing to pin to. The scroller must own both axes
  (`max-height` + `overflow: auto`), which is why `.scroll` is capped at `70vh`.

## Planned

- `Connections/Anime` — subtitles (`.srt`/`.ass`) as a corpus; timestamps give clip
  lookup for any word via ffmpeg
- `Connections/Music` — local library tags → [LRCLIB](https://lrclib.net/docs) synced lyrics
