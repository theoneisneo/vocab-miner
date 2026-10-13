# vocab-miner

從「自己正在接觸的素材」（歌曲、遊戲、影片、小說）建立語言學習用的詞彙表和例句卡。
核心想法：先統計素材裡實際出現的詞，依頻率和覆蓋率決定學習順序，每個詞都附上素材裡的原句與原音當例句。

目前第一個目標語言是日文，但框架必須是**多語言**的：語言相關的東西（分詞、讀音、字典）全部透過介面接入。

> 個人學習目標、私人素材的取得方式與路徑，寫在 `CLAUDE.local.md`（不進版控）。開工前先讀它。

## 公開與私人的界線（最重要的規則）

這個 repo 會公開。素材本身多半有版權，取得方式也不公開。

- **公開（進 git）**：框架、資料模型、通用 source（純文字、字幕檔、Whisper 轉寫）、分詞、排序、匯出、測試。
- **私人（不進 git）**：`private/`、`data/`、`out/`、`.cache/`、`config.local.toml`、`CLAUDE.local.md`。
  - 任何針對特定網站或特定遊戲的抓取/解析程式，一律放 `private/sources/`。
  - 任何素材原文（歌詞、台詞、字幕）、由素材產生的詞彙表和卡片，一律只存在 `data/` 或 `out/`。
- 公開的程式碼、文件、commit message、測試資料裡**不得出現**：特定遊戲或歌曲的原文、私人 source 的實作細節、取得素材用的工具名稱。
- 測試只用 `tests/fixtures/` 裡自己寫的或公版的文字。
- `scripts/check_no_corpus.py` 是 pre-commit 檢查，不要繞過它；它擋下東西時，修正內容而不是放寬規則。

不確定某樣東西該放哪邊時，放 `private/`，然後問使用者。

## 架構

```
Source ──▶ Utterance (JSONL) ──▶ Tokenizer ──▶ Index (SQLite) ──▶ Ranker ──▶ VocabEntry
                                                    │                            │
                                                    └──▶ ExampleSelector ◀───────┘
                                                                  │
                                                              Exporter (CSV / Anki / HTML)
```

1. **Source**：把任何素材轉成 `Utterance`，寫成 `data/corpus/<source_id>.jsonl`。這個 JSONL 格式是對外的契約：別人用任何方式產生符合格式的 JSONL，就能使用後面整條流程。
2. **Tokenizer**：依語言切詞，產出 `Token`（含原形、讀音、詞性）。
3. **Index**：`.cache/index.sqlite`，存 utterance、token、lemma 出現位置（倒排索引 lemma → utterance）。所有統計和例句查詢都從這裡做。
4. **Ranker**：決定學習順序。先做頻率排序，之後做 i+1（每次挑「學了能讓最多句子只剩 ≤1 個生詞」的詞）。
5. **ExampleSelector**：為每個詞**在建表時**從索引挑例句，不把例句寫死在素材裡（理由見 docs/architecture.md）。
6. **Exporter**：輸出詞彙表與學習卡。

詳細的資料模型、詞彙表欄位、例句與媒體連結設計：`docs/architecture.md`。介面定義：`src/vocab_miner/model.py`、`src/vocab_miner/protocols.py`。

### 外掛載入
Source / Tokenizer / Exporter 等都用 `"module.path:ClassName"` 字串在設定檔指定，框架用 importlib 載入。私人 source 就是 `private.sources.xxx:XxxSource`，和公開的 source 地位相同。

## 多語言原則

- 語言相關的實作放在各自模組：`tokenizers/ja.py`（fugashi + UniDic）、之後的 `zh.py`、`ko.py`、空白分詞語言等。
- `Token.pos` 統一用 Universal POS（UPOS）；各語言原生的詞性放 `pos_native`。
- 讀音與拼音轉寫（`Romanizer`）、字典（`Dictionary`）也是可替換的介面。
- 語言代碼用 BCP-47（`ja`、`zh-Hant`、`en`）。

## 開發約定

- Python 3.12+，用 **uv** 管理（`uv sync`、`uv run ...`）。
- 使用者的主要環境是 **Windows 11 + PowerShell 7**。
  - 所有檔案讀寫明確指定 `encoding="utf-8"`；給 Excel 開的 CSV 用 `utf-8-sig`。
  - 產生 `.ps1` 時只用 ASCII，或確保用 `pwsh` 執行（Windows PowerShell 5.1 會把無 BOM 的 UTF-8 讀成亂碼）。
  - 路徑一律用 `pathlib`。
- CLI 入口：`uv run vm <command>`（typer）。
- 測試：`uv run pytest`。每個 source / tokenizer / exporter 都要有用 fixture 的測試。
- 回覆使用者用繁體中文；程式碼、識別字、commit message 用英文。

## 里程碑

依使用者的時程排序（細節見 CLAUDE.local.md）：

- **M1 骨架**：資料模型、設定檔、外掛載入、`TextSource`、`LrcSource`/`SrtSource`、JSONL 讀寫、pre-commit 檢查。
- **M2 詞彙表**：日文 tokenizer、Index、FrequencyRanker、讀音與拼音、字典釋義、CSV 詞彙表（欄位見 architecture.md）。
- **M3 例句與卡片**：ExampleSelector、媒體連結（YouTube 時間戳、本地音檔片段）、Anki 匯出。
- **M4 進度追蹤**：已學詞清單、覆蓋率曲線、i+1 ranker、「下一首/下一段學什麼」建議。
- **M5 Whisper**：`WhisperSource`（faster-whisper，本機 GPU），含時間戳與音檔切割。
- 之後：更多語言、HTML 詞彙頁。

## 已知的坑

- 字典不認得的自創名詞（遊戲角色名、地名）會被切碎成無意義的片段。需要使用者可編輯的名詞清單（`data/names/<source>.txt`），在分詞前保護起來，並可從片假名連續字串自動產生候選清單。
- 素材裡的換行（`\r\n`）多半只是排版，不是句子邊界。
- 有些素材附帶控制碼（`<...>`、`{0}`、`[...]`），要在 source 階段清掉。
- 多語言版本的同一份素材，通常可以用共同的 ID 對齊成翻譯對照。
