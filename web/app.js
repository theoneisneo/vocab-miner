/* Sing-along: reads vocab-miner data files (vm web) kept on this device. No data leaves the device. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const view = $("#view");
const DOCS_URL = "https://github.com/theoneisneo/vocab-miner/blob/main/docs/";

// ---------- storage ----------
const DB_NAME = "vocab-miner", STORE = "kv";

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function kvGet(key) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const r = db.transaction(STORE).objectStore(STORE).get(key);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
async function kvSet(key, value) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
async function kvDel(key) {
  const db = await idb();
  return new Promise((resolve) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(key);
    tx.oncomplete = () => resolve();
  });
}
async function kvKeys() {
  const db = await idb();
  return new Promise((resolve) => {
    const r = db.transaction(STORE).objectStore(STORE).getAllKeys();
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => resolve([]);
  });
}

const PREFS_KEY = "vm.prefs";
const ALL_RATES = [2, 1.75, 1.5, 1.25, 1, 0.75, 0.5, 0.25];
const prefs = Object.assign({ ruby: true, romaji: true, tr: true, gloss: false, struct: false, ex: false,
  follow: true, loop: false, rate: 1, rates: [1, 0.75, 0.5, 0.25], ask: "auto", showDisplay: true, lessonOpen: true },
  safeJson(localStorageGet(PREFS_KEY)));
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }
function safeJson(s) { try { return JSON.parse(s) || {}; } catch { return {}; } }
function savePrefs() { localStorageSet(PREFS_KEY, JSON.stringify(prefs)); }

// ---------- state ----------
let datasets = new Map();   // dataset id -> imported data file
let data = null;            // the dataset of the song being shown
let known = new Map();      // word key -> true/false (overrides status from the data files; shared by all datasets)
let lookups = new Map();    // word key -> how many times the word card was opened (words you keep checking)
let player = null, ticker = null, currentLine = -1, loopLine = -1;

function isKnown(w) {
  return known.has(w.key) ? known.get(w.key) : w.status === "known";
}
async function setKnown(w, value) {
  known.set(w.key, value);
  await kvSet("known", Object.fromEntries(known));
}
const saveDatasets = () => kvSet("datasets", Object.fromEntries(datasets));

// ---------- optional features ----------
// Each lives in its own folder and is loaded only when opened. To switch one off, set it to false;
// to remove it, also delete its folder. Data it created stays usable (it uses the normal data file format).
const FEATURES = { create: true };   // web/create/: create a song in the browser

/** The only interface optional features get to the app. */
function featureApi() {
  return {
    el, toast, dialog, askAI, loadYouTubeApi, validate,
    get datasets() { return datasets; },
    async saveDataset(id, d) { datasets.set(id, d); await saveDatasets(); },
    openDoc(dsId, docId) { location.hash = `#/doc/${encodeURIComponent(dsId)}/${encodeURIComponent(docId)}`; route(); },
    refresh: () => route(),
  };
}

async function openFeature(name) {
  stopPlayer();
  try {
    if (name === "create") (await import("./create/create.js")).openCreate(featureApi());
  } catch (err) {
    dialog("無法開啟這個功能", el("p", {}, "需要網路才能第一次載入。"), el("p", { class: "hint" }, String(err.message || err)));
  }
}

// ---------- helpers ----------
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) e.append(c);
  return e;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3000);
}
/** A message that stays until dismissed (errors, settings). */
function dialog(title, ...body) {
  const box = $("#dialog");
  const close = () => { box.hidden = true; };
  const hasAction = body.some((b) => b instanceof Element && b.matches("button.primary"));
  box.replaceChildren(el("div", { class: "dialog-card" },
    el("h2", {}, title), ...body,
    el("button", { class: hasAction ? "secondary" : "primary", onclick: close }, hasAction ? "取消" : "關閉")));
  box.onclick = (ev) => { if (ev.target === box) close(); };
  box.hidden = false;
}
function fmtTime(s) {
  if (s === null || s === undefined) return "";
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}
function download(name, text) {
  const a = el("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" })), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
const docRoute = (dsId, doc) => `#/doc/${encodeURIComponent(dsId)}/${encodeURIComponent(doc.id)}`;
// local media belongs to the song, not to the data file, so it survives renaming or updating a data file
const mediaKey = (doc) => `media:${doc.id}`;

/** Share of content-word tokens in a doc that are known, and the number of distinct new content words. */
function docStats(ds, doc) {
  let total = 0, ok = 0;
  const fresh = new Set();
  for (const line of doc.lines) for (const s of line.seg) {
    const wi = s[2];
    if (wi === null || wi === undefined) continue;
    const w = ds.words[wi];
    if (!w || w.grammar) continue;
    total++;
    if (isKnown(w)) ok++; else fresh.add(w.key);
  }
  return { pct: total ? Math.round((100 * ok) / total) : 0, fresh: fresh.size };
}

// ---------- validation ----------
/** Problems with an imported file, in plain language; empty when the file can be used. */
function validate(d) {
  const p = [];
  if (!d || typeof d !== "object" || Array.isArray(d)) return ["檔案內容不是一個 JSON 物件。"];
  if (d.format !== "vocab-miner-web") p.push(`format 應該是 "vocab-miner-web"，這個檔案是 ${JSON.stringify(d.format)}。`);
  if (d.version !== 1) p.push(`version 應該是 1，這個檔案是 ${JSON.stringify(d.version)}（可能是較新或較舊的工具產生的）。`);
  if (!Array.isArray(d.words)) p.push("缺少 words 陣列（詞彙清單）。");
  if (!Array.isArray(d.docs) || !d.docs.length) p.push("缺少 docs 陣列，或裡面沒有任何歌曲。");
  if (p.length) return p;
  d.words.forEach((w, i) => {
    if (p.length < 8 && (!w || typeof w.key !== "string" || typeof w.lemma !== "string"))
      p.push(`words[${i}] 需要文字欄位 key 和 lemma。`);
  });
  const ids = new Set();
  d.docs.forEach((doc, i) => {
    if (p.length >= 8) return;
    const where = `docs[${i}]${doc && doc.title ? `（${doc.title}）` : ""}`;
    if (!doc || typeof doc.id !== "string") { p.push(`${where} 需要文字欄位 id。`); return; }
    if (ids.has(doc.id)) p.push(`${where} 的 id 重複：${doc.id}`);
    ids.add(doc.id);
    if (!Array.isArray(doc.lines)) { p.push(`${where} 需要 lines 陣列。`); return; }
    doc.lines.forEach((line, j) => {
      if (p.length >= 8) return;
      if (!line || !Array.isArray(line.seg)) { p.push(`${where} 第 ${j + 1} 句需要 seg 陣列。`); return; }
      for (const s of line.seg) {
        if (!Array.isArray(s) || typeof s[0] !== "string") { p.push(`${where} 第 ${j + 1} 句的 seg 格式不對（每段應為 [文字, 讀音, 詞編號]）。`); return; }
        if (s[2] !== null && s[2] !== undefined && !(Number.isInteger(s[2]) && s[2] >= 0 && s[2] < d.words.length)) {
          p.push(`${where} 第 ${j + 1} 句指到不存在的詞編號 ${s[2]}。`); return;
        }
      }
      for (const k of ["start", "end"]) {
        if (line[k] !== null && line[k] !== undefined && typeof line[k] !== "number") p.push(`${where} 第 ${j + 1} 句的 ${k} 應該是秒數。`);
      }
    });
  });
  return p;
}

// ---------- routing ----------
function route() {
  stopPlayer();
  const m = location.hash.match(/^#\/doc\/([^/]+)\/(.+)$/);
  if (m) {
    const ds = datasets.get(decodeURIComponent(m[1]));
    const doc = ds && ds.docs.find((d) => d.id === decodeURIComponent(m[2]));
    if (doc) return renderDoc(decodeURIComponent(m[1]), ds, doc);
  }
  renderHome();
}
window.addEventListener("hashchange", route);

// ---------- home ----------
function renderHome() {
  renderSeq++;
  $("#title").textContent = "Sing-along";
  $("#back").hidden = true;
  view.replaceChildren();
  if (!datasets.size) {
    view.append(el("div", { class: "empty" },
      el("h2", {}, "還沒有資料"),
      el("p", {}, "這個網頁顯示 vocab-miner 產生的資料檔（songs.json）：歌詞或台詞、讀音、拼音、翻譯和單字釋義。"),
      el("p", {}, "產生資料檔：在電腦上用 vocab-miner 處理你自己的字幕或歌詞，再執行 ", el("code", {}, "uv run vm web"),
        "。步驟見 ", el("a", { href: DOCS_URL + "getting-started.md", target: "_blank", rel: "noopener" }, "入門教學"),
        "；想自己產生檔案，格式見 ", el("a", { href: DOCS_URL + "web-data-format.md", target: "_blank", rel: "noopener" }, "資料檔格式"), "。"),
      el("p", {}, "資料只會存在這個裝置上，不會上傳。"),
      el("button", { class: "primary", onclick: () => $("#file").click() }, "匯入資料檔"),
      FEATURES.create ? el("p", {}, el("button", { class: "secondary", onclick: () => openFeature("create") },
        "或者：在這裡自己建立一首歌")) : null));
    return;
  }
  const often = renderOftenLooked();
  if (often) view.append(often);
  for (const [id, ds] of datasets) {
    const docs = ds.docs.map((d) => ({ d, s: docStats(ds, d) }));
    const main = docs.filter((x) => !x.d.noStats), extra = docs.filter((x) => x.d.noStats);
    const list = (items) => el("ul", { class: "songs" }, items.map(({ d, s }) =>
      el("li", {}, el("a", { class: "song", href: docRoute(id, d) },
        el("div", { class: "song-title" }, d.title, el("div", { class: "song-sub" }, `${d.lines.length} 句 · 生詞 ${s.fresh}`)),
        el("div", { class: "meter" }, `已懂 ${s.pct}%`, el("div", { class: "meter-bar" }, el("span", { style: `width:${s.pct}%` })))))));
    main.sort((a, b) => b.s.pct - a.s.pct || a.s.fresh - b.s.fresh);
    const content = ds.words.filter((w) => !w.grammar);
    view.append(el("section", { class: "dataset" },
      el("div", { class: "dataset-head" },
        el("h2", {}, ds.title || id),
        el("button", { class: "icon-btn small", "aria-label": `移除 ${ds.title || id}`, onclick: () => removeDataset(id) }, "✕")),
      el("div", { class: "section-title" },
        `已學會 ${content.filter(isKnown).length} / ${content.length} 個詞 · 產生於 ${(ds.generated || "").slice(0, 10)} · 越上面越容易學`),
      list(main),
      extra.length ? el("div", { class: "section-title" }, "其他版本（不列入統計）") : null,
      extra.length ? list(extra) : null));
  }
  view.append(el("div", { class: "home-actions" },
    el("button", { class: "secondary", onclick: () => $("#file").click() }, "匯入或更新資料檔（songs.json）"),
    FEATURES.create ? el("button", { class: "secondary", onclick: () => openFeature("create") }, "在這裡建立一首歌") : null,
    el("p", { class: "hint" }, "同名的資料檔會被更新，不同名的會新增在上面；已學會的詞所有資料共用。")));
}

async function removeDataset(id) {
  const ds = datasets.get(id);
  if (!confirm(`移除「${ds.title || id}」？已學會的詞會保留。`)) return;
  datasets.delete(id);
  await saveDatasets();
  const stillUsed = new Set([...datasets.values()].flatMap((d) => d.docs.map((x) => x.id)));
  for (const doc of ds.docs) if (!stillUsed.has(doc.id)) await kvDel(mediaKey(doc));
  route();
}

// ---------- song ----------
let renderSeq = 0;   // a newer render wins when two overlap (renderDoc waits for storage before drawing)

async function renderDoc(dsId, ds, doc) {
  const seq = ++renderSeq;
  data = ds;
  $("#title").textContent = doc.title;
  $("#back").hidden = false;
  view.replaceChildren();
  const root = el("div", { class: "doc" });
  applyPrefClasses(root);

  const local = await kvGet(mediaKey(doc)).catch(() => null);
  if (seq !== renderSeq) return;
  const youtube = doc.media && doc.media.kind === "youtube" ? doc.media.uri : null;
  const timed = doc.lines.some((l) => l.start !== null && l.start !== undefined);
  const stick = el("div", { class: "stick" });             // player + toolbar stay under the top bar
  root.append(stick);
  const playerBox = el("div", { class: "player-wrap" });
  if (local || youtube) stick.append(playerBox);

  const chip = (label, key, onToggle) => el("button", {
    class: "chip", "aria-pressed": String(!!prefs[key]),
    onclick: (ev) => {
      prefs[key] = !prefs[key];
      savePrefs();
      ev.currentTarget.setAttribute("aria-pressed", String(prefs[key]));
      applyPrefClasses(root);
      if (onToggle) onToggle();
    },
  }, label);
  const rateBtn = el("button", { class: "chip rate-chip", "aria-label": "播放速度：左右滑動調整，點一下切換" },
    `‹ ${prefs.rate}× ›`);
  const applyRate = (r) => {
    prefs.rate = r;
    savePrefs();
    rateBtn.textContent = `‹ ${r}× ›`;
    if (player) player.setRate(r);
  };
  swipeable(rateBtn, (dir) => applyRate(stepRate(prefs.rate, dir)), () => applyRate(nextRate(prefs.rate)));
  const playable = !!(local || youtube);
  // row 1: what you press while singing; row 2: how lines are shown (set once, then fold away)
  const displayRow = el("div", { class: "toolbar display-row" + (playable && !prefs.showDisplay ? " collapsed" : "") },
    chip("假名", "ruby"), chip("拼音", "romaji"), chip("中文", "tr"), chip("逐詞", "gloss"), chip("結構", "struct"),
    doc.lines.some((l) => l.ex) ? chip("解說", "ex") : null);
  if (playable) {
    const label = () => (prefs.showDisplay ? "顯示 ▴" : "顯示 ▾");
    const toggle = el("button", { class: "chip toggle-chip", "aria-expanded": String(!!prefs.showDisplay),
      "aria-label": "顯示設定" }, label());
    toggle.addEventListener("click", () => {
      prefs.showDisplay = !prefs.showDisplay;
      savePrefs();
      displayRow.classList.toggle("collapsed", !prefs.showDisplay);
      toggle.textContent = label();
      toggle.setAttribute("aria-expanded", String(prefs.showDisplay));
    });
    stick.append(el("div", { class: "toolbar play-row" },
      chip("單句重複", "loop", () => { loopLine = prefs.loop ? currentLine : -1; }), rateBtn, chip("跟隨", "follow"), toggle));
  }
  stick.append(displayRow);
  stick.append(el("div", { class: "legend" },
    el("span", { class: "role-prt" }, "助詞"), el("span", { class: "role-pred" }, "動詞・形容詞"),
    el("span", { class: "role-aux" }, "時態・否定・句型"), el("span", { class: "legend-note" }, "動詞通常在句尾")));

  if (timed) {
    const pick = () => { $("#media-file").dataset.target = mediaKey(doc); $("#media-file").click(); };
    root.append(el("div", { class: "media-bar" },
      local
        ? [el("span", {}, `本機檔案：${local.name}`),
           el("button", { class: "link-btn", onclick: pick }, "更換"),
           el("button", { class: "link-btn", onclick: async () => { await kvDel(mediaKey(doc)); route(); } }, "移除")]
        : el("button", { class: "link-btn", onclick: pick },
            youtube ? "改用手機裡的影片／音檔播放" : "選擇手機裡的影片／音檔來播放")));
  }

  const lesson = renderLesson(doc);
  if (lesson) root.append(lesson);
  root.append(el("ol", { class: "lines" }, doc.lines.map((line, i) => renderLine(doc, line, i))));
  view.append(root);

  if (local) startLocalPlayer(playerBox, local, doc);
  else if (youtube) startYouTube(playerBox, youtube, doc);
}

function applyPrefClasses(root) {
  root.classList.toggle("hide-ruby", !prefs.ruby);
  root.classList.toggle("hide-romaji", !prefs.romaji);
  root.classList.toggle("hide-tr", !prefs.tr);
  root.classList.toggle("show-gloss", !!prefs.gloss);
  root.classList.toggle("show-struct", !!prefs.struct);
  root.classList.toggle("show-ex", !!prefs.ex);
}

/** Sentence role used for colouring: particles, predicates (verbs/adjectives), auxiliaries (tense, negation...). */
function role(w) {
  if (["ADP", "PART", "SCONJ"].includes(w.upos)) return "prt";
  if (w.upos === "AUX") return "aux";
  if (["VERB", "ADJ"].includes(w.upos)) return "pred";
  return "";
}

/** Short meaning under a word; falls back to the first sense of the gloss for older data files. */
function shortGloss(w) {
  if (w.short !== undefined) return w.short;
  const g = (w.zh || "").replace(/（[^）]*）|\([^)]*\)/g, "").split(/[；;/、，,]/)[0].replace(/^[\s…]+|[\s…]+$/g, "");
  return g.length <= 6 ? g : g.slice(0, 5) + "…";
}

function renderLine(doc, line, i) {
  const jp = el("div", { class: "line-jp" });
  const wr = Array.isArray(line.wr) ? line.wr : [];
  // pieces of one token (or, in older files, of one word) share a block: the text, its romaji and its meaning
  let text = null, group;
  for (const s of line.seg) {
    const [t, ruby, wi = null, ti = null] = s;
    const node = ruby ? el("ruby", {}, t, el("rt", {}, ruby)) : document.createTextNode(t);
    const g = ti !== null ? `t${ti}` : wi !== null ? `w${wi}` : null;
    if (g === null) { text = null; group = undefined; jp.append(node); continue; }
    if (g !== group) {
      group = g;
      const w = wi !== null ? data.words[wi] : null;
      const r = w ? role(w) : "";
      const cls = "w" + (!w ? " plain" : w.grammar ? " grammar" : isKnown(w) ? "" : " new") + (r ? ` role-${r}` : "");
      const block = el("span", { class: cls, "data-w": wi === null ? null : wi });
      text = el("span", { class: "wt" });
      block.append(text);
      if (ti !== null && wr[ti]) block.append(el("span", { class: "wr" }, wr[ti]));
      block.append(el("span", { class: "gl" }, w ? shortGloss(w) : ""));
      if (w) block.addEventListener("click", (ev) => { ev.stopPropagation(); openWord(w, block, doc, i); });
      jp.append(block);
    }
    text.append(node);
  }
  const ask = el("button", { class: "ask-btn", "aria-label": "問 AI 這句為什麼這樣翻", title: "問 AI 這句為什麼這樣翻" }, "問");
  ask.addEventListener("click", (ev) => { ev.stopPropagation(); askAI(linePrompt(doc, i)); });
  const ex = line.ex ? el("details", { class: "line-ex" }, el("summary", {}, "解說"), el("p", {}, line.ex)) : null;
  if (ex) ex.addEventListener("click", (ev) => ev.stopPropagation());
  const li = el("li", { class: "line", "data-i": i },
    el("div", { class: "line-side" },
      line.start !== null && line.start !== undefined ? el("span", { class: "line-time" }, fmtTime(line.start)) : null,
      ask),
    jp,
    line.romaji ? el("div", { class: "line-romaji" + (wr.length ? " has-wr" : "") }, line.romaji) : null,
    line.tr ? el("div", { class: "line-tr" }, line.tr) : null,
    ex);
  li.addEventListener("click", () => playLine(doc, i));
  return li;
}

// ---------- learning this song ----------
const LESSON_SIZE = 10;

/** New content words of a song in learning order, with how often each occurs in the song. */
function songNewWords(doc) {
  const seen = new Map();
  doc.lines.forEach((line, i) => {
    let last;
    for (const s of line.seg) {
      const wi = s[2], ti = s[3] ?? null;
      if (wi === null || wi === undefined) continue;
      const tag = ti !== null ? `t${ti}` : `w${wi}`;
      if (tag === last) continue;                   // pieces of one token count once
      last = tag;
      const w = data.words[wi];
      if (!w || w.grammar || isKnown(w)) continue;
      const e = seen.get(w.key) || { w, n: 0, line: i };
      e.n++;
      seen.set(w.key, e);
    }
  });
  return [...seen.values()].sort((a, b) => (a.w.rank ?? 1e9) - (b.w.rank ?? 1e9));
}

function wordButton(cls, w, extra, onOpen) {
  const b = el("button", { class: cls + (isKnown(w) ? " known" : ""), "data-key": w.key },
    el("span", { class: "lw-lemma" }, w.lemma),
    w.reading && w.reading !== w.lemma ? el("span", { class: "lw-reading" }, w.reading) : null,
    el("span", { class: "lw-gloss" }, shortGloss(w)),
    extra ? el("span", { class: "lw-n" }, extra) : null);
  b.addEventListener("click", (ev) => { ev.stopPropagation(); onOpen(b); });
  return b;
}

/** "Learn these first": the song's most useful new words, before you start singing. */
function renderLesson(doc) {
  const fresh = songNewWords(doc);
  if (!fresh.length) return null;
  const first = fresh.slice(0, LESSON_SIZE);
  const card = el("details", { class: "lesson", open: prefs.lessonOpen !== false },
    el("summary", {}, `這首先學這 ${first.length} 個詞`, el("span", { class: "lesson-sub" }, `（這首共有 ${fresh.length} 個生詞）`)),
    el("div", { class: "lesson-words" },
      first.map(({ w, n, line }) => wordButton("lesson-word", w, `×${n}`, (b) => openWord(w, b, doc, line)))),
    el("p", { class: "hint" }, "依「在你所有歌裡最常出現」排序，學了最划算。點詞看讀音和意思；查過的次數會記下來，常查的就是還沒記住的。"));
  card.addEventListener("toggle", () => { prefs.lessonOpen = card.open; savePrefs(); });
  return card;
}

/** Home: the words opened most often across all data files. */
function renderOftenLooked() {
  const byKey = new Map();
  for (const [, ds] of datasets) for (const w of ds.words) if (!byKey.has(w.key)) byKey.set(w.key, { w, ds });
  const top = [...lookups.entries()].filter(([k, n]) => n > 0 && byKey.has(k))
    .sort((a, b) => b[1] - a[1]).slice(0, 12);
  if (!top.length) return null;
  return el("section", { class: "often" },
    el("div", { class: "section-title" }, "你最常查的詞（還沒記住的）"),
    el("div", { class: "lesson-words" }, top.map(([k, n]) => {
      const { w, ds } = byKey.get(k);
      return wordButton("often-word", w, `查 ${n} 次`, (b) => { data = ds; openWord(w, b); });
    })));
}

// ---------- word sheet ----------
let sheetWord = null, sheetSpan = null, sheetLine = null;
function openWord(w, span, doc, i) {
  sheetWord = w;
  sheetLine = doc ? { doc, i } : null;
  lookups.set(w.key, (lookups.get(w.key) || 0) + 1);
  kvSet("lookups", Object.fromEntries(lookups)).catch(() => {});
  document.querySelectorAll(".w.sel").forEach((e) => e.classList.remove("sel"));
  sheetSpan = span;
  span.classList.add("sel");
  $("#sheet-lemma").textContent = w.lemma;
  $("#sheet-reading").textContent = [w.reading !== w.lemma ? w.reading : "", w.romaji].filter(Boolean).join(" · ");
  $("#sheet-meaning").textContent = w.zh || "（還沒有中文釋義）";
  $("#sheet-ff").hidden = !w.ff;
  $("#sheet-ff").textContent = w.ff ? `⚠ 和中文意思不同：${w.ff}` : "";
  $("#sheet-en").textContent = w.en || "";
  $("#sheet-meta").textContent = (w.grammar
    ? `${w.pos || ""} · 文法詞 · 出現 ${w.count ?? "?"} 次`
    : `${w.pos || ""} · 學習順序 #${w.rank ?? "?"} · 出現在 ${w.docFreq ?? "?"} 首、共 ${w.count ?? "?"} 次`)
    + ` · 你查過 ${lookups.get(w.key)} 次`;
  updateKnownButton();
  $("#sheet").hidden = false;
}
function updateKnownButton() {
  const b = $("#sheet-known");
  const k = isKnown(sheetWord);
  b.textContent = k ? "✓ 已學會（點一下取消）" : "標記為已學會";
  b.classList.toggle("is-known", k);
}
function closeSheet() {
  $("#sheet").hidden = true;
  if (sheetSpan) sheetSpan.classList.remove("sel");
}
$("#sheet-close").addEventListener("click", closeSheet);
$("#sheet-ask").addEventListener("click", () =>
  askAI(wordPrompt(sheetWord, sheetLine && sheetLine.doc, sheetLine && sheetLine.i)));
$("#sheet").addEventListener("click", (ev) => { if (ev.target.id === "sheet") closeSheet(); });
$("#sheet-known").addEventListener("click", async () => {
  await setKnown(sheetWord, !isKnown(sheetWord));
  updateKnownButton();
  const wi = data ? String(data.words.indexOf(sheetWord)) : null;
  if (wi !== null) {
    document.querySelectorAll(`.w[data-w="${wi}"]`).forEach((e) =>
      e.classList.toggle("new", !sheetWord.grammar && !isKnown(sheetWord)));
  }
  document.querySelectorAll(".lesson-word, .often-word").forEach((e) => {
    if (e.dataset.key === sheetWord.key) e.classList.toggle("known", isKnown(sheetWord));
  });
});

// ---------- players ----------
// Both players expose: seek(t), play(), pause(), time(), setRate(r), destroy().

function loadYouTubeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve();
  if (loadYouTubeApi.p) return loadYouTubeApi.p;
  loadYouTubeApi.p = new Promise((resolve, reject) => {
    window.onYouTubeIframeAPIReady = resolve;
    const s = el("script", { src: "https://www.youtube.com/iframe_api" });
    s.onerror = () => { loadYouTubeApi.p = null; reject(new Error("offline")); };
    document.head.append(s);
  });
  return loadYouTubeApi.p;
}

async function startYouTube(box, videoId, doc) {
  const host = el("div", { id: "yt" });
  box.append(el("div", { class: "player" }, host));
  try {
    await loadYouTubeApi();
  } catch {
    host.replaceWith(el("div", { class: "offline-note" }, "離線中：影片無法載入，歌詞仍可閱讀；也可以改用手機裡的檔案。"));
    return;
  }
  if (!document.getElementById("yt")) return;          // navigated away meanwhile
  let ready = false;
  const yt = new YT.Player("yt", {
    videoId,
    playerVars: { playsinline: 1, rel: 0, modestbranding: 1 },
    events: {
      onReady: () => { ready = true; yt.setPlaybackRate(prefs.rate); },
      onStateChange: (e) => { if (e.data === YT.PlayerState.PLAYING) startTicker(doc); else stopTicker(); },
    },
  });
  player = {
    ready: () => ready,
    seek: (t) => yt.seekTo(t, true), play: () => yt.playVideo(), pause: () => yt.pauseVideo(),
    time: () => yt.getCurrentTime(), setRate: (r) => ready && yt.setPlaybackRate(r),
    destroy: () => { try { yt.destroy(); } catch { /* gone */ } },
  };
}

function startLocalPlayer(box, file, doc) {
  const isVideo = (file.type || "").startsWith("video/");
  const url = URL.createObjectURL(file.blob);
  const media = el(isVideo ? "video" : "audio", { src: url, controls: true, playsinline: true, preload: "metadata",
    class: isVideo ? "local-video" : "local-audio" });
  box.append(media);
  media.playbackRate = prefs.rate;
  media.addEventListener("play", () => startTicker(doc));
  media.addEventListener("pause", stopTicker);
  media.addEventListener("ended", stopTicker);
  media.addEventListener("error", () => toast("這個檔案無法播放，請換成 mp3、m4a、mp4 等常見格式"));
  player = {
    ready: () => true,
    seek: (t) => { media.currentTime = t; }, play: () => media.play().catch(() => {}), pause: () => media.pause(),
    time: () => media.currentTime, setRate: (r) => { media.playbackRate = r; },
    destroy: () => { media.pause(); media.removeAttribute("src"); media.load(); URL.revokeObjectURL(url); },
  };
}

function stopPlayer() {
  stopTicker();
  if (player) player.destroy();
  player = null; currentLine = -1; loopLine = -1;
  closeSheet();
}

function playLine(doc, i) {
  const line = doc.lines[i];
  if (!player || !player.ready() || line.start === null || line.start === undefined) return;
  player.seek(line.start);
  player.play();
  setCurrent(i);
  if (prefs.loop) loopLine = i;
}

function startTicker(doc) {
  stopTicker();
  ticker = setInterval(() => {
    if (!player || !player.ready()) return;
    const t = player.time();
    if (prefs.loop && loopLine >= 0) {
      const l = doc.lines[loopLine];
      const end = l.end ?? (l.start + 6);
      if (t >= end - 0.05 || t < l.start - 1) { player.seek(l.start); return; }
    }
    let idx = -1;
    for (let i = 0; i < doc.lines.length; i++) {
      const s = doc.lines[i].start;
      if (s !== null && s !== undefined && s <= t + 0.15) idx = i;
    }
    if (idx !== currentLine) setCurrent(idx);
  }, 150);
}
function stopTicker() { clearInterval(ticker); ticker = null; }

function setCurrent(i) {
  document.querySelector(".line.current")?.classList.remove("current");
  currentLine = i;
  if (prefs.loop && loopLine < 0) loopLine = i;
  const li = document.querySelector(`.line[data-i="${i}"]`);
  if (!li) return;
  li.classList.add("current");
  if (prefs.follow) followLine(li);
}

/** Keep the current line in the upper third of the area below the sticky header, player and toolbar. */
function followLine(li) {
  const stick = document.querySelector(".stick");
  const covered = stick ? stick.getBoundingClientRect().bottom : 0;
  const visible = window.innerHeight - covered;
  const r = li.getBoundingClientRect();
  if (r.top >= covered + visible * 0.15 && r.bottom <= covered + visible * 0.7) return;   // already comfortable
  const top = window.scrollY + r.top - covered - visible / 3;
  window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

// ---------- ask an AI ----------
// No API key and no cost: the question is handed to an AI app the user already has.
// "auto": share sheet on phones (pick Claude, ChatGPT, Gemini ...), clipboard on computers.
const ASK_MODES = {
  auto: "自動：手機用分享選單、電腦複製到剪貼簿",
  copy: "一律複製到剪貼簿",
  chatgpt: "開啟 ChatGPT 網頁並填好問題（實驗性）",
  claude: "開啟 Claude 網頁並填好問題（實驗性）",
};
const ASK_URLS = { chatgpt: "https://chatgpt.com/?q=", claude: "https://claude.ai/new?q=" };

const segText = (line) => line.seg.map((s) => s[0]).join("");
const segReading = (line) => line.seg.map((s) => s[1] || s[0]).join("");

/** "誰＝誰／の＝的／帰れ＝回去 ..." for the words of a line. */
function lineWords(line) {
  const out = [];
  let group;
  for (const s of line.seg) {
    const [t, , wi = null, ti = null] = s;
    const g = ti !== null ? `t${ti}` : wi !== null ? `w${wi}` : null;
    if (g === null) { group = undefined; continue; }
    if (g === group) { out[out.length - 1].text += t; continue; }
    group = g;
    out.push({ text: t, w: wi !== null ? data.words[wi] : null });
  }
  return out.filter((x) => x.w).map((x) => `${x.text}＝${shortGloss(x.w) || x.w.lemma}`).join("／");
}

function linePrompt(doc, i) {
  const line = doc.lines[i];
  const prev = doc.lines[i - 1], next = doc.lines[i + 1];
  return [
    "我在學日文，請用繁體中文解釋這句歌詞為什麼這樣翻譯。",
    `歌曲：${doc.title}`,
    `原文：${segText(line)}`,
    `讀音：${segReading(line)}${line.romaji ? `（${line.romaji}）` : ""}`,
    `逐詞：${lineWords(line)}`,
    prev ? `前一句：${segText(prev)}` : null,
    next ? `後一句：${segText(next)}` : null,
    `現有翻譯：${line.tr || "（沒有）"}`,
    "請說明：1. 句子結構（動詞在哪、助詞的作用） 2. 逐字直譯 3. 翻譯哪裡是意譯、為什麼 4. 值得記住的文法",
  ].filter(Boolean).join("\n");
}

function wordPrompt(w, doc, i) {
  const line = doc && doc.lines[i];
  return [
    `我在學日文，請用繁體中文解釋「${w.lemma}${w.reading && w.reading !== w.lemma ? `（${w.reading}）` : ""}」這個詞。`,
    line ? `出現的句子：${segText(line)}` : null,
    line && line.tr ? `句子翻譯：${line.tr}` : null,
    w.zh ? `字典意思：${w.zh}` : null,
    w.en ? `英文：${w.en}` : null,
    "請說明：1. 它在這句裡的意思 2. 這裡是什麼變化形（如果有） 3. 常見用法和兩三個簡單例句",
  ].filter(Boolean).join("\n");
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = el("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

const isPhone = () => matchMedia("(pointer: coarse)").matches && !!navigator.share;

async function askAI(text) {
  const mode = prefs.ask || "auto";
  if (mode === "chatgpt" || mode === "claude") {
    await copyText(text);                       // in case the site ignores the prefilled question
    window.open(ASK_URLS[mode] + encodeURIComponent(text), "_blank", "noopener");
    return;
  }
  if (mode === "auto" && isPhone()) {
    try {
      await navigator.share({ text });
      return;
    } catch (err) {
      if (err && err.name === "AbortError") return;   // the user closed the share sheet
    }
  }
  if (await copyText(text)) toast("問題已複製，貼到你的 AI app（Ctrl+V／⌘V）");
  else dialog("請手動複製", el("textarea", { class: "ask-text", readonly: true }, text));
}

function openAskSettings() {
  const current = prefs.ask || "auto";
  const options = Object.entries(ASK_MODES).map(([k, label]) =>
    el("label", { class: "ask-option" },
      el("input", { type: "radio", name: "ask-mode", value: k, checked: k === current }), ` ${label}`));
  const save = el("button", { class: "primary", onclick: () => {
    const picked = document.querySelector('#dialog input[name="ask-mode"]:checked');
    prefs.ask = picked ? picked.value : "auto";
    savePrefs();
    $("#dialog").hidden = true;
    toast(`問 AI：${ASK_MODES[prefs.ask]}`);
  } }, "儲存");
  dialog("問 AI 的方式",
    el("p", { class: "hint" }, "每句的「問」按鈕和詞卡的「問這個詞」會把整理好的問題交給你手邊的 AI app，不需要 API 金鑰、不花錢。"),
    el("div", { class: "ask-options" }, options), save);
}

// ---------- playback speed ----------
function rateCycle() {
  const r = (Array.isArray(prefs.rates) ? prefs.rates : []).filter((x) => ALL_RATES.includes(x));
  return (r.length ? r : [1]).slice().sort((a, b) => b - a);
}
/** Next speed in the user's cycle, going down and wrapping to the fastest: 1 → 0.75 → 0.5 → 0.25 → 1. */
function nextRate(current) {
  const cycle = rateCycle();
  const i = cycle.indexOf(current);
  return i < 0 ? (cycle.includes(1) ? 1 : cycle[0]) : cycle[(i + 1) % cycle.length];
}
/** Swipe right: 0.25x faster, swipe left: slower; wraps around between 0.25x and 2x. */
function stepRate(current, dir) {
  const min = 0.25, max = 2;
  let r = Math.round((current + 0.25 * dir) * 100) / 100;
  if (r > max) r = min;
  if (r < min) r = max;
  return r;
}

/** Horizontal swipe calls onSwipe(+1 / -1); a tap (or Enter/Space) calls onTap; arrow keys call onSwipe. */
function swipeable(node, onSwipe, onTap) {
  let x0 = null;
  node.addEventListener("pointerdown", (ev) => { x0 = ev.clientX; node.setPointerCapture?.(ev.pointerId); });
  node.addEventListener("pointerup", (ev) => {
    if (x0 === null) return;
    const dx = ev.clientX - x0;
    x0 = null;
    if (Math.abs(dx) >= 24) onSwipe(dx > 0 ? 1 : -1); else onTap();
  });
  node.addEventListener("pointercancel", () => { x0 = null; });
  node.addEventListener("click", (ev) => { if (ev.detail === 0) onTap(); });   // keyboard activation
  node.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowRight") { ev.preventDefault(); onSwipe(1); }
    if (ev.key === "ArrowLeft") { ev.preventDefault(); onSwipe(-1); }
  });
}

function openRateSettings() {
  const boxes = ALL_RATES.map((r) => {
    const input = el("input", { type: "checkbox", value: String(r), checked: rateCycle().includes(r) });
    return el("label", { class: "rate-option" }, input, ` ${r}×`);
  });
  const save = el("button", { class: "primary", onclick: () => {
    const chosen = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => Number(i.value));
    if (!chosen.length) return toast("至少要選一個速度");
    prefs.rates = chosen;
    if (!chosen.includes(prefs.rate)) prefs.rate = chosen.includes(1) ? 1 : Math.max(...chosen);
    savePrefs();
    $("#dialog").hidden = true;
    toast(`速度按鈕會依序切換：${rateCycle().join(" → ")}`);
    route();
  } }, "儲存");
  dialog("播放速度", el("p", { class: "hint" },
    "速度按鈕：往右滑快 0.25 倍、往左滑慢 0.25 倍（0.25～2 倍循環）；點一下則依序切換下面勾選的速度（由快到慢）。"),
    el("div", { class: "rate-grid" }, boxes), save);
}

// ---------- menu & import/export ----------
$("#back").addEventListener("click", () => { location.hash = ""; });
if (FEATURES.create) {   // optional feature
  $("#menu").insertBefore(el("button", { "data-action": "create" }, "建立歌曲…"), $('#menu [data-action="rates"]'));
}
$("#menu-btn").addEventListener("click", (ev) => { ev.stopPropagation(); $("#menu").hidden = !$("#menu").hidden; });
document.addEventListener("click", () => { $("#menu").hidden = true; });
$("#menu").addEventListener("click", async (ev) => {
  const action = ev.target.dataset.action;
  if (action === "home") location.hash = "";
  if (action === "import") $("#file").click();
  if (action === "rates") openRateSettings();
  if (action === "create") openFeature("create");   // optional feature
  if (action === "ask") openAskSettings();
  if (action === "import-known") $("#known-file").click();
  if (action === "export-known") {
    const words = new Map();
    for (const ds of datasets.values()) for (const w of ds.words) if (isKnown(w)) words.set(w.key, w);
    const lines = [...words.values()].map((w) => `${w.lemma}\t${w.reading}`);
    download("known-ja.txt", `# known words exported from Sing-along\n${lines.join("\n")}\n`);
    toast(`已匯出 ${lines.length} 個詞；放到電腦的 data/known/ja.txt 即可同步到詞彙表與 Anki`);
  }
  if (action === "clear" && confirm("清除這個裝置上所有的資料檔、本機影音檔和學習紀錄？")) {
    for (const k of await kvKeys()) await kvDel(k);
    datasets = new Map(); known = new Map();
    location.hash = "";
    route();
  }
});

$("#file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = "";
  if (!f) return;
  let d;
  try {
    d = JSON.parse(await f.text());
  } catch (err) {
    return dialog("無法匯入", el("p", {}, `「${f.name}」不是有效的 JSON 檔。`),
      el("p", { class: "hint" }, `詳細：${err.message}`),
      el("p", { class: "hint" }, "請確認選的是 vocab-miner 產生的 songs.json（不是 .apkg 或其他檔案）。"));
  }
  const problems = validate(d);
  if (problems.length) {
    return dialog("無法匯入", el("p", {}, `「${f.name}」的格式不符：`),
      el("ul", { class: "problems" }, problems.map((x) => el("li", {}, x))),
      el("p", { class: "hint" }, "格式說明：", el("a", { href: DOCS_URL + "web-data-format.md", target: "_blank", rel: "noopener" }, "資料檔格式")));
  }
  const id = (d.title || f.name.replace(/\.json$/i, "") || "資料").trim();
  // same title, or exactly the same songs (e.g. an older file without a title): update instead of adding
  const songsOf = (x) => x.docs.map((doc) => doc.id).sort().join("|");
  const same = datasets.has(id) ? id : [...datasets.keys()].find((k) => songsOf(datasets.get(k)) === songsOf(d));
  const replaced = same !== undefined;
  const entries = [...datasets].map(([k, v]) => (k === same ? [id, d] : [k, v]));
  if (!replaced) entries.push([id, d]);
  const before = datasets;
  datasets = new Map(entries);
  try {
    await saveDatasets();
  } catch (err) {
    datasets = before;
    return dialog("無法儲存", el("p", {}, `手機空間不足或瀏覽器拒絕儲存：${err.message}`));
  }
  toast(`${replaced ? "已更新" : "已新增"}「${id}」：${d.docs.length} 首、${d.words.length} 個詞`);
  location.hash = "";
  route();
});

$("#media-file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  const key = ev.target.dataset.target;
  ev.target.value = "";
  if (!f || !key) return;
  if (!/^(audio|video)\//.test(f.type) && !/\.(mp3|m4a|aac|wav|ogg|opus|flac|mp4|webm|mkv|mov)$/i.test(f.name)) {
    return dialog("無法使用這個檔案", el("p", {}, `「${f.name}」看起來不是影片或音檔。`));
  }
  try {
    await kvSet(key, { name: f.name, type: f.type, blob: f });
  } catch (err) {
    return dialog("無法儲存", el("p", {}, `檔案可能太大，或手機空間不足：${err.message}`));
  }
  toast(`已設定本機檔案：${f.name}（存在這支手機上）`);
  route();
});

$("#known-file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = "";
  if (!f || !datasets.size) return;
  const lemmas = new Map();
  for (const l of (await f.text()).split(/\r?\n/)) {
    if (!l || l.startsWith("#")) continue;
    const [lemma, reading] = l.split("\t");
    lemmas.set(lemma, reading || "");
  }
  let n = 0;
  for (const ds of datasets.values()) for (const w of ds.words) {
    if (lemmas.has(w.lemma) && (!lemmas.get(w.lemma) || lemmas.get(w.lemma) === w.reading) && !known.get(w.key)) {
      known.set(w.key, true); n++;
    }
  }
  await kvSet("known", Object.fromEntries(known));
  toast(`已標記 ${n} 個詞為已學會`);
  route();
});

// ---------- start ----------
(async function init() {
  try {
    datasets = new Map(Object.entries((await kvGet("datasets")) || {}));
    const legacy = await kvGet("data");                 // single data file from the first version of the app
    if (legacy && !datasets.size) {
      datasets.set(legacy.title || "我的資料", legacy);
      await saveDatasets();
    }
    if (legacy) await kvDel("data");
    known = new Map(Object.entries((await kvGet("known")) || {}));
    lookups = new Map(Object.entries((await kvGet("lookups")) || {}));
  } catch (err) {
    toast(`無法讀取本機資料：${err.message}`);
  }
  route();
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("sw.js").catch(() => { /* offline support is optional */ });
  }
})();
