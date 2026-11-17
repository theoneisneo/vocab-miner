# AGENTS.md: working on vocab-miner

Instructions for AI coding agents (Codex, Cursor, Gemini CLI, Claude Code, …) and for people who work like them.
vocab-miner builds vocabulary lists, flashcards and a sing-along web app from material you are learning a language
with: songs, games, videos, novels. The full tutorial is `docs/getting-started.md` (in Traditional Chinese); the
design is `docs/architecture.md`; the web app's data format is `docs/web-data-format.md`.

Start by reading any private notes the user keeps next to this file (for example `CLAUDE.local.md`). They are not in
git and may say which projects exist and where the material comes from.

## The one rule: public framework, private material

This repository is public. The material (lyrics, game text, subtitles) is copyrighted, and how it was obtained is
private.

- **Never commit material**: no lyrics, lines, subtitles or translations of real works, and nothing generated from
  them (corpora, vocabulary lists, data files). They live only in the gitignored folders `data/`, `out/`, `.cache/`,
  `inbox/`, `private/`, plus `config.local.toml` and `CLAUDE.local.md`.
- Code that targets one specific website or one specific game goes in `private/sources/` (gitignored). Code,
  docs, tests and commit messages must not name those sites, games' text, or the tools used to get material.
- Tests use only sentences written for the tests or public-domain text (`tests/fixtures/`).
- `scripts/check_no_corpus.py` runs before every commit. When it blocks something, fix the content; never weaken
  the check or skip it.
- When unsure where something belongs, put it in `private/` and ask the user.

## Setup and checks

```bash
uv sync --extra ja --extra whisper      # Python 3.12+, managed with uv; add --extra en for English
uv run pytest                           # must pass before a commit
uv run ruff check src tests
uv run vm --help                        # every command; `uv run vm <command> --help` for one
```

The user's main machine is Windows 11 with PowerShell 7: open files with `encoding="utf-8"` (CSV for Excel:
`utf-8-sig`), use `pathlib`, and keep `.ps1` files ASCII-only.

## Content tasks (the usual work)

A *project* is a folder with a `config.local.toml`; every command takes `--root <folder>` (default: the current
folder). Song projects made by `vm new` live in `data/<name>/` with their lyrics in `data/raw/<name>/`.

| Task | What to do |
|---|---|
| New artist / album set | `uv run vm new <name> <playlist or YouTube Music album URL>... --artist <name>`, then `uv run vm update --root data/<name>` |
| More songs or albums | add a line `lang \| album \| url` to `data/<name>/playlists.txt`, then `vm update --root data/<name>` |
| Wrong song title or artist | `data/raw/<name>/titles.tsv`: `video id<TAB>title[<TAB>artist]`, then `vm update` |
| Leave a video out | its video id or title on a line of `data/raw/<name>/skip.txt` |
| Lyrics with wrong words | put the correct lyrics (one line per line) in `data/raw/<name>/<video id>.txt`, delete `<video id>.lrc`, `vm update` (Whisper only adds timing) |
| One line wrong, or bad timing | edit `data/raw/<name>/<video id>.lrc` by hand (`[mm:ss.xx]text`; a stamp without text ends the line before) |
| Line translations | `vm translate-todo --root R -o todo.txt` → translate the numbered lines in place (keep `number\|`) → `vm translate-import todo.txt --root R` → `vm update --root R` |
| Word glosses | `vm gloss-todo --root R -o gloss.tsv` → fill the `gloss` column → `vm gloss-import gloss.tsv --root R` → `vm update --root R` |
| Translation file by hand | `data/raw/<name>/<video id>.<lang>.lrc` with the same time stamps as the lyrics; never overwritten by the tools |
| Concert setlist | a text file, one title per line, `## Encore` starts a section, `@ Label URL` adds a link button; `vm web --root R --setlist file --file-name x.json` |

After `vm update`, read its last section ("still to do"): it lists the songs to check (`quality.tsv`), lines without
a translation and words without a gloss, with the command for each. Songs graded `check` or `problem` usually came
from Whisper; tell the user rather than guessing lyrics.

When you translate (todo files, glosses): keep each line's number and meaning, translate the line on its own
terms, do not add notes. The target language is in the todo file's header.

## Code tasks

- Pipeline: `Source → Utterance JSONL → Tokenizer → Index (SQLite) → Ranker → vocab → exporters (CSV, Anki, web)`.
  Interfaces: `src/vocab_miner/model.py`, `src/vocab_miner/protocols.py`.
- Plugins are named in the config as `"module.path:ClassName"`; private ones are `private.sources.x:XSource`.
- Language-specific code stays in its own module (`tokenizers/ja.py`, `tokenizers/en.py`); `Token.pos` uses
  Universal POS; language codes are BCP-47 (`ja`, `zh-Hant`, `en`).
- Song collection: `songs.py` (playlists → uploader subtitles → LRCLIB → Whisper → translations from subtitles →
  quality report), `project.py` (`vm new`, `vm update`), `translation_subs.py`, `quality.py`.
- The web app is plain files in `web/` (no build step). Bump `CACHE` in `web/sw.js` on every web change; the page
  shows that version in its top bar. Pushing `web/` to `main` deploys it to GitHub Pages.
- Every source, tokenizer and exporter has tests with fixtures. Code, identifiers and commit messages in English.
- Ask the user before pushing.
