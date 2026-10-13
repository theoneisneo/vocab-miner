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
uv sync --extra ja                        # 日文分詞（fugashi + UniDic）
uv run vm setup-dict                      # 下載 JMdict 英文字典（約 10 MB，CC BY-SA 4.0），只需一次
uv run python scripts/install_hooks.py   # 安裝 pre-commit 檢查（開發者）
```

### 使用方式

**第一次使用？** 請看 [入門教學](docs/getting-started.md)，用附的範例專案走一遍完整流程。


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
| `vocab_miner.sources.subtitle:SubtitleSource` | `.lrc`／`.srt`／`.vtt` | 同名音檔（`song.lrc` + `song.mp3`）會自動當成聲音；`youtube = { "<doc_id>" = "<影片 ID>" }`；雙語字幕 `translations = { "zh-Hant" = "file" / "last-line" / "same-time" }` |
| `LrcSource`／`SrtSource`／`VttSource` | 同上，只讀單一格式 | |

每個 `[[sources]]` 都可以加上框架層級的選項：

- `no_stats_docs = ["<doc_id>", ...]`：這些單位不列入頻率統計，但仍可當例句（例如同一首歌的另一個版本）。
- `add_tags = ["..."]`：替所有句子加上標籤（例如章節，用於劇透過濾）。

3. 產生詞彙表：

   ```bash
   uv run vm vocab                # 全部素材 → out/vocab.csv（實詞）＋ out/grammar.csv（助詞、助動詞）
   uv run vm vocab --doc <doc_id> # 只看一首歌／一個場景的詞，仍依全體頻率排序
   ```

   欄位：學習順序、原形、平假名讀音、拼音、詞性、中文／英文釋義、出現次數、出現在幾個單位、累積覆蓋率、
   素材中的變化形、出現在哪些單位、⚠ 同形異義（漢字和中文相同但意思不同）、學習狀態、例句與中譯、聲音連結。

4. 匯出 Anki 牌組（需要 `uv sync --extra anki`）：

   ```bash
   uv run vm anki                 # → out/vocab.apkg，在 Anki／AnkiDroid 匯入
   ```

   每個詞一張卡：正面是單字與讀音，背面是拼音、中文釋義、同形異義警告、注音假名例句（目標詞加粗）、
   例句拼音與中譯、聽這一句的連結。新卡依學習順序出現，已學會的詞不放進去。
   卡片有固定的 ID，詞彙表更新後重新匯入只會更新內容，不會重複，也不會清掉複習紀錄。

   - **拼音輔助模式**：還看不懂假名時，設定 `[anki] romaji_front = true`（或 `vm anki --romaji-front`），
     卡片正面會同時顯示拼音。假名熟了之後關掉、重新匯出，正面就只剩日文，複習紀錄保留。
   - **五十音牌組**：`uv run vm kana` → `out/kana.apkg`。平假名、片假名各一個子牌組，依五十音表一行一行排
     （清音 → 濁音 → 拗音）。正面出現假名時會唸出來；背面有拼音、**字源**（例如 あ 來自「安」，對中文母語者很好記）、
     素材中含這個假名的常用詞，以及它在你的素材裡出現的次數。
   - **發音**：卡片用 Anki 內建的語音合成（`{{tts ja_JP:…}}`）唸出單字和例句，唸的是素材裡的讀法。
     手機需要有日文語音（Android：設定 → 文字轉語音 → 下載日文語音資料）。

5. 跟唱網頁（手機可安裝的 PWA，程式在 `web/`）：

   ```bash
   uv run vm web                  # → out/web/songs.json（含你的素材，只存在本機）
   ```

   網頁本身不含任何素材，可以放在任何 HTTPS 靜態網站（例如這個 repo 的 GitHub Pages）。
   在手機的 Chrome 打開網址 →「加到主畫面」→ 在 app 裡「匯入資料檔」選 `songs.json`。資料只存在手機上，離線也能看歌詞。

   - 每句顯示原文（漢字上標假名）、拼音、中譯，三者都可以切換。
   - 點一句：影片從這一句開始播；播放時目前這句會高亮並自動捲動。單句重複、0.75／0.5 倍速。
   - 點一個詞：顯示讀音、釋義、同形異義警告，可標記「已學會」；生詞有底線，學會後消失。
   - 歌曲清單依「已懂比例」排序，最容易的排最上面。
   - 選單可匯出已學會的詞，放到電腦的 `data/known/ja.txt` 就會同步到詞彙表和 Anki。

   本機預覽：`uv run python -m http.server 8765`，打開 `http://localhost:8765/web/`。

詞彙表的細節：

- **讀音校正**：素材本身附讀音時（例如歌詞的注音假名，`Utterance.reading_hint`），會用它校正分詞器的讀音，
  所以歌詞特有的讀法（例如把「時間」唱成 とき）會照素材顯示。
- **名詞保護**：字典不認得的自創名詞（角色名、地名）會被切碎。寫進 `data/names/<source_id>.txt`（一行一個）即可保護；
  `uv run vm names <source_id>` 會列出被切碎的片假名候選。
- **中文釋義**：開源的日中字典很少，所以中文釋義放在你自己的 `data/gloss/ja-zh.tsv`。
  `uv run vm gloss-todo -o todo.tsv` 列出還沒有釋義的詞（照學習順序），填好 gloss 欄後用 `uv run vm gloss-import todo.tsv` 匯入。
  匯入只會新增、不會覆蓋，所以你手動改過的釋義永遠不會被蓋掉。同形同音但詞性不同的詞，用 `pos` 欄區分。
- **文法詞分開**：助詞（の、は、が…）和助動詞（だ、た、ない…）適合從例句學，不適合做單字卡，
  所以預設另外輸出到 `out/grammar.csv`，詞彙表與覆蓋率只算實詞。設定 `[vocab] include_grammar = true` 可合併。
- **已學會的詞**：寫進 `data/known/ja.txt`（一行一個），詞彙表的 status 欄會標成 known；`ja.learning.txt` 標成 learning。

### 接上自己的素材

`Utterance` JSONL 是對外的契約：用任何方式產生符合格式的 JSONL（欄位見 [docs/architecture.md](docs/architecture.md)），就能使用後面整條流程。

也可以自己寫 source：一個有 `source_id` 屬性和 `utterances()` 方法的類別，在設定檔用 `plugin = "your.module:YourSource"` 指定即可。專案根目錄下的模組都能載入。

遊戲素材可以從遊戲本身的文字取得，或錄下自己的遊玩過程再用 Whisper 轉寫。

### 授權與版權

- 程式碼以 [MIT 授權](LICENSE) 釋出。
- 你必須有權使用自己放進來的素材。本 repo 不包含任何第三方文字；由素材產生的語料、詞彙表和卡片只存在本機的 `data/` 與 `out/`，不會進版控。
- 英文釋義來自 [JMdict](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project)（© Electronic Dictionary Research and Development Group，[CC BY-SA 4.0](https://www.edrdg.org/edrdg/licence.html)）。字典檔由 `vm setup-dict` 下載，不包含在本 repo。若你**公開分享**含有這些英文釋義的詞彙表或 Anki 牌組，需標註 JMdict 出處並以相同授權分享；自己使用則不受影響。

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

A step-by-step walkthrough with a runnable example project (in Traditional Chinese): [docs/getting-started.md](docs/getting-started.md).


```bash
uv sync --extra ja
uv run vm setup-dict                       # JMdict English glosses (one time, ~10 MB)
cp config.example.toml config.local.toml   # then list your material under [[sources]]
uv run vm ingest                           # -> data/corpus/<source_id>.jsonl
uv run vm vocab                            # -> out/vocab.csv, out/grammar.csv
uv run vm anki                             # -> out/vocab.apkg (needs: uv sync --extra anki)
uv run vm kana                             # -> out/kana.apkg: kana ordered by frequency in your material
uv run vm web                              # -> out/web/songs.json for the sing-along app in web/
```

`web/` is a static, installable sing-along page (no build step, no material inside): host it on any HTTPS static
site, open it on your phone, and import `songs.json`; the data stays on the device. Lines show furigana, romaji and
translation; tapping a line plays the video from that moment; tapping a word shows its gloss and lets you mark it
known.

Particles and auxiliaries go to a separate `out/grammar.csv` by default. The vocabulary list ranks lemmas by how many docs (songs, scenes) they appear in, then by count, with cumulative
coverage, readings, Hepburn romaji, glosses (JMdict for English; your own editable TSV for other languages —
`vm gloss-todo` / `vm gloss-import`), false-friend warnings for Chinese speakers, learning status from
`data/known/<lang>.txt`, and an example sentence with translation and audio link. When a source ships its own
readings (e.g. furigana), they correct the tokenizer's readings. Protect invented names with
`data/names/<source_id>.txt` (`vm names <source_id>` suggests candidates).

Built-in sources: `TextSource` (plain text), `SubtitleSource` / `LrcSource` / `SrtSource` / `VttSource` (timed text; a same-named audio file next to the subtitle is picked up as media). Any `[[sources]]` block also accepts `no_stats_docs` (keep out of frequency stats, still usable as examples) and `add_tags`.

The `Utterance` JSONL format is the public contract — produce it any way you like and the rest of the pipeline works. Custom sources are plain classes loaded by `"module.path:ClassName"`. See [docs/architecture.md](docs/architecture.md).

You are responsible for having the right to use the material you feed in. This repository ships no third-party text.

Code: [MIT](LICENSE). English glosses come from [JMdict](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project)
(© EDRDG, [CC BY-SA 4.0](https://www.edrdg.org/edrdg/licence.html)), downloaded by `vm setup-dict` and not included here;
if you share vocabulary lists or decks containing them, credit JMdict and share them under the same license.
