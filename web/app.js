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
const prefs = Object.assign({ ruby: true, romaji: true, tr: true, gloss: false, struct: false, follow: true,
  loop: false, rate: 1, rates: [1, 0.75, 0.5, 0.25] }, safeJson(localStorageGet(PREFS_KEY)));
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }
function safeJson(s) { try { return JSON.parse(s) || {}; } catch { return {}; } }
function savePrefs() { localStorageSet(PREFS_KEY, JSON.stringify(prefs)); }

// ---------- state ----------
let datasets = new Map();   // dataset id -> imported data file
let data = null;            // the dataset of the song being shown
let known = new Map();      // word key -> true/false (overrides status from the data files; shared by all datasets)
let player = null, ticker = null, currentLine = -1, loopLine = -1;

function isKnown(w) {
  return known.has(w.key) ? known.get(w.key) : w.status === "known";
}
async function setKnown(w, value) {
  known.set(w.key, value);
  await kvSet("known", Object.fromEntries(known));
}
const saveDatasets = () => kvSet("datasets", Object.fromEntries(datasets));

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
      el("button", { class: "primary", onclick: () => $("#file").click() }, "匯入資料檔")));
    return;
  }
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
async function renderDoc(dsId, ds, doc) {
  data = ds;
  $("#title").textContent = doc.title;
  $("#back").hidden = false;
  view.replaceChildren();
  const root = el("div", { class: "doc" });
  applyPrefClasses(root);

  const local = await kvGet(mediaKey(doc)).catch(() => null);
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
  const rateBtn = el("button", { class: "chip", onclick: () => {
    prefs.rate = nextRate(prefs.rate);
    savePrefs();
    rateBtn.textContent = `${prefs.rate}×`;
    if (player) player.setRate(prefs.rate);
  } }, `${prefs.rate}×`);
  const playable = !!(local || youtube);
  const toolbar = el("div", { class: "toolbar" },
    chip("假名", "ruby"), chip("拼音", "romaji"), chip("中文", "tr"), chip("逐詞", "gloss"), chip("結構", "struct"),
    playable ? chip("跟隨", "follow") : null,
    playable ? chip("單句重複", "loop", () => { loopLine = prefs.loop ? currentLine : -1; }) : null,
    playable ? rateBtn : null);
  stick.append(toolbar);
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
      if (w) block.addEventListener("click", (ev) => { ev.stopPropagation(); openWord(w, block); });
      jp.append(block);
    }
    text.append(node);
  }
  const li = el("li", { class: "line", "data-i": i },
    line.start !== null && line.start !== undefined ? el("span", { class: "line-time" }, fmtTime(line.start)) : null,
    jp,
    line.romaji ? el("div", { class: "line-romaji" + (wr.length ? " has-wr" : "") }, line.romaji) : null,
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
  $("#sheet-en").textContent = w.en || "";
  $("#sheet-meta").textContent = w.grammar
    ? `${w.pos || ""} · 文法詞 · 出現 ${w.count ?? "?"} 次`
    : `${w.pos || ""} · 學習順序 #${w.rank ?? "?"} · 出現在 ${w.docFreq ?? "?"} 首、共 ${w.count ?? "?"} 次`;
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
  dialog("播放速度", el("p", { class: "hint" }, "勾選速度按鈕要循環的選項（由快到慢）。YouTube 影片只支援 0.25～2 倍。"),
    el("div", { class: "rate-grid" }, boxes), save);
}

// ---------- menu & import/export ----------
$("#back").addEventListener("click", () => { location.hash = ""; });
$("#menu-btn").addEventListener("click", (ev) => { ev.stopPropagation(); $("#menu").hidden = !$("#menu").hidden; });
document.addEventListener("click", () => { $("#menu").hidden = true; });
$("#menu").addEventListener("click", async (ev) => {
  const action = ev.target.dataset.action;
  if (action === "home") location.hash = "";
  if (action === "import") $("#file").click();
  if (action === "rates") openRateSettings();
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
  } catch (err) {
    toast(`無法讀取本機資料：${err.message}`);
  }
  route();
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    navigator.serviceWorker.register("sw.js").catch(() => { /* offline support is optional */ });
  }
})();
