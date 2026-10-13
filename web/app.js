/* Sing-along: reads a vocab-miner data file (vm web) kept on this device. No data leaves the device. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const view = $("#view");

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

const PREFS_KEY = "vm.prefs";
const prefs = Object.assign({ ruby: true, romaji: true, tr: true, gloss: false, struct: false, follow: true,
  loop: false, rate: 1 },
  safeJson(localStorageGet(PREFS_KEY)));
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }
function safeJson(s) { try { return JSON.parse(s) || {}; } catch { return {}; } }
function savePrefs() { localStorageSet(PREFS_KEY, JSON.stringify(prefs)); }

// ---------- state ----------
let data = null;            // imported data file
let known = new Map();      // word key -> true/false (overrides status from the data file)
let player = null, playerReady = false, ticker = null, currentLine = -1, loopLine = -1;

function isKnown(w) {
  return known.has(w.key) ? known.get(w.key) : w.status === "known";
}
async function setKnown(w, value) {
  known.set(w.key, value);
  await kvSet("known", Object.fromEntries(known));
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
  toast.timer = setTimeout(() => (t.hidden = true), 2600);
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

/** Share of content-word tokens in a doc that are known, and the number of distinct new content words. */
function docStats(doc) {
  let total = 0, ok = 0;
  const fresh = new Set();
  for (const line of doc.lines) for (const [, , wi] of line.seg) {
    if (wi === null) continue;
    const w = data.words[wi];
    if (w.grammar) continue;
    total++;
    if (isKnown(w)) ok++; else fresh.add(w.key);
  }
  return { pct: total ? Math.round((100 * ok) / total) : 0, fresh: fresh.size };
}

// ---------- routing ----------
function route() {
  stopPlayer();
  const m = location.hash.match(/^#\/doc\/(.+)$/);
  if (data && m) {
    const doc = data.docs.find((d) => d.id === decodeURIComponent(m[1]));
    if (doc) return renderDoc(doc);
  }
  renderHome();
}
window.addEventListener("hashchange", route);

// ---------- home ----------
function renderHome() {
  $("#title").textContent = "Sing-along";
  $("#back").hidden = true;
  view.replaceChildren();
  if (!data) {
    view.append(el("div", { class: "empty" },
      el("h2", {}, "還沒有資料"),
      el("p", {}, "在電腦執行 ", el("code", {}, "uv run vm web"), "，把產生的 songs.json 傳到這支手機，再按下面的按鈕匯入。"),
      el("p", {}, "資料只會存在這個裝置上。"),
      el("button", { class: "primary", onclick: () => $("#file").click() }, "匯入資料檔")));
    return;
  }
  const docs = data.docs.map((d) => ({ d, s: docStats(d) }));
  const main = docs.filter((x) => !x.d.noStats), extra = docs.filter((x) => x.d.noStats);
  const list = (items) => el("ul", { class: "songs" }, items.map(({ d, s }) =>
    el("li", {}, el("a", { class: "song", href: `#/doc/${encodeURIComponent(d.id)}` },
      el("div", { class: "song-title" }, d.title, el("div", { class: "song-sub" }, `${d.lines.length} 句 · 生詞 ${s.fresh}`)),
      el("div", { class: "meter" }, `已懂 ${s.pct}%`, el("div", { class: "meter-bar" }, el("span", { style: `width:${s.pct}%` })))))));
  main.sort((a, b) => b.s.pct - a.s.pct || a.s.fresh - b.s.fresh);
  view.append(el("div", { class: "section-title" }, "依已懂比例排序：越上面越容易學"), list(main));
  if (extra.length) view.append(el("div", { class: "section-title" }, "其他版本（不列入統計）"), list(extra));
  const knownCount = data.words.filter((w) => !w.grammar && isKnown(w)).length;
  view.append(el("p", { class: "section-title" },
    `已學會 ${knownCount} / ${data.words.filter((w) => !w.grammar).length} 個詞 · 資料產生於 ${data.generated.slice(0, 10)}`));
  view.append(el("div", { class: "home-actions" },
    el("button", { class: "secondary", onclick: () => $("#file").click() }, "更新資料（匯入新的 songs.json）")));
}

// ---------- song ----------
function renderDoc(doc) {
  $("#title").textContent = doc.title;
  $("#back").hidden = false;
  view.replaceChildren();
  const root = el("div", { class: "doc" });
  applyPrefClasses(root);

  const hasVideo = doc.media && doc.media.kind === "youtube";
  const stick = el("div", { class: "stick" });          // player + toolbar stay under the top bar
  root.append(stick);
  if (hasVideo) {
    stick.append(el("div", { class: "player-wrap" }, el("div", { class: "player" }, el("div", { id: "yt" }))));
  }

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
  const rateBtn = el("button", { class: "chip", onclick: () => {
    prefs.rate = prefs.rate === 1 ? 0.75 : prefs.rate === 0.75 ? 0.5 : 1;
    savePrefs();
    rateBtn.textContent = `${prefs.rate}×`;
    if (playerReady) player.setPlaybackRate(prefs.rate);
  } }, `${prefs.rate}×`);
  const toolbar = el("div", { class: "toolbar" },
    chip("假名", "ruby"), chip("拼音", "romaji"), chip("中文", "tr"), chip("逐詞", "gloss"), chip("結構", "struct"),
    hasVideo ? chip("跟隨", "follow") : null,
    hasVideo ? chip("單句重複", "loop", () => { loopLine = prefs.loop ? currentLine : -1; }) : null,
    hasVideo ? rateBtn : null);
  stick.append(toolbar);
  stick.append(el("div", { class: "legend" },
    el("span", { class: "role-prt" }, "助詞"), el("span", { class: "role-pred" }, "動詞・形容詞"),
    el("span", { class: "role-aux" }, "時態・否定・句型"), el("span", { class: "legend-note" }, "動詞通常在句尾")));

  const lines = el("ol", { class: "lines" }, doc.lines.map((line, i) => renderLine(doc, line, i)));
  root.append(lines);
  view.append(root);

  if (hasVideo) startPlayer(doc);
}

function applyPrefClasses(root) {
  root.classList.toggle("hide-ruby", !prefs.ruby);
  root.classList.toggle("hide-romaji", !prefs.romaji);
  root.classList.toggle("hide-tr", !prefs.tr);
  root.classList.toggle("show-gloss", !!prefs.gloss);
  root.classList.toggle("show-struct", !!prefs.struct);
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
  // consecutive segments of the same word share one tappable span
  let span = null, spanWord = null;
  for (const [text, ruby, wi] of line.seg) {
    const node = ruby ? el("ruby", {}, text, el("rt", {}, ruby)) : document.createTextNode(text);
    if (wi === null) { span = null; spanWord = null; jp.append(node); continue; }
    if (wi !== spanWord) {
      const w = data.words[wi];
      const r = role(w);
      const s = el("span", { class: "w" + (w.grammar ? " grammar" : isKnown(w) ? "" : " new") + (r ? ` role-${r}` : ""),
        "data-w": wi });
      const text = el("span", { class: "wt" });
      s.append(text, el("span", { class: "gl" }, shortGloss(w)));
      s.addEventListener("click", (ev) => { ev.stopPropagation(); openWord(w, s); });
      span = text;
      spanWord = wi;
      jp.append(s);
    }
    span.append(node);
  }
  const li = el("li", { class: "line", "data-i": i },
    line.start !== null ? el("span", { class: "line-time" }, fmtTime(line.start)) : null,
    jp,
    line.romaji ? el("div", { class: "line-romaji" }, line.romaji) : null,
    line.tr ? el("div", { class: "line-tr" }, line.tr) : null);
  li.addEventListener("click", () => playLine(doc, i));
  return li;
}

// ---------- word sheet ----------
let sheetWord = null, sheetSpan = null;
function openWord(w, span) {
  sheetWord = w;
  document.querySelectorAll(".w.sel").forEach((e) => e.classList.remove("sel"));
  sheetSpan = span;
  span.classList.add("sel");
  $("#sheet-lemma").textContent = w.lemma;
  $("#sheet-reading").textContent = [w.reading !== w.lemma ? w.reading : "", w.romaji].filter(Boolean).join(" · ");
  $("#sheet-meaning").textContent = w.zh || "（還沒有中文釋義）";
  $("#sheet-ff").hidden = !w.ff;
  $("#sheet-ff").textContent = w.ff ? `⚠ 和中文意思不同：${w.ff}` : "";
  $("#sheet-en").textContent = w.en;
  $("#sheet-meta").textContent = w.grammar
    ? `${w.pos} · 文法詞 · 出現 ${w.count} 次`
    : `${w.pos} · 學習順序 #${w.rank} · 出現在 ${w.docFreq} 首、共 ${w.count} 次`;
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
$("#sheet").addEventListener("click", (ev) => { if (ev.target.id === "sheet") closeSheet(); });
$("#sheet-known").addEventListener("click", async () => {
  await setKnown(sheetWord, !isKnown(sheetWord));
  updateKnownButton();
  const wi = String(data.words.indexOf(sheetWord));
  document.querySelectorAll(`.w[data-w="${wi}"]`).forEach((e) =>
    e.classList.toggle("new", !sheetWord.grammar && !isKnown(sheetWord)));
});

// ---------- YouTube ----------
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

async function startPlayer(doc) {
  try {
    await loadYouTubeApi();
  } catch {
    const host = document.getElementById("yt");
    if (host) host.replaceWith(el("div", { class: "offline-note" }, "離線中：影片無法載入，歌詞仍可閱讀。"));
    return;
  }
  if (!document.getElementById("yt")) return;          // navigated away meanwhile
  player = new YT.Player("yt", {
    videoId: doc.media.uri,
    playerVars: { playsinline: 1, rel: 0, modestbranding: 1 },
    events: {
      onReady: () => { playerReady = true; player.setPlaybackRate(prefs.rate); },
      onStateChange: (e) => {
        if (e.data === YT.PlayerState.PLAYING) startTicker(doc);
        else stopTicker();
      },
    },
  });
}

function stopPlayer() {
  stopTicker();
  if (player && player.destroy) try { player.destroy(); } catch { /* already gone */ }
  player = null; playerReady = false; currentLine = -1; loopLine = -1;
  closeSheet();
}

function playLine(doc, i) {
  const line = doc.lines[i];
  if (!playerReady || line.start === null) return;
  player.seekTo(line.start, true);
  player.playVideo();
  setCurrent(i);
  if (prefs.loop) loopLine = i;
}

function startTicker(doc) {
  stopTicker();
  ticker = setInterval(() => {
    if (!playerReady) return;
    const t = player.getCurrentTime();
    if (prefs.loop && loopLine >= 0) {
      const l = doc.lines[loopLine];
      const end = l.end ?? (l.start + 6);
      if (t >= end - 0.05 || t < l.start - 1) { player.seekTo(l.start, true); return; }
    }
    let idx = -1;
    for (let i = 0; i < doc.lines.length; i++) {
      const s = doc.lines[i].start;
      if (s !== null && s <= t + 0.15) idx = i;
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

// ---------- menu & import/export ----------
$("#back").addEventListener("click", () => { location.hash = ""; });
$("#menu-btn").addEventListener("click", (ev) => { ev.stopPropagation(); $("#menu").hidden = !$("#menu").hidden; });
document.addEventListener("click", () => { $("#menu").hidden = true; });
$("#menu").addEventListener("click", async (ev) => {
  const action = ev.target.dataset.action;
  if (action === "import") $("#file").click();
  if (action === "import-known") $("#known-file").click();
  if (action === "export-known") {
    if (!data) return toast("還沒有資料");
    const lines = data.words.filter((w) => isKnown(w)).map((w) => `${w.lemma}\t${w.reading}`);
    download("known-ja.txt", `# known words exported from Sing-along\n${lines.join("\n")}\n`);
    toast(`已匯出 ${lines.length} 個詞；放到電腦的 data/known/ja.txt 即可同步到詞彙表與 Anki`);
  }
  if (action === "clear" && confirm("清除這個裝置上的歌詞資料和學習紀錄？")) {
    await kvDel("data"); await kvDel("known");
    data = null; known = new Map();
    location.hash = "";
    route();
  }
});

$("#file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = "";
  if (!f) return;
  try {
    let d;
    try { d = JSON.parse(await f.text()); } catch { throw new Error(`「${f.name}」不是 JSON 檔`); }
    if (d.format !== "vocab-miner-web" || d.version !== 1) throw new Error("不是 vocab-miner 的資料檔（或版本不符）");
    await kvSet("data", d);
    data = d;
    toast(`已匯入 ${d.docs.length} 首、${d.words.length} 個詞`);
    location.hash = "";
    route();
  } catch (err) {
    toast(`匯入失敗：${err.message}`);
  }
});

$("#known-file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = "";
  if (!f || !data) return;
  const names = new Set((await f.text()).split(/\r?\n/).filter((l) => l && !l.startsWith("#"))
    .map((l) => l.split("\t")));
  let n = 0;
  const lemmas = new Map();
  for (const [lemma, reading] of names) lemmas.set(lemma, reading || "");
  for (const w of data.words) {
    if (lemmas.has(w.lemma) && (!lemmas.get(w.lemma) || lemmas.get(w.lemma) === w.reading)) { known.set(w.key, true); n++; }
  }
  await kvSet("known", Object.fromEntries(known));
  toast(`已標記 ${n} 個詞為已學會`);
  route();
});

// ---------- start ----------
(async function init() {
  try {
    data = (await kvGet("data")) || null;
    known = new Map(Object.entries((await kvGet("known")) || {}));
  } catch (err) {
    toast(`無法讀取本機資料：${err.message}`);
  }
  route();
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("sw.js").catch(() => { /* offline support is optional */ });
  }
})();
