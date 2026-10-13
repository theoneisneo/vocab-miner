# 架構細節

## 1. 資料模型

### Utterance（素材的基本單位）
一句歌詞、一句台詞、一段字幕。所有 source 的輸出都是 Utterance。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | str | 全域唯一，格式 `<source_id>:<local_id>` |
| `source_id` | str | 素材集合，例如 `songs/artist-x`、`game-y/demo` |
| `doc_id` | str | 素材內的單位：一首歌、一個場景。用來計算「出現在幾個素材」 |
| `seq` | int | 在 doc 內的順序 |
| `lang` | str | 原文語言（BCP-47） |
| `text` | str | 原文，已清除控制碼 |
| `translations` | dict[str, str] | 官方或人工翻譯，例如 `{"zh-Hant": ..., "en": ...}` |
| `reading_hint` | str \| None | 素材本身附的讀音或拼音（有就保留，可拿來校正分詞器的讀音） |
| `speaker` | str \| None | 說話者／角色 |
| `media` | MediaRef \| None | 這句話對應的聲音，見下方 |
| `tags` | list[str] | 例如章節 `ch01`，用於劇透過濾。`no-stats`：不列入頻率統計但可當例句（同一素材的另一版本） |

### MediaRef（例句的聲音）
| 欄位 | 說明 |
|---|---|
| `kind` | `youtube` / `file` |
| `uri` | YouTube 影片 ID，或本機檔案路徑 |
| `start`, `end` | 秒數（float）；整個檔案就是一句時可為 None |

渲染規則由 Exporter 決定：
- `youtube` → 連結 `https://www.youtube.com/watch?v=<id>&t=<int(start)>s`；Anki 匯出可選擇用 yt-dlp 在本機切出片段（僅限私人使用）。
- `file` → CSV 給路徑；Anki 匯出用 ffmpeg 切出 `start..end` 的片段放進卡片。

### Token
`surface`、`lemma`、`reading`（日文為平假名）、`pos`（UPOS）、`pos_native`、`start/end`（在 text 中的位置）、`is_proper`、
`base`、`lemma_reading`。

- `lemma` + `lemma_reading` 決定一個詞彙條目（`Token.key`）；同一個詞的各種變化形會合併。
- `reading` 是這個詞**在句中**的讀音，給注音假名用；`lemma_reading` 是原形的讀音，給詞彙表用。
- `base` 是素材裡實際寫法的原形，用來顯示。日文的 UniDic 原形常是罕見漢字（為る、有る），`base` 則是 する、ある。
- 日文分詞器會把可能形（会える）顯示成原形（会う），把古典サ變（信ずる）換成現代寫法（信じる）。

### 讀音校正
Source 提供 `reading_hint`（例如歌詞的注音假名）時，Index 建立時會用它校正 token 的讀音：
假名必須逐字對上，漢字部分在所有可行切法中選「改動的詞最少、和原讀音編輯距離最小」的那一種；對不上就保留原讀音。
只差清濁音的改動（連濁，例如 何気ない 的 気→げ）只改句中讀音，不改原形讀音。

## 2. 例句與聲音：為什麼在建表時才挑

不同素材提供的東西不一樣：

| 素材 | 原句 | 翻譯 | 聲音 |
|---|---|---|---|
| 歌詞網站 | 有 | 逐句中譯 | YouTube 連結 + 時間軸 |
| 遊戲文字表 | 有 | 官方多語言版本 | 不一定（語音檔對應關係要另外找） |
| Whisper 轉寫 | 有 | 無 | 本機音檔 + 時間戳 |
| 純文字 | 有 | 無 | 無 |

所以設計成：
1. **Source 只負責把自己有的東西填進 Utterance**（沒有聲音就 `media=None`）。
2. **Index 記錄每個 lemma 出現在哪些 utterance**（倒排索引）。
3. **ExampleSelector 在產生詞彙表時**，對每個詞從所有候選句裡挑 top-k，評分依序考慮：
   - 有聲音的優先
   - 有翻譯的優先
   - 句中其他生詞越少越好（i+1：只剩這個詞不懂的句子最好學）
   - 長度適中（太長的句子不適合當例句）
   - 來源多樣性（不要全部例句都來自同一首歌）
   - 排除帶有劇透標籤的句子（依設定）

好處：加入新素材後重新建表，例句會自動變好（例如某個詞原本只有純文字例句，加了 Whisper 轉寫後就有聲音了），不需要改任何素材。

## 3. 詞彙表欄位

使用者要求的欄位：原文、中文、英文字母拼音、頻率。建議完整欄位：

| 欄位 | 範例 | 說明 |
|---|---|---|
| `rank` | 12 | 學習順序 |
| `lemma` | 食べる | 原形（字典形） |
| `reading` | たべる | 平假名讀音。學假名期間和拼音並列，之後可隱藏拼音 |
| `romaji` | taberu | 見下方規則 |
| `pos` | 動詞 | 中文詞性名稱 |
| `gloss_zh` | 吃 | 中文釋義 |
| `gloss_en` | to eat | 英文釋義（字典來源） |
| `count` | 37 | 總出現次數 |
| `doc_freq` | 9 | 出現在幾個素材單位（幾首歌／幾個場景）。比 count 更能反映「到處都會遇到」 |
| `coverage` | 41.2% | 學到這個詞為止，累積能涵蓋素材多少比例的詞 |
| `forms` | 食べて、食べた | 素材中實際出現的變化形 |
| `docs` | 歌A、歌C | 出現在哪些素材 |
| `false_friend` | ⚠ | 漢字和中文同形但意思不同（例如 勉強＝讀書、手紙＝信、大丈夫＝沒問題）。對中文母語者特別重要 |
| `jlpt` | N4 | 參考用難度等級（非官方清單） |
| `status` | new / learning / known | 使用者自己的學習狀態，來自 `data/known/<lang>.txt` |
| `examples` | （連到例句） | ExampleSelector 挑出的例句 ID，匯出時渲染成原句＋翻譯＋聲音連結 |

### 拼音規則（給不會音標的使用者）
用**黑本式（Hepburn）**：它本來就是為英語使用者設計的，拼法最接近英文直覺（し=shi、ち=chi、つ=tsu、ふ=fu、じ=ji）。
- 不用長音符號（ō），長音照假名寫（とうきょう → toukyou），讓拼音和假名一一對應，方便同時學假名。
- 助詞照發音：は→wa、へ→e、を→o。
- 候選實作：`cutlet`（建立在 fugashi 上，處理助詞和長音）。拼音規則做成 Romanizer 的設定。

### 釋義的來源
多個 Dictionary 依序查詢，每種語言取第一個有結果的。
1. 英文：JMdict（EDRDG，CC BY-SA 4.0）。字典檔用 `vm setup-dict` 下載，不放進 repo；第一次使用時轉成 `.cache/dict/jmdict.sqlite`。
   查詢時優先：寫法相符 > 讀音相符 > 詞性相符 > 常用詞；只有讀音相同的同音詞不算。
2. 中文：開源的日中字典很少，所以用使用者自己的 `data/gloss/ja-zh.tsv`（`lemma, reading, gloss, origin, pos`）。
   - `vm gloss-todo` 依學習順序列出還沒有釋義的詞（含英文釋義和例句當參考），可交給 LLM 或自己填，再用 `vm gloss-import` 匯入。
   - LLM 產生的草稿標為 `origin=machine`。匯入只新增、從不覆蓋，所以使用者改過的釋義不會被蓋掉。
   - `pos`（UPOS，選填）用來區分同形同音但詞性不同的詞（例如助動詞 ない 和形容詞 ない）。
3. 同形異義（false friend）：漢字和中文相同但意思不同的詞，清單在 `src/vocab_miner/data/false_friends_ja_zh.tsv`，在詞彙表裡用 ⚠ 標示。

## 4. 進度與指標（M4）

- **已知詞覆蓋率**：對一首新歌／一段新台詞，已知詞佔多少比例。用來挑「下一首學什麼」：選新詞最少的。
- **學習曲線**：學完 N 首後，下一首的已知比例。
- i+1 ranker：貪婪地選「加入已知集合後，使最多句子變成只剩 ≤1 個生詞」的詞。類似 set cover。

## 5. 目錄

```
src/vocab_miner/
  model.py         資料模型（dataclass）+ JSONL 讀寫
  protocols.py     Source / Tokenizer / Romanizer / Dictionary / Ranker / ExampleSelector / Exporter
  config.py        讀 config.toml + config.local.toml，載入外掛
  index.py         SQLite 索引
  cli.py           typer CLI：ingest / build / vocab / export / stats
  sources/         text.py, subtitle.py (lrc/srt/vtt), whisper.py
  tokenizers/      ja.py, ...
  export/          csv.py, anki.py, html.py
private/           （gitignored）私人 source、fixture、舊腳本
data/              （gitignored）corpus/ names/ known/ gloss/ media/
out/               （gitignored）產出的詞彙表與卡片
```
