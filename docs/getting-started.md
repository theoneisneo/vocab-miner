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
- `english.csv`：日文素材裡直接用英文寫的詞（歌詞常見），不算進日文的排序和覆蓋率。

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
3. 點一首歌：
   - 最上面的「**這首先學這 10 個詞**」列出這首歌裡最值得先學的生詞（依你所有歌裡的出現頻率排序）。開始跟唱前先看一遍。
   - 工具列第一排是「單句重複」「速度」「跟隨」；第二排是顯示設定（假名、拼音、中文、逐詞、結構、解說），設定好可以按「顯示 ▴」收起來。
   - 速度按鈕往右滑快 0.25 倍、往左滑慢 0.25 倍；點一下依序切換選單「播放速度設定」裡勾選的速度。
   - 點一句播放（有聲音時）；點一個詞看讀音和釋義。每次查詢都會記下次數，首頁會列出「你最常查的詞」。
   - 確定記住的詞可以在詞卡上標記「已學會」，它就不會再出現在生詞清單裡。
   - 首頁每份資料分「全部」和「★最愛」。「全部」依專輯分組（見第 12 節的播放清單檔），也可以切換成依已懂比例排序；
     在歌曲旁或歌曲頁上方點 ☆ 加入最愛。「最愛」裡按「排列」，用 ↑ ↓ 調整順序、加上可命名的分隔線。
4. 看不懂句子結構時，打開工具列的「逐詞」（每個詞底下標拼音和短釋義）和「結構」（助詞、動詞、時態用不同顏色）。
   日文的動詞在句尾、助詞貼在詞的後面標示角色，所以先找句尾的綠色動詞，再看藍色助詞，最容易對上翻譯。
5. 沒有 YouTube 影片（例如範例專案），或想離線練習：在歌曲頁點「選擇手機裡的影片／音檔來播放」，
   選一個和字幕時間軸對得上的檔案。檔案只存在手機上，下次打開還在。
6. 可以匯入好幾個資料檔（在設定檔用 `[web] title = "名稱"` 或 `vm web --title 名稱` 取名）；同名的會更新，不同名的會分組並列。

7. **看不懂翻譯時問 AI**：每句右邊的「問」會把這句的原文、讀音、逐詞意思、前後句和翻譯整理成一個問題，
   手機上用分享選單交給 Claude、ChatGPT 等 app，電腦上複製到剪貼簿再貼到 AI app。詞卡上也有「問 AI 這個詞」。
   選單「問 AI 的方式」可以改成一律複製，或直接開網頁版並填好問題（實驗性，取決於網站是否支援）。

8. **不用電腦也能加歌**：選單「建立歌曲…」（或首頁的「在這裡建立一首歌」）。貼上歌詞和 YouTube 連結，
   影片播放時每唱到新的一句就點一下，再逐句微調時間；可以按「問 AI 翻譯整首」把翻譯貼回來。
   網頁會在手機上分詞（第一次需要下載日文分詞器），建立的歌曲放在「我建立的歌曲」。
   這是選用功能，限制和移除方式見 [web/create/README.md](../web/create/README.md)。

想用自己的程式產生資料檔，格式見 [web-data-format.md](web-data-format.md)。

## 12. 每句的解說（選用）

想把「為什麼這樣翻」先寫好、離線也能看，可以為一首歌產生解說：

```bash
uv run vm explain-todo --doc morning -o explain.jsonl   # 每句一行：原文、讀音、逐詞、翻譯、前後句
# 填寫每行的 "explanation"（自己寫，或交給 AI 起草再檢查）
uv run vm explain-import explain.jsonl                  # 存進 data/explain/<source_id>.jsonl（只新增、不覆蓋）
uv run vm web                                           # 重新產生 songs.json
```

跟唱網頁的工具列會出現「解說」開關（預設關閉），打開後每句下面有可以展開的解說。

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

**把資料檔同步到手機**：在設定檔加上下面兩行，`vm web` 每次產生資料檔後會自動多複製一份到指定資料夾
（例如和 Google Drive、Dropbox 同步的資料夾，手機上直接從雲端開檔匯入）：

```toml
[web]
file_name = "my_songs.json"            # 複製出去的檔名（預設 songs.json）
copy_to = ["D:/CloudDrive/vocab"]      # 可以寫好幾個資料夾；資料夾不存在時會略過並提醒
```

## 12. 從 YouTube 播放清單開始

跟唱網頁播的是 YouTube 影片，所以「一個播放清單」很適合當收集素材的起點。（yt-dlp 已包含在依賴裡，`uv sync` 就會裝好。YouTube 改版後若抓不到，`uv lock --upgrade-package yt-dlp` 更新它。）

```bash
uv run vm yt-list "https://www.youtube.com/playlist?list=..." -o data/raw/youtube/mylist.tsv   # 影片清單（不下載任何東西）
uv run vm yt-subs data/raw/youtube/mylist.tsv                                                  # 下載字幕 -> data/raw/youtube/subs/<影片ID>.vtt
```

- `yt-subs` 只下載上傳者提供的字幕軌，不下載影片；已下載的會跳過，每支影片之間停 3 秒。
  也接受網址、影片 ID，或一行一個網址的文字檔。
- 結果寫在 `subs/report.tsv`：`subtitles`（上傳者的字幕）、`auto-available`（只有自動產生的字幕，加 `--auto` 才下載；
  辨識歌聲常常出錯）、`none`（沒有字幕，之後可以用 Whisper 轉寫）。
- 檔名就是影片 ID，在 source 的 `youtube` 選項裡把它對到同一支影片，每句就能跳到影片的對應時間。
- 請只把下載的字幕用在自己的學習，不要散布。

**專輯分組**：把用到的播放清單寫成一個檔（例如 `data/playlists.txt`），一行一個「語言 | 專輯 | 播放清單網址」，
專輯寫 `-` 表示只是歌曲來源、不當成專輯：

```
ja | 第一張 EP | https://www.youtube.com/playlist?list=...
en | -         | https://www.youtube.com/playlist?list=...
```

```bash
uv run vm yt-playlists data/playlists.txt      # 存下每個清單的影片表（data/raw/youtube/<清單ID>.tsv）
```

設定 `[web] playlists = "data/playlists.txt"` 後，`vm web` 會依影片 ID 或歌名把歌曲分到專輯（每首只放在第一張收錄它的專輯），
網頁首頁的「全部」就會依專輯分組。

**同一首歌的其他語言版本**（例如原曲和英文版）：寫一份對照表，表頭是語言代碼，一行一首歌：

```
ja	en
朝の雨	Morning Rain
```

`[web] versions = "data/song_pairs.tsv"` 讓網頁顯示另一語言的歌名、可以在兩個版本之間切換；在翻唱版那邊再加
`[web] album_lang = "ja"`，就會照原曲的專輯分組和排序（兩份資料順序相同），翻唱版自己的專輯改成歌名旁的小標籤。歌名寫法不同對不上時，用 `[web] title_aliases = { "清單上的歌名" = "資料裡的歌名" }`。

**連結到串流平台**：每首歌可以有幾個連結按鈕（例如 Spotify）。搜尋連結可以全部自動產生；想要直接開到某首歌，
就在連結表填上那首歌的分享連結（表頭第一欄是歌名，其他欄是按鈕名稱）：

```toml
[web]
artist = "歌手名"
links = "data/song_links.tsv"
search_links = { Spotify = "https://open.spotify.com/search/{artist}%20{title}" }
```

## 13. 沒有時間軸：用 Whisper 產生

需要 `uv sync --extra whisper`（faster-whisper；有 NVIDIA 顯示卡時會用 GPU，第一次會下載約 1.2 GB 的 CUDA 套件和約 3 GB 的模型）。

```bash
uv run vm transcribe data/raw/youtube/mylist.tsv --lyrics data/raw/mylyrics   # YouTube 清單：自動下載音訊
uv run vm transcribe recordings/*.mp4 -o data/raw/transcripts                 # 自己的錄音／錄影
```

- **有歌詞文字、沒有時間軸**：把歌詞存成 `--lyrics` 資料夾裡的 `<影片ID或檔名>.txt`（一行一句）。
  Whisper 只提供時間，每一句都保留你給的文字。
- **完全沒有文字**：用 Whisper 聽寫的結果。歌聲常會聽錯，檔頭會標明是轉寫，請對照原曲修正。
- 結果寫成 `<名稱>.lrc`，可以直接手動修改，再用 `LrcSource` 匯入。已經有 `.lrc`／`.vtt`／`.srt` 的會跳過（`--force` 重做）。
- 一首歌在 RTX 3090 上約 40 秒；沒有 GPU 也能跑，但慢很多（可以用 `--model small` 加快）。
- `--separate`：先用 Demucs 分離人聲再轉寫（`uv sync --extra separate`，會下載約 2.5 GB 的 GPU 版 PyTorch）。
  三首歌的實測，錯字率降低 0～4 個百分點、每首多約 16 秒；適合沒有歌詞、只能靠轉寫的歌。
- Whisper 被指定語言時仍會照它聽到的語言寫；結果明顯不是指定語言時，指令會提醒你（例如影片其實是原文版）。

## 14. 一鍵收集：從播放清單到時間軸歌詞

把第 12、13 節的步驟串起來：

```bash
uv run vm songs data/playlists.txt --lang en -o data/raw/english
```

1. 播放清單檔裡該語言的清單 → 影片表（`vm yt-playlists`）
2. 上傳者提供的字幕（`vm yt-subs`）
3. LRCLIB：社群整理的公開歌詞資料庫，有時間軸的直接用、純文字的存成 `.txt`（`vm yt-lyrics`）
4. Whisper：純文字歌詞補上時間、什麼都沒找到的轉寫（`vm transcribe`；`--no-whisper` 跳過、`--separate` 先分離人聲）
5. 品質報告 `quality.tsv`（`vm quality`）

- 已經有歌詞檔的歌會跳過，同一首歌的不同上傳（MV 和純音樂版）只算一次。
- Prologue、Interlude、Cross Fade 這類不是歌的影片會略過；播放清單裡混了其他語言的版本，把影片 ID 或歌名寫進
  輸出資料夾的 `skip.txt`（一行一個）。
- 輸出資料夾的 `videos.tsv` 是整理過歌名的歌曲清單，設定成 source 的 `video_list`，每句就能連到影片。

**品質報告**：每首歌標成 `ok`（可以直接用）、`check`（建議看一下：AI 轉寫、歌詞在影片結束前很早就停、Whisper 自己
加的「Thanks for watching」）、`problem`（大概有錯：主要不是該語言、歌詞比影片長、幾乎沒有內容）。也可以單獨執行：

```bash
uv run vm quality data/raw/english --lang en
```

## 15. 整句翻譯：你來當「API」

素材沒有附翻譯時，用待辦檔補上：程式整理出還沒翻譯的句子，你用任何方式翻（聊天 AI、翻譯網站、朋友、自己），再匯入。
不需要 API 金鑰。

```bash
uv run vm translate-todo -o todo.txt          # 每首歌一段，「編號|原文」，開頭附翻譯指示
# 把 todo.txt 整份貼給聊天 AI（或自己翻），把回覆整份貼回 todo.txt 存檔
uv run vm translate-import todo.txt           # 逐行檢查後存起來
uv run vm ingest                              # 套用翻譯
```

- 重複的句子（副歌）只列一次。`--doc <id>` 只匯出某首，`--lang` 指定翻譯語言（預設 `zh-Hant`）。
- 匯入時會列出缺漏的句子、多出來的行、沒翻的行；沒翻好的下次 `translate-todo` 會再列出來。
- 翻譯存在 `data/translations/<source_id>.<語言>.tsv`，依「歌曲＋原文」對應：重新對時間或換成更正確的歌詞時，
  沒變的句子不用重翻。素材本身附的翻譯（例如雙語字幕）不會被覆蓋。
- 不要刪掉 `todo.txt` 旁邊的 `todo.txt.keys.json`：匯入時靠它知道每個編號對應哪一句。

## 16. 另一種語言（例如英文）

每種語言用自己的專案資料夾（自己的設定、索引和輸出），跟唱網頁可以同時匯入多份資料。英文需要 `uv sync --extra en`（spaCy）。

`data/en/config.local.toml`：

```toml
data_dir = "."
out_dir = "../../out/en"
target_lang = "en"
gloss_langs = ["zh-Hant"]
romanizer = false

[tokenizer]
plugin = "vocab_miner.tokenizers.en:EnglishTokenizer"

[[dictionaries]]
plugin = "vocab_miner.dictionaries.tsv:TsvGlossDictionary"
path = "gloss/en-zh.tsv"
gloss_lang = "zh-Hant"

[vocab]
exclude_pos = ["PUNCT", "SYM", "NUM", "X", "INTJ"]               # INTJ: la-la-la、oh、yeah
grammar_pos = ["ADP", "PART", "SCONJ", "AUX", "CCONJ", "DET", "PRON"]

[[sources]]
id = "songs/english"
plugin = "vocab_miner.sources.subtitle:SubtitleSource"           # .lrc / .srt / .vtt
path = "../raw/english"
lang = "en"
video_list = "../raw/youtube/mylist.tsv"                         # 檔名是影片 ID：自動連到影片、帶入歌名
```

```bash
uv run vm ingest --root data/en
uv run vm gloss-todo --root data/en -o todo.tsv    # 補中文釋義（gloss 欄；short 欄可填逐詞顯示的短釋）
uv run vm gloss-import todo.tsv --root data/en
uv run vm web --root data/en                       # out/en/web/songs.json，在網頁裡匯入
```

- 分詞會還原詞形（sang → sing、skies → sky），縮寫拆開（I'm → I + be、don't → do + not）。
- 英文歌詞通常沒有中譯；在網頁上按句子旁的「問」，AI 會翻譯並解釋。

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
