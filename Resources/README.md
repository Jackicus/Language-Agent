# Resources

Impersonal reference data, the same for every learner: one graded **test list** and one
**dictionary** per language. Which fetchers a language uses is set by
`languages.json` (`tests.source`, `dictionary.source`); the file layout and CSV schemas
are fixed by `CONTRACTS.md` §3–4. All fetched CSVs are git-ignored and regenerable.

```bash
python Resources/Tests/data/fetch/fetch-<tests.source>.py [levels...]
python Resources/Dictionary/data/fetch/fetch-<dictionary.source>.py [--full]
```

Every fetcher is stdlib-only, supports `-h`, prints what it wrote with row counts, and on
a network failure prints one `error:` line and exits 1 (no traceback, no half-written
file — output goes to `*.part` and is renamed on success). Shared plumbing lives in
`Resources/_fetchlib.py` (network, CSV, Wiktionary reader, frequency bands) and
`Resources/_korean.py` (the NIKL/TOPIK table).

## Sources

| Lang | Tests source → files | Levels (rows) | Official | Dictionary source → file | Rows (common) | Licences |
|---|---|---|---|---|---|---|
| ja | `jlpt` → `Japanese/jlpt-n5.csv`… | N5 718 · N4 668 · N3 2,140 · N2 1,906 · N1 2,699 = **8,131** | yes | `jmdict` → `Japanese/jmdict.csv` | 22,626 | open-anki-jlpt-decks (MIT, from tanos.co.uk CC BY); JMdict CC BY-SA 4.0 |
| zh | `hsk` → `Chinese/hsk-1.csv`… | HSK1 150 · HSK2 147 · HSK3 298 · HSK4 598 · HSK5 1,298 · HSK6 2,500 = **4,991** | yes | `cedict` → `Chinese/cedict.csv` | 120,818 (11,813) | complete-hsk-vocabulary MIT; CC-CEDICT CC BY-SA 4.0 |
| ko | `topik` → `Korean/topik-1.csv`… | 920 · 911 · 960 · 960 · 926 · 846 = **5,523** | yes (bands split by us) | `wiktionary-ko` → `Korean/wiktionary-ko.csv` | 35,717 (6,981) | combined_korean_vocabulary_list MIT (data from NIKL/NIIED); Wiktionary CC BY-SA 4.0; kengdic MPL 2.0/LGPL |
| fr | `freq-fr` → `French/freq-fr-a1.csv`… | 500 · 1,000 · 2,000 · 3,000 · 5,000 · C2 5,924 = **17,424** | no | `wiktionary-fr` → `French/wiktionary-fr.csv` | 20,747 (7,921) | FrequencyWords content CC BY-SA 4.0; Wiktionary CC BY-SA 4.0 |
| de | `freq-de` | … · C2 9,465 = **20,965** | no | `wiktionary-de` | 22,802 (7,472) | same |
| es | `freq-es` | … · C2 4,215 = **15,715** | no | `wiktionary-es` | 19,514 (7,633) | same |
| it | `freq-it` | … · C2 8,233 = **19,733** | no | `wiktionary-it` | 23,199 (7,745) | same |
| pt | `freq-pt` | … · C2 4,682 = **16,182** | no | `wiktionary-pt` | 18,354 (6,638) | same (frequency list is Brazilian, `pt_br`) |

Counts are from the run on 2026-10-02. Upstream sources move, so expect drift.

### Download sizes and timings (one run, home broadband)

| Fetcher | Downloads | Time |
|---|---|---|
| `fetch-jlpt.py` | 5 small CSVs | 2 s |
| `fetch-hsk.py` | 3 MB JSON | 4 s |
| `fetch-cedict.py` | 4 MB gz + 3 MB HSK JSON | 5–9 s |
| `fetch-wiktionary-ko.py` | 21 MB gz (streamed) + 12 MB kengdic + 1 MB list | 15–50 s |
| `fetch-topik.py` | 1 MB list (+ the dictionary if missing) | <1 s |
| `fetch-wiktionary-fr.py` | 56 MB gz, streamed (584 MB uncompressed) + 0.6 MB frequency list | 20–40 s |
| `fetch-wiktionary-de.py` | 94 MB gz, streamed (1.1 GB uncompressed) | 43–60 s |
| `fetch-wiktionary-es.py` | 91 MB gz, streamed (1.05 GB uncompressed) | 42–46 s |
| `fetch-wiktionary-it.py` | 72 MB gz, streamed (770 MB uncompressed) | 23–26 s |
| `fetch-wiktionary-pt.py` | 54 MB gz, streamed (577 MB uncompressed) | 19 s |
| `fetch-freq-*.py` | 0.6 MB frequency list (+ the dictionary if missing) | 1–8 s |

The Wiktionary dumps are decompressed and parsed as they arrive; nothing large is
written to disk; peak memory is ~300 MB (Italian, the largest lemma count).

## Per language

### Chinese — HSK 2.0 + CC-CEDICT

- **Tests**: [drkameleon/complete-hsk-vocabulary](https://github.com/drkameleon/complete-hsk-vocabulary),
  which merges the HSK 2.0 and HSK 3.0 lists with CEDICT meanings and pinyin. The
  registry's six levels are **HSK 2.0** (2009–2021, 4,991 distinct words; a word listed
  at two levels takes the lower). HSK 3.0 has nine levels with 7–9 merged; rather than
  invent a mapping onto six labels, each row's HSK 3.0 level is kept in `tags`
  (`hsk2.0 hsk3.0-2`). HSK 3.0-only words (~6,500) are not written. Note 你好 is not on
  HSK 2.0 (你 and 好 are, separately).
- **Dictionary**: MDBG's [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cedict)
  export, fixed URL, refreshed daily. One row per (simplified, pinyin): 行 xíng and 行 háng
  are separate rows, while 水 shuǐ and the surname 水 Shuǐ merge (common-noun senses
  first). `reading` is tone-marked pinyin (`xiè xie`), the same format as the HSK
  `reading`; `readings` keeps CEDICT's numbered form (`xie4 xie5`, `nu:3`). `pos` comes
  from the HSK data and is empty for non-HSK words. `common` = in any HSK 2.0/3.0 list
  with that reading. `CL:` classifier notes are dropped from `senses`. Default omits
  2,884 entries that are only "variant of X"; `--full` keeps them.

### Korean — TOPIK (published list, our six-way split) + Wiktionary

- **Tests**: [julienshim/combined_korean_vocabulary_list](https://github.com/julienshim/combined_korean_vocabulary_list)
  `results.tsv`, derived from TOPIK's **2015 published vocabulary list** (5,992 rows,
  graded only 초급 / 중급) and NIKL's 2003 learner list (A/B/C + frequency rank). Only
  TOPIK words are written (NIKL-only words are not exam vocabulary). The six levels are
  our split, tagged `level-split`: 초급 halved into TOPIK1/2, 중급 quartered into TOPIK3–6,
  ordering each band by NIKL grade then NIKL frequency rank (words with no NIKL grade
  last). `official: true` because membership is the published list; the 1-vs-2 and
  3-vs-6 boundaries are not published anywhere. 5,679 distinct (word, hanja) pairs;
  **156 dropped** for having no English gloss in either dictionary.
- **Dictionary**: kaikki.org's English-Wiktionary extract, Korean section (21 MB gz),
  every lemma kept; conjugated-form entries (`ko-verb-form`) are skipped. Homographs with
  different hanja stay separate rows (가구 家具 "furniture"). `reading` is Wiktionary's
  Revised Romanisation (`meokda`), `forms` is hanja. 546 NIKL/TOPIK words that Wiktionary
  lacks entirely (강의실, 관광지 — mostly Sino-Korean compounds) are filled from
  [kengdic](https://github.com/garfieldnate/kengdic), matched on hanja where possible.
  kengdic was not used as the main dictionary: it has no part of speech and its glosses
  are noisy (먹다 "Go deaf" beside "Eat"). `common` = on the NIKL or TOPIK list.
  `--full` is accepted and changes nothing.

### French, German, Spanish, Italian, Portuguese — frequency bands + Wiktionary

**There is no official CEFR word list for any of these.** The tests are frequency
bands, labelled with CEFR letters only because the registry needs six labels. Every row
carries `tags=frequency-band` and the registry says `official: false`.

- **Frequency**: [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords)
  OpenSubtitles 2018, top 50,000 word forms (`pt_br` for Portuguese — the variety the
  Duolingo course teaches). Subtitle frequency is a good proxy for spoken, everyday
  vocabulary, which is what a beginner course teaches; it underweights written and
  academic vocabulary.
- **Lemmatisation**: word forms are mapped to lemmas through the dictionary. A form that
  spells a lemma counts for it; otherwise it counts for the lemma it inflects, and when
  several lemmas claim one form, only the one whose own spelling is most frequent
  ("suis" → être, not suivre; "les" → le, not ils/elles). Outside German, a casefolded
  form prefers the lowercase lemma (são, not São). A lemma's rank is its best form's.
- **Bands (cumulative lemmas)**: A1 1–500 · A2 501–1,500 · B1 1,501–3,500 ·
  B2 3,501–6,500 · C1 6,501–11,500 · C2 the rest. These follow the commonly cited
  vocabulary-size estimates per CEFR level (roughly 500–1,000 lemmas for A1, ~1,500 by
  A2, ~3,000–3,500 by B1, ~6,000 by B2, ~10,000+ for C1; cf. Milton & Alexiou 2009, the
  English Vocabulary Profile). C2 is everything else that resolves, which is why its
  size varies per language.
- **Dropped**: forms with no dictionary lemma — names, English words, clitic fragments
  ("avez-vous", "quelqu'") — fr 15,758 · de 14,103 · es 10,793 · it 13,574 · pt 13,784
  of the 50,000.
- **Dictionary**: kaikki.org Wiktionary dumps, streamed. Kept: every lemma whose own
  spelling **or any of its inflected forms** is among the 50,000 frequency words, plus
  short set phrases made only of such words (`s'il vous plaît`). `--full` keeps every
  lemma. Entries that are only "inflection of X" / "alternative form of X" are folded
  into X's `forms` instead of becoming rows, so `headword` is always a lemma and `forms`
  carries the inflections (`manger` → `mangé|mange|manges|…`). Excluded from `forms`:
  auxiliaries (haben, avere), derived words (Kätzchen), obsolete/archaic forms, and
  Wiktionary's stress-marked Italian display forms (`màngio` is normalised to `mangio`).
  `common` = the lemma or one of its forms is in the top 10,000. Proper names are not
  kept. FreeDict was the alternative; kaikki was chosen because it is the same format
  for all five languages, has English senses with part of speech, and carries full
  inflection tables.
- **German / Goethe-Institut**: the Goethe A1/A2/B1 Wortlisten were looked for and not
  used. They are © Goethe-Institut and published only as PDFs; the GitHub transcriptions
  found (wejn/goethe-b1-wortliste is a PDF extractor, langfield/A2_Wortliste_Goethe is
  one Markdown file per word, kennethsible/goethe-wortliste is B1 only) are unlicensed,
  per-level and from different hands. German uses the same frequency bands as the rest.

## Caveats

- **JLPT and HSK 2.0 are community-maintained reconstructions or merges of official
  lists**, not something the exam bodies publish in machine-readable form. See CLAUDE.md
  for the JLPT lineage problem (every free list descends from tanos.co.uk).
- **TOPIK levels 1–6 are an approximation** inside two published bands.
- **CEFR labels on fr/de/es/it/pt are frequency bands, not syllabi.** `listed` (in a test
  file) means "among the ~15–21k most frequent lemmas" for these languages, nothing more.
  Filter on `tags=frequency-band` wherever exam-readiness would be implied.
- **Homographs take their spelling's frequency.** The frequency list is of word forms
  and cannot tell French *est* "east" from *est* "is", so est ("east") lands in A1;
  likewise Portuguese *foi*/*estou* have interjection lemmas that inherit the verb's
  frequency. The verbs themselves (être, ser, estar) still rank correctly through their
  other forms.
- **Wiktionary coverage is uneven.** Glosses are as good as English Wiktionary's entry,
  and the first sense is not always the most common one in speech.
- **Duolingo course codes**: Chinese is `zs` on duome (`zh` there is a Cantonese
  fallback); the registry key stays `zh`.
