/* Optional feature: create a song in the browser (no computer, no server).
 *
 *   1. paste lyrics (plain lines, or LRC with [mm:ss.xx] times) and a YouTube link
 *   2. tap "next line" while the video plays to time each line, then nudge by ±0.1 s
 *   3. optionally ask an AI app to translate and paste the result back
 *   4. the lyrics are tokenized in the browser (Japanese: kuromoji.js, downloaded on first use) and saved as a
 *      normal data file ("我建立的歌曲") in the same format `vm web` produces
 *
 * Self-contained on purpose: the main app only loads this file when the user opens it, and talks to it through
 * the `api` object passed to openCreate(). To remove the feature, set FEATURES.create = false in app.js (or
 * delete this folder and the few lines marked "optional feature" there). Songs already created stay usable.
 */

const DATASET_TITLE = "我建立的歌曲";
const KUROMOJI = "https://cdn.jsdelivr.net/npm/kuromoji@0.1.2/build/kuromoji.js";
const KUROMOJI_DICT = "https://cdn.jsdelivr.net/npm/kuromoji@0.1.2/dict/";
const TAP_LAG = 0.15;          // people tap a little after the line starts
const LANGS = { ja: "日文" };  // a tokenizer per language; others can be added here

let api, panel, state;

export function openCreate(appApi) {
  api = appApi;
  ensureCss();
  state = { title: "", youtube: "", lang: "ja", lines: [], times: [], translations: [] };
  panel = api.el("div", { class: "create-panel", role: "dialog", "aria-modal": "true" });
  document.body.append(panel);
  document.body.classList.add("create-open");
  stepInput();
}

function close() {
  stopPlayer();
  panel?.remove();
  document.body.classList.remove("create-open");
  api.refresh();                       // the app stopped its own player when this opened
}

function ensureCss() {
  if (document.querySelector("link[data-create-css]")) return;
  document.head.append(api.el("link", { rel: "stylesheet", href: new URL("create.css", import.meta.url).href,
    "data-create-css": "" }));
}

function screen(title, ...body) {
  const el = api.el;
  panel.replaceChildren(el("div", { class: "create-card" },
    el("div", { class: "create-head" },
      el("h2", {}, title),
      el("button", { class: "icon-btn", "aria-label": "關閉", onclick: () => { if (confirm("離開建立歌曲？尚未儲存的內容會消失。")) close(); } }, "✕")),
    ...body));
  panel.scrollTop = 0;
}

// ---------- step 1: lyrics and link ----------

const LRC_TAG = /^\s*((?:\[\d+:\d{1,2}(?:[.:]\d{1,3})?\])+)(.*)$/;

function parseLyrics(text) {
  const lines = [], times = [];
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const m = raw.match(LRC_TAG);
    if (m) {
      const body = m[2].trim();
      if (!body) continue;
      const t = m[1].match(/\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]/);
      lines.push(body);
      times.push(Number(t[1]) * 60 + Number(t[2]) + (t[3] ? Number(t[3]) / 10 ** t[3].length : 0));
    } else if (raw.trim() && !/^\s*\[[a-z]+:/i.test(raw)) {
      lines.push(raw.trim());
      times.push(null);
    }
  }
  return { lines, times };
}

function youtubeId(text) {
  const m = (text || "").match(/(?:v=|youtu\.be\/|embed\/|shorts\/|live\/)([\w-]{11})/) || (text || "").match(/^([\w-]{11})$/);
  return m ? m[1] : "";
}

function stepInput() {
  const el = api.el;
  const title = el("input", { class: "create-input", placeholder: "歌名", value: state.title });
  const link = el("input", { class: "create-input", placeholder: "YouTube 連結（可留空）", value: state.youtube });
  const lang = el("select", { class: "create-input" },
    Object.entries(LANGS).map(([k, v]) => el("option", { value: k, selected: k === state.lang }, v)));
  const lyrics = el("textarea", { class: "create-text", placeholder: "貼上歌詞，一行一句。\n已經有時間軸的 LRC（[00:12.34]歌詞）也可以直接貼。" },
    state.lines.map((l, i) => (state.times[i] != null ? `[${fmtLrc(state.times[i])}]${l}` : l)).join("\n"));
  const next = el("button", { class: "primary", onclick: () => {
    const parsed = parseLyrics(lyrics.value);
    if (!parsed.lines.length) return api.toast("請貼上歌詞");
    const id = youtubeId(link.value.trim());
    if (link.value.trim() && !id) return api.toast("看不出 YouTube 影片 ID，請貼完整的影片網址");
    Object.assign(state, { title: title.value.trim() || parsed.lines[0].slice(0, 20), youtube: id,
      lang: lang.value, lines: parsed.lines, times: parsed.times,
      translations: state.translations.length === parsed.lines.length ? state.translations : [] });
    const timed = parsed.times.every((t) => t !== null);
    if (timed) stepAdjust();
    else if (id) stepTap();
    else stepTranslate();
  } }, "下一步");
  screen("建立歌曲 1／3：歌詞",
    el("p", { class: "hint" }, "歌詞請貼你有權使用的內容；建立的歌曲只存在這個裝置上。"),
    el("label", { class: "create-label" }, "歌名", title),
    el("label", { class: "create-label" }, "YouTube 連結", link),
    el("label", { class: "create-label" }, "語言", lang),
    el("label", { class: "create-label" }, "歌詞", lyrics),
    el("p", { class: "hint" }, "沒有時間軸、但有影片：下一步邊聽邊點來標時間。沒有影片：略過時間，只做閱讀用。"),
    next);
}

// ---------- step 2a: tap to time each line ----------

let player = null;

function stopPlayer() {
  if (player) try { player.destroy(); } catch { /* gone */ }
  player = null;
}

async function mountPlayer(host) {
  stopPlayer();
  const box = api.el("div", { id: "create-yt" });
  host.replaceChildren(box);
  try {
    await api.loadYouTubeApi();
  } catch {
    host.replaceChildren(api.el("p", { class: "hint" }, "離線中：影片無法載入。"));
    return null;
  }
  return new Promise((resolve) => {
    player = new YT.Player("create-yt", {
      videoId: state.youtube,
      playerVars: { playsinline: 1, rel: 0, modestbranding: 1 },
      events: { onReady: () => resolve(player) },
    });
  });
}

function stepTap() {
  const el = api.el;
  const n = state.lines.length;
  let i = 0;
  const times = new Array(n).fill(null);
  const host = el("div", { class: "create-player" });
  const counter = el("div", { class: "tap-counter" });
  const current = el("div", { class: "tap-current" });
  const upcoming = el("div", { class: "tap-next" });
  const tap = el("button", { class: "primary tap-btn" }, "▶ 開始，第一句唱出來時點這裡");
  const back = el("button", { class: "secondary" }, "↶ 退回一句");
  const show = () => {
    counter.textContent = `第 ${Math.min(i + 1, n)} ／ ${n} 句`;
    current.textContent = i < n ? state.lines[i] : "（全部標完了）";
    upcoming.textContent = i + 1 < n ? `下一句：${state.lines[i + 1]}` : "";
    tap.textContent = i === 0 && times[0] === null ? "▶ 開始，第一句唱出來時點這裡" : i < n ? "這一句開始了 ⏎" : "完成";
  };
  tap.addEventListener("click", async () => {
    if (!player) return;
    if (i === 0 && times[0] === null && player.getPlayerState() !== YT.PlayerState.PLAYING) {
      player.playVideo();
      tap.textContent = "第一句唱出來時點這裡";
      return;
    }
    if (i < n) {
      times[i] = Math.max(0, Math.round((player.getCurrentTime() - TAP_LAG) * 100) / 100);
      i++;
      show();
      if (i === n) {
        state.times = times;
        state.lastEnd = Math.round(player.getCurrentTime() * 100) / 100 + 4;
      }
    } else {
      player.pauseVideo();
      stepAdjust();
    }
  });
  back.addEventListener("click", () => {
    if (i === 0) return;
    i--;
    times[i] = null;
    if (player) player.seekTo(Math.max(0, (times[i - 1] ?? 0) - 1), true);
    show();
  });
  screen("建立歌曲 2／3：標時間",
    host,
    el("p", { class: "hint" }, "播放影片，每一句開始唱的時候點一下大按鈕（也可以按鍵盤 Enter）。點錯了就退回一句。"),
    counter, current, upcoming, tap, back,
    el("button", { class: "link-btn", onclick: () => { stopPlayer(); stepInput(); } }, "‹ 回上一步"));
  show();
  mountPlayer(host);
  const onKey = (ev) => {
    if (!document.body.contains(tap)) return document.removeEventListener("keydown", onKey);
    if (ev.key === "Enter") { ev.preventDefault(); tap.click(); }
  };
  document.addEventListener("keydown", onKey);
}

// ---------- step 2b: check and nudge the times ----------

function fmtLrc(t) {
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
}

function stepAdjust() {
  const el = api.el;
  const host = el("div", { class: "create-player" });
  const rows = state.lines.map((line, i) => {
    const time = el("span", { class: "adj-time" }, fmtLrc(state.times[i] ?? 0));
    const nudge = (d) => {
      state.times[i] = Math.max(0, Math.round(((state.times[i] ?? 0) + d) * 100) / 100);
      time.textContent = fmtLrc(state.times[i]);
    };
    const play = () => {
      if (!player) return;
      player.seekTo(state.times[i] ?? 0, true);
      player.playVideo();
    };
    return el("li", { class: "adj-row" },
      el("button", { class: "secondary adj-play", "aria-label": "從這句播放", onclick: play }, "▶"),
      time,
      el("button", { class: "secondary adj-nudge", onclick: () => nudge(-0.1) }, "−0.1"),
      el("button", { class: "secondary adj-nudge", onclick: () => nudge(0.1) }, "+0.1"),
      el("span", { class: "adj-line" }, line));
  });
  screen("建立歌曲 2／3：檢查時間",
    state.youtube ? host : null,
    el("p", { class: "hint" }, "點 ▶ 從那句開始聽，太早或太晚就用 ±0.1 秒調整。"),
    el("ol", { class: "adj-list" }, rows),
    el("button", { class: "primary", onclick: () => { stopPlayer(); stepTranslate(); } }, "下一步"),
    state.youtube ? el("button", { class: "link-btn", onclick: () => { stopPlayer(); stepTap(); } }, "重新標時間") : null);
  if (state.youtube) mountPlayer(host);
}

// ---------- step 3: translation ----------

function translatePrompt() {
  return [
    `請把下面的${LANGS[state.lang] || ""}歌詞逐行翻譯成繁體中文。`,
    `每一行原文輸出一行翻譯，行數必須和原文相同（共 ${state.lines.length} 行），不要加編號、原文或其他說明。`,
    "",
    ...state.lines,
  ].join("\n");
}

function stepTranslate() {
  const el = api.el;
  const area = el("textarea", { class: "create-text", placeholder: "把 AI 的翻譯貼在這裡，一行對一句。" },
    state.translations.join("\n"));
  const status = el("p", { class: "hint" });
  const check = () => {
    const got = area.value.replace(/\r\n?/g, "\n").split("\n").filter((l) => l.trim()).length;
    status.textContent = area.value.trim() ? `翻譯 ${got} 行／歌詞 ${state.lines.length} 句${got === state.lines.length ? " ✓" : "（行數不同時會依順序對應）"}` : "";
  };
  area.addEventListener("input", check);
  screen("建立歌曲 3／3：翻譯（可略過）",
    el("p", { class: "hint" }, "按下面的按鈕，把整首歌詞交給你的 AI app 翻譯，再把結果貼回來。不需要翻譯也可以直接完成。"),
    el("button", { class: "secondary", onclick: () => api.askAI(translatePrompt()) }, "問 AI 翻譯整首"),
    area, status,
    el("button", { class: "primary", onclick: () => {
      state.translations = area.value.replace(/\r\n?/g, "\n").split("\n").filter((l) => l.trim()).map((l) => l.trim());
      finish();
    } }, "完成並建立"),
    el("button", { class: "link-btn", onclick: () => stepInput() }, "‹ 回到歌詞"));
  check();
}

// ---------- tokenizing (Japanese) ----------

let tokenizerPromise = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (window.kuromoji) return resolve();
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error("無法下載分詞器（需要網路）"));
    document.head.append(s);
  });
}

function japaneseTokenizer() {
  if (!tokenizerPromise) {
    tokenizerPromise = loadScript(KUROMOJI).then(() => new Promise((resolve, reject) => {
      window.kuromoji.builder({ dicPath: KUROMOJI_DICT }).build((err, t) => (err ? reject(err) : resolve(t)));
    })).catch((err) => { tokenizerPromise = null; throw err; });
  }
  return tokenizerPromise;
}

const KANA = /^[ぁ-ゖァ-ヺー]+$/;
const HAS_KANJI = /[㐀-鿿豈-﫿々〆ヶ]/;
const hira = (s) => s.replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));

/** IPADIC part of speech -> Universal POS (same roles the page colours). */
function upos(t, prev) {
  const p1 = t.pos, p2 = t.pos_detail_1;
  if (p1 === "名詞") {
    if (p2 === "固有名詞") return "PROPN";
    if (p2 === "数") return "NUM";
    if (p2 === "代名詞") return "PRON";
    if (p2 === "形容動詞語幹") return "ADJ";
    return "NOUN";
  }
  if (p1 === "動詞") return p2 === "非自立" && prev && /^[てで]$/.test(prev.surface_form) ? "AUX" : "VERB";
  if (p1 === "形容詞") return p2 === "非自立" && prev && /^[てで]$/.test(prev.surface_form) ? "AUX" : "ADJ";
  if (p1 === "助詞") return p2 === "接続助詞" ? "SCONJ" : p2 === "終助詞" ? "PART" : "ADP";
  return { 助動詞: "AUX", 副詞: "ADV", 連体詞: "DET", 接続詞: "CCONJ", 感動詞: "INTJ", 記号: "PUNCT",
    接頭詞: "NOUN", フィラー: "INTJ" }[p1] || "X";
}

/** 食べ/たべ -> [[食,た],[べ,null]] : ruby only over the kanji. */
function splitOkurigana(surface, reading) {
  const runs = surface.match(/[ぁ-ゖァ-ヺー]+|[^ぁ-ゖァ-ヺー]+/g) || [surface];
  const esc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp("^" + runs.map((r) => (KANA.test(r) ? `(${esc(hira(r))})` : "(.+?)")).join("") + "$");
  const m = hira(reading).match(pattern);
  if (!m) return [[surface, reading]];
  return runs.map((r, k) => [r, HAS_KANJI.test(r) ? m[k + 1] : null]);
}

// Hepburn, same rules as the Python romanizer: shi/chi/tsu/fu/ji, n' before vowels, long vowels as written
const BLOCK = ("a a i i u u e e o o ka ga ki gi ku gu ke ge ko go sa za shi ji su zu se ze so zo ta da chi ji - tsu zu te de "
  + "to do na ni nu ne no ha ba pa hi bi pi fu bu pu he be pe ho bo po ma mi mu me mo ya ya yu yu yo yo "
  + "ra ri ru re ro wa wa i e o n vu ka ke").split(" ");
const MONO = Object.fromEntries(BLOCK.map((r, i) => [String.fromCharCode(0x3041 + i), r]).filter(([, r]) => r !== "-"));
const SMALL = new Set("ぁぃぅぇぉゃゅょゎ");

function romanize(reading) {
  const s = hira(reading);
  let out = "", geminate = false, afterN = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i], nx = s[i + 1];
    let syl;
    if (c === "っ") { geminate = true; continue; }
    if (c === "ー") { syl = (out.match(/[aeiou](?=[^aeiou]*$)/) || [""])[0]; }
    else if (MONO[c] && nx && SMALL.has(nx) && "ゃゅょ".includes(nx) && MONO[c].endsWith("i") && MONO[c].length > 1) {
      const b = MONO[c].slice(0, -1);
      syl = (["sh", "ch", "j"].includes(b) ? b : b + "y") + MONO[nx].slice(1);
      i++;
    } else if (MONO[c] && nx && "ぁぃぅぇぉ".includes(nx) && !"あえお".includes(c)) {
      const v = MONO[nx];                                               // ティ ti, ファ fa, ウィ wi, イェ ye
      syl = c === "う" ? "w" + v : c === "い" ? "y" + v : MONO[c].replace(/[aeiou]+$/, "") + v;
      i++;
    } else syl = MONO[c] ?? c;
    if (geminate && syl && !"aeioun'".includes(syl[0])) syl = (syl.startsWith("ch") ? "t" : syl[0]) + syl;
    geminate = false;
    if (afterN && /^[aiueoy]/.test(syl)) out += "'";
    afterN = c === "ん";
    out += syl;
  }
  return geminate ? out + "'" : out;
}

/** Words already known from other data files, so created songs reuse their glosses and "known" marks. */
function existingWords() {
  // most specific first: same spelling, reading and part of speech (ない the auxiliary is not ない the adjective)
  const exact = new Map(), byLemmaReading = new Map(), byLemma = new Map();
  const addUnique = (map, k, w) => { if (!map.has(k)) map.set(k, w); else if (map.get(k) !== w) map.set(k, null); };
  for (const ds of api.datasets.values()) {
    for (const w of ds.words) {
      if (!exact.has(`${w.lemma}|${w.reading}|${w.upos}`)) exact.set(`${w.lemma}|${w.reading}|${w.upos}`, w);
      addUnique(byLemmaReading, `${w.lemma}|${w.reading}`, w);
      addUnique(byLemma, w.lemma, w);
    }
  }
  return (lemma, reading, upos) => exact.get(`${lemma}|${reading}|${upos}`)
    || byLemmaReading.get(`${lemma}|${reading}`) || byLemma.get(lemma) || null;
}

async function buildJapanese(words, wordIndex) {
  const tokenizer = await japaneseTokenizer();
  const lookup = existingWords();
  return state.lines.map((text) => {
    const toks = tokenizer.tokenize(text);
    const seg = [], wr = [];
    toks.forEach((t, ti) => {
      const prev = toks[ti - 1];
      const u = upos(t, prev);
      const surface = t.surface_form;
      const reading = t.reading && t.reading !== "*" ? hira(t.reading) : (KANA.test(surface) ? hira(surface) : "");
      let lemma = t.basic_form && t.basic_form !== "*" ? t.basic_form : surface;
      let lemmaReading = surface === lemma ? reading : "";
      if (u === "AUX" && (t.pos === "動詞" || t.pos === "形容詞")) {     // 〜ている, 〜てしまう ... as grammar patterns
        const kana = KANA.test(lemma) ? hira(lemma) : lemmaReading || hira(lemma);
        lemma = `〜て${kana}`;
        lemmaReading = `て${kana}`;
      }
      let wi = null;
      if (u !== "PUNCT" && /[ぁ-ゖァ-ヺー㐀-鿿豈-﫿]/.test(lemma)) {
        const found = lookup(lemma, lemmaReading || reading, u);
        const key = found ? found.key : `${lemma}\t${lemmaReading}`;
        if (!wordIndex.has(key)) {
          wordIndex.set(key, words.length);
          words.push(found ? { ...found } : {
            key, lemma, reading: lemmaReading || "", romaji: lemmaReading ? romanize(lemmaReading) : "",
            pos: t.pos, upos: u, short: "", zh: "", en: "", grammar: ["ADP", "PART", "SCONJ", "AUX"].includes(u),
          });
        }
        wi = wordIndex.get(key);
      }
      const particle = u === "ADP" || u === "PART" ? { は: "wa", へ: "e", を: "o" }[surface] : null;
      wr.push(u === "PUNCT" || !surface.trim() ? "" : particle || (reading ? romanize(reading) : surface));
      if (reading && HAS_KANJI.test(surface)) {
        for (const [piece, ruby] of splitOkurigana(surface, reading)) seg.push([piece, ruby, wi, ti]);
      } else seg.push([surface, null, wi, ti]);
    });
    for (let k = 0; k < wr.length; k++) {                               // small tsu at the end of a token
      if (wr[k].endsWith("'")) {
        const nxt = wr.slice(k + 1).find((x) => x) || "";
        if (/^[b-df-hj-np-tv-z]/.test(nxt)) wr[k] = wr[k].slice(0, -1) + (nxt.startsWith("ch") ? "t" : nxt[0]);
      }
    }
    const romaji = wr.filter((x) => x).join(" ");
    return { seg, wr, romaji };
  });
}

// ---------- finish ----------

async function finish() {
  const el = api.el;
  screen("建立中…", el("p", { class: "hint", id: "create-progress" }, "第一次使用需要下載日文分詞器（約 12 MB），請稍候…"));
  const ds = api.datasets.get(DATASET_TITLE);
  const data = ds ? structuredClone(ds) : {
    format: "vocab-miner-web", version: 1, lang: state.lang, title: DATASET_TITLE,
    generated: new Date().toISOString().slice(0, 19), words: [], docs: [],
  };
  const wordIndex = new Map(data.words.map((w, i) => [w.key, i]));
  let built;
  try {
    if (state.lang !== "ja") throw new Error(`目前只支援：${Object.values(LANGS).join("、")}`);
    built = await buildJapanese(data.words, wordIndex);
  } catch (err) {
    return screen("無法建立", el("p", {}, String(err.message || err)),
      el("button", { class: "primary", onclick: () => stepTranslate() }, "回上一步"));
  }
  const n = state.lines.length;
  const times = state.times;
  const stamp = Date.now().toString(36);
  const doc = {
    id: `created/${stamp}`, title: state.title,
    media: state.youtube ? { kind: "youtube", uri: state.youtube } : null, noStats: false,
    lines: state.lines.map((text, i) => {
      const start = times[i] ?? null;
      const nextStart = times.slice(i + 1).find((t) => t !== null && t !== undefined);
      return {
        id: `created:${stamp}:${i + 1}`,
        start, end: start === null ? null : (nextStart ?? state.lastEnd ?? start + 5),
        seg: built[i].seg, romaji: built[i].romaji, wr: built[i].wr,
        tr: state.translations[i] || "",
      };
    }),
  };
  data.docs.push(doc);
  data.generated = new Date().toISOString().slice(0, 19);
  const problems = api.validate(data);
  if (problems.length) {
    return screen("無法建立", el("ul", {}, problems.map((p) => el("li", {}, p))),
      el("button", { class: "primary", onclick: () => stepInput() }, "回到歌詞"));
  }
  await api.saveDataset(DATASET_TITLE, data);
  close();
  api.toast(`已建立「${doc.title}」（${n} 句）`);
  api.openDoc(DATASET_TITLE, doc.id);
}
