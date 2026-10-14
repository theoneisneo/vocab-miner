# 入門教學：從一首歌到單字卡和跟唱網頁

這份教學用 repo 裡附的範例專案 `examples/demo/` 走一遍完整流程。範例裡的兩首短歌詞是為這份教學寫的，可以放心使用。
跑完之後，把範例換成你自己的素材，就是你自己的學習流程。

整個流程：

```
你的素材（字幕檔、歌詞、純文字）
   │  vm ingest            轉成統一格式的句子（Utterance JSONL）
   ▼
data/corpus/*.jsonl
   │  vm vocab             分詞、統計頻率、排出學習順序、查釋義、挑例句
   ▼
out/vocab.csv、out/grammar.csv
   │  vm anki / vm kana    單字卡、五十音卡（Anki）
   │  vm web               跟唱網頁的資料檔
   ▼
手機：AnkiDroid ＋ 跟唱網頁
```

---

## 1. 安裝

需要 Python 3.12 以上和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/theoneisneo/vocab-miner.git
cd vocab-miner
uv sync --extra ja --extra anki     # 日文分詞（fugashi + UniDic）與 Anki 匯出
uv run vm setup-dict                # 下載 JMdict 英文字典，約 10 MB，只需一次
```

## 2. 準備素材

範例的素材放在 `examples/demo/`：

```
examples/demo/
  config.toml                 設定檔
  lyrics/morning.lrc          歌詞（LRC，有時間軸）
  lyrics/morning.zh-Hant.lrc  它的中文翻譯（獨立檔案，用時間對應）
  scenes/night.srt            雙語字幕（每段第一行日文、最後一行中文）
```

支援的素材格式：

| 格式 | 說明 | 設定的 plugin |
|---|---|---|
| `.txt` | 純文字，一行一句（也可以按段落或句號切） | `vocab_miner.sources.text:TextSource` |
| `.lrc` | 歌詞，有時間軸 | `vocab_miner.sources.subtitle:SubtitleSource` |
| `.srt`／`.vtt` | 字幕，有時間軸 | 同上 |
| 其他 | 自己寫一個 source，輸出 `Utterance` JSONL（格式見 [architecture.md](architecture.md)） | 你自己的 `module:Class` |

### 翻譯怎麼放

有翻譯的話，例句卡和跟唱網頁都會顯示。三種常見的放法都支援，在設定檔用 `translations` 指定：

| 寫法 | 檔案長相 | 設定 |
|---|---|---|
| 獨立翻譯檔 | `song.lrc` 旁邊放 `song.zh-Hant.lrc`，時間相同（差 0.3 秒內也算） | `translations = { "zh-Hant" = "file" }` |
| 每段最後一行 | 雙語 `.srt`：一段裡第一行原文、最後一行翻譯 | `translations = { "zh-Hant" = "last-line" }` |
| 同時間的下一行 | 雙語 `.lrc`：原文和翻譯用同一個時間標籤，翻譯在後 | `translations = { "zh-Hant" = "same-time" }` |

`song.zh-Hant.lrc` 這種檔名（主檔名後面接語言代碼）會被當成翻譯檔，不會被當成另一首歌。

### 聲音：點一句就播放

- **本機音檔**：把 `song.mp3`（或 m4a、wav、mp4…）放在 `song.lrc` 旁邊，同名就會自動配對。
- **YouTube**：在設定檔加 `youtube = { "morning" = "影片ID" }`，`morning` 是檔名（不含副檔名），影片 ID 是網址 `watch?v=` 後面那一串。
  時間軸要和那支影片對得上，所以要用你對時間軸時參考的同一支影片。

範例沒有附聲音（沒有適合公開的影片），所以範例的跟唱網頁不會有播放器，其他功能都一樣。

## 3. 設定檔

範例的 [examples/demo/config.toml](../examples/demo/config.toml) 有兩個素材：

```toml
[[sources]]
id = "demo/songs"                                   # 素材的名稱，輸出檔名也用它
plugin = "vocab_miner.sources.subtitle:SubtitleSource"
path = "lyrics"                                     # 檔案或資料夾，相對於設定檔所在位置
lang = "ja"
translations = { "zh-Hant" = "file" }
```

你自己的專案：把 `config.example.toml` 複製成 `config.local.toml`（不會進 git），在 `[[sources]]` 填你的素材。
下面的指令在範例裡都加了 `--root examples/demo`；在你自己的專案根目錄執行時不用加。

## 4. 轉成句子：`vm ingest`

```bash
uv run vm ingest --root examples/demo
uv run vm stats  --root examples/demo
```

```
demo/songs: 8 utterances in 1 docs -> examples/demo/data/corpus/demo/songs.jsonl
demo/scenes: 4 utterances in 1 docs -> examples/demo/data/corpus/demo/scenes.jsonl
demo/songs.jsonl     8 utt   1 docs   8 translated   0 with media   0 no-stats
```

`stats` 可以檢查翻譯和聲音有沒有接上：「translated」應該等於句數；有設定聲音的話「with media」也一樣。

## 5. 詞彙表：`vm vocab`

```bash
uv run vm vocab --root examples/demo
```

```
39 words -> examples/demo/out/vocab.csv (39 without a Chinese gloss)
12 grammar words -> examples/demo/out/grammar.csv (12 without a Chinese gloss)
```

- `vocab.csv`：實詞（名詞、動詞、形容詞…），依「出現在幾首歌 → 總次數」排序，越上面越值得先學。用 Excel 可以直接開。
- `grammar.csv`：助詞（の、は、が…）、助動詞（だ、た…）、〜ている 這類句型。它們最常出現，但適合從例句學，所以分開放。

欄位說明：學習順序、原形、平假名讀音、拼音、詞性、中文／英文釋義、次數、出現在幾首、**累積覆蓋率**
（學到這個詞為止，能看懂素材裡多少比例的詞）、變化形、出現在哪些歌、⚠ 同形異義（漢字和中文相同但意思不同）、學習狀態、例句與中譯、聲音連結。

要看單一首歌的生詞（仍依全體頻率排序）：`uv run vm vocab --doc morning`。

## 6. 中文釋義：`vm gloss-todo` → 填寫 → `vm gloss-import`

英文釋義由 JMdict 自動提供。開源的日中字典很少，所以中文釋義放在你自己的檔案 `data/gloss/ja-zh.tsv`：

```bash
uv run vm gloss-todo --root examples/demo -o todo.tsv
```

`todo.tsv` 依學習順序列出還沒有中文釋義的詞，附上詞性、英文釋義和例句當參考。在 `gloss` 欄填上中文
（自己填，或交給 AI 起草再自己檢查），然後：

```bash
uv run vm gloss-import todo.tsv --root examples/demo
uv run vm vocab --root examples/demo
```

匯入**只會新增，不會覆蓋**：已經在 `ja-zh.tsv` 裡的詞不會被改掉，所以你直接修改那個檔案也很安全。
同形同音但詞性不同的詞（例如助動詞 ない 和形容詞 ない），用 `pos` 欄區分。

## 7. Anki 單字卡：`vm anki`

```bash
uv run vm anki --root examples/demo     # → out/vocab.apkg
```

在手機安裝 AnkiDroid（電腦用 Anki），匯入 `.apkg`。

- 新卡依學習順序出現；已學會的詞不放進去（見第 10 節）。
- 正面：單字和讀音；背面：拼音、中文釋義、注音假名的例句（目標詞加粗）、例句中譯、聽這一句的連結。
- **還看不懂假名時**：範例設定了 `[anki] romaji_front = true`，卡片正面會加上拼音。假名熟了改成 `false`、重新匯出、再匯入，
  正面就只剩日文，複習紀錄會保留。
- 詞彙表更新後重新匯入，只會更新卡片內容，不會出現重複的卡。

## 8. 五十音卡：`vm kana`

```bash
uv run vm kana --root examples/demo     # → out/kana.apkg
```

平假名、片假名各一個子牌組，依五十音表一行一行排（あいうえお、かきくけこ…，再來濁音、拗音）。
同一行子音相同、母音固定是 a-i-u-e-o，比打散的順序好記。

- 正面出現假名時會**唸出來**（AnkiDroid 也有重播按鈕）。
- 背面有拼音、**字源**（平假名是整個漢字的草書，例如 あ ← 安；片假名取漢字的一部分，例如 イ ← 伊），
  素材中含這個假名的常用詞，以及它在你的素材裡出現的次數。

**發音**：單字卡和五十音卡都用 Anki 內建的語音合成。手機要有日文語音：Android 到「設定 → 文字轉語音」
確認引擎是 Google，並下載日文語音資料。單字卡唸的是讀音（例如素材附的注音），所以會照歌詞的讀法唸。

## 9. 跟唱網頁：`vm web`

```bash
uv run vm web --root examples/demo      # → out/web/songs.json
```

網頁本身在 repo 的 `web/`，不含任何素材，可以放在任何 HTTPS 靜態網站（這個 repo 用 GitHub Pages：
`.github/workflows/pages.yml` 會發佈 `web/`）。

1. 手機 Chrome 打開網頁 → 選單「加到主畫面」或「安裝應用程式」。
2. 把 `songs.json` 傳到手機，在網頁裡「匯入資料檔」。資料只存在手機上，離線也能看。
3. 點一首歌：每句有注音假名、拼音、中譯（都可以開關）；點一句播放（有聲音時）；點一個詞看釋義、標記「已學會」。
4. 看不懂句子結構時，打開工具列的「逐詞」（每個詞底下標拼音和短釋義）和「結構」（助詞、動詞、時態用不同顏色）。
   日文的動詞在句尾、助詞貼在詞的後面標示角色，所以先找句尾的綠色動詞，再看藍色助詞，最容易對上翻譯。
5. 沒有 YouTube 影片（例如範例專案），或想離線練習：在歌曲頁點「選擇手機裡的影片／音檔來播放」，
   選一個和字幕時間軸對得上的檔案。檔案只存在手機上，下次打開還在。
6. 可以匯入好幾個資料檔（在設定檔用 `[web] title = "名稱"` 或 `vm web --title 名稱` 取名）；同名的會更新，不同名的會分組並列。

想用自己的程式產生資料檔，格式見 [web-data-format.md](web-data-format.md)。

在電腦上預覽：`uv run python -m http.server 5180`，打開 `http://localhost:5180/web/`（Windows 會保留部分 port，若無法啟動就換一個號碼）。

## 10. 已學會的詞

- 在跟唱網頁標記「已學會」，再從選單「匯出已學會的詞」，把檔案存成 `data/known/ja.txt`（一行一個詞）。
- 也可以直接編輯 `data/known/ja.txt`。`ja.learning.txt` 則標成「學習中」。
- 之後重新執行 `vm vocab`／`vm anki`／`vm web`，詞彙表的 status 欄、Anki 牌組、網頁的生詞底線都會跟著更新。

## 11. 加新素材的日常流程

```bash
# 把新的字幕／歌詞放進素材資料夾，然後：
uv run vm ingest
uv run vm gloss-todo -o todo.tsv     # 補新詞的中文釋義
uv run vm gloss-import todo.tsv
uv run vm anki                       # 重新匯入 AnkiDroid（只會新增和更新）
uv run vm web                        # 在網頁裡「更新資料」
```

索引只會重新處理有變動的素材，所以素材變多也不會越跑越慢。

---

## 常見狀況

**讀音不是歌詞裡唱的讀法**（例如範例的「明日」顯示 あす，但歌詞通常唱 あした）
分詞器沒有上下文時用字典的預設讀法。素材本身附有讀音（`Utterance.reading_hint`，例如歌詞的注音假名）時，
會用它自動校正；一般的 `.lrc`／`.srt` 沒有讀音資訊，所以會出現這種情況。

**角色名、地名被切成奇怪的片段**
字典不認得的自創名詞會被切碎。執行 `uv run vm names <source_id>` 列出可疑的片假名，把真正的名字寫進
`data/names/<source_id>.txt`（一行一個），再執行 `vm vocab` 就會被當成一個專有名詞。

**同一首歌有兩個版本**（例如現場版）
在該素材的設定加 `no_stats_docs = ["檔名"]`：那個版本不列入頻率統計，但仍可以當例句。

**換行把一句話切成兩半**
字幕裡的換行會被當成排版、合併成一句；純文字可以用 `split = "paragraph"` 或 `"sentence"` 調整。

**想從零重新建索引**：`uv run vm build --force`。
