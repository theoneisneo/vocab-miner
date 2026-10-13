# vocab-miner

[正體中文](#正體中文) · [English](#english)

---

## 正體中文

從你**正在接觸的素材**（歌曲、遊戲、影片、小說）學語言。

先統計素材裡實際出現的詞，依頻率和覆蓋率決定學習順序；每個詞都附上素材裡的原句當例句，有聲音時還能直接跳到那一句的時間點。

1. 把任何素材轉成句子（`Utterance` JSONL）：純文字、字幕檔（.lrc / .srt / .vtt），或用 Whisper 轉寫自己錄的影片。
2. 分詞、統計、依頻率與覆蓋率排序。
3. 產生詞彙表：讀音、好讀的拼音、釋義，以及從你自己的素材挑出的例句（有聲音時附時間點連結）。
4. 匯出成 CSV 或 Anki。

所有元件都可以替換：素材來源（source）、各語言的分詞器、拼音、字典、排序方式、例句挑選、匯出格式。

**狀態**：開發初期。第一個語言是日文，但架構是多語言的。

### 安裝

需要 Python 3.12+ 與 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run python scripts/install_hooks.py   # 安裝 pre-commit 檢查（開發者）
```

### 使用方式

1. 複製 `config.example.toml` 為 `config.local.toml`（不進版控），在 `[[sources]]` 填入你的素材。
2. 產生語料：

   ```bash
   uv run vm sources   # 列出設定的素材
   uv run vm ingest    # 轉成 data/corpus/<source_id>.jsonl
   uv run vm stats     # 每份語料的句數、翻譯與聲音覆蓋情況
   ```

內建的 source：

| plugin | 用途 | 主要選項 |
|---|---|---|
| `vocab_miner.sources.text:TextSource` | 純文字 `.txt`（單檔或資料夾） | `split = "line"`／`"paragraph"`／`"sentence"` |
| `vocab_miner.sources.subtitle:SubtitleSource` | `.lrc`／`.srt`／`.vtt` | 同名音檔（`song.lrc` + `song.mp3`）會自動當成聲音；`youtube = { "<doc_id>" = "<影片 ID>" }` |
| `LrcSource`／`SrtSource`／`VttSource` | 同上，只讀單一格式 | |

每個 `[[sources]]` 都可以加上框架層級的選項：

- `no_stats_docs = ["<doc_id>", ...]`：這些單位不列入頻率統計，但仍可當例句（例如同一首歌的另一個版本）。
- `add_tags = ["..."]`：替所有句子加上標籤（例如章節，用於劇透過濾）。

### 接上自己的素材

`Utterance` JSONL 是對外的契約：用任何方式產生符合格式的 JSONL（欄位見 [docs/architecture.md](docs/architecture.md)），就能使用後面整條流程。

也可以自己寫 source：一個有 `source_id` 屬性和 `utterances()` 方法的類別，在設定檔用 `plugin = "your.module:YourSource"` 指定即可。專案根目錄下的模組都能載入。

遊戲素材可以從遊戲本身的文字取得，或錄下自己的遊玩過程再用 Whisper 轉寫。

### 版權

你必須有權使用自己放進來的素材。本 repo 不包含任何第三方文字；由素材產生的語料、詞彙表和卡片只存在本機的 `data/` 與 `out/`，不會進版控。

---

## English

Learn a language from the media you are actually consuming — songs, games, shows, books.

1. Turn any material into sentences (`Utterance` JSONL): plain text, subtitle files (.lrc/.srt/.vtt), or Whisper transcriptions of your own recordings.
2. Tokenize, count, and rank words by frequency and coverage.
3. Get a vocabulary list with readings, learner-friendly romanization, glosses, and example sentences picked from your own material — with a link to the exact moment in the audio when available.
4. Export to CSV or Anki.

Everything is pluggable: sources, tokenizers (per language), romanizers, dictionaries, rankers, example selectors, exporters.

**Status:** early development. Japanese first; designed for multiple languages.

### Quick start

```bash
uv sync
cp config.example.toml config.local.toml   # then list your material under [[sources]]
uv run vm ingest                           # -> data/corpus/<source_id>.jsonl
uv run vm stats
```

Built-in sources: `TextSource` (plain text), `SubtitleSource` / `LrcSource` / `SrtSource` / `VttSource` (timed text; a same-named audio file next to the subtitle is picked up as media). Any `[[sources]]` block also accepts `no_stats_docs` (keep out of frequency stats, still usable as examples) and `add_tags`.

The `Utterance` JSONL format is the public contract — produce it any way you like and the rest of the pipeline works. Custom sources are plain classes loaded by `"module.path:ClassName"`. See [docs/architecture.md](docs/architecture.md).

You are responsible for having the right to use the material you feed in. This repository ships no third-party text.
