/* Optional feature: edit one line of a song (✎ in the 編輯歌詞 mode).
 *
 *   - the line word by word, the Japanese over its romaji: deleting a word removes both, so they never disagree
 *   - a word's reading (kana) for songs that sing it another way; its romaji follows
 *   - the whole text, tokenized again in the browser (kuromoji, downloaded on first use)
 *   - split the line before any word; join it with the next
 *   - start and end times: ±0.1 s, or "now" from the playing video
 *   - the translation, free text
 *   - 復原本句: everything back to how it was when this line was opened
 *
 * Changes are kept on this device by the app (lineEdits) as soon as they are made. The app passes the `api`
 * object; nothing else of it is used, so this folder can be removed (see the README).
 */
import { buildJapanese, splitOkurigana, romanize, fixGeminates, HAS_KANJI, hira } from "../lib/ja.js";

let api, panel, lines, i, snapshot, selected = null, trTimer = null;
let pendingText = null;      // text typed in the box but not applied yet (重新分詞 / Enter applies it)

/** Leaving the line with typed text not applied: ask first. True when it is fine to go on. */
function leaveText() {
  if (pendingText === null) return true;
  if (!confirm("改的字還沒套用（要按「重新分詞」才會套用）。放棄這些修改？")) return false;
  pendingText = null;
  return true;
}

export function openLineEditor(appApi) {
  api = appApi;
  ensureCss();
  panel?.remove();
  panel = api.el("div", { class: "edit-panel", role: "dialog", "aria-label": "編輯這句" });
  document.body.append(panel);
  document.addEventListener("keydown", onKey);
  goTo(api.i);
}

function onKey(ev) {
  if (ev.key === "Escape" && panel) close();
}

function close() {
  if (!leaveText()) return;
  flushTranslation();
  panel?.remove();
  panel = null;
  document.removeEventListener("keydown", onKey);
  for (const li of document.querySelectorAll(".line.editing-now")) li.classList.remove("editing-now");
}

function ensureCss() {
  if (document.querySelector("link[data-edit-css]")) return;
  document.head.append(api.el("link", { rel: "stylesheet", href: new URL("edit.css", import.meta.url).href,
    "data-edit-css": "" }));
}

function goTo(k) {
  if (panel && lines && !leaveText()) return;
  flushTranslation();
  lines = api.lines();
  i = Math.max(0, Math.min(k, lines.length - 1));
  snapshot = structuredClone(lines);
  selected = null;
  render();
}

/** Keep the change and show it (the app re-draws the song); the line counts as changed. */
function commit(changed = true) {
  if (changed && lines[i]) lines[i].changed = true;
  api.save(lines);
  lines = api.lines();
  render();
}

// ---------- the line as words ----------

const segText = (line) => line.seg.map((s) => s[0]).join("");

/** Pieces of the line grouped by token: [{ti, segs: [seg positions]}]. */
function units(line) {
  const out = [];
  line.seg.forEach((s, k) => {
    const ti = s[3] ?? null;
    const last = out[out.length - 1];
    if (ti !== null && last && last.ti === ti) last.segs.push(k);
    else out.push({ ti, segs: [k] });
  });
  return out;
}

function setRomaji(line) {
  if (Array.isArray(line.wr) && line.wr.length) line.romaji = line.wr.filter((x) => x).join(" ");
}

function deleteUnit(u) {
  const line = lines[i];
  const un = units(line)[u];
  line.seg = line.seg.filter((_, k) => !un.segs.includes(k));
  if (un.ti !== null && Array.isArray(line.wr)) line.wr[un.ti] = "";
  setRomaji(line);
  selected = null;
  commit();
}

function editReading(u) {
  const line = lines[i];
  const un = units(line)[u];
  const surface = un.segs.map((k) => line.seg[k][0]).join("");
  const now = un.segs.map((k) => line.seg[k][1] ?? line.seg[k][0]).join("");
  const answer = prompt(`「${surface}」的讀音（假名）`, hira(now));
  if (answer === null) return;
  const r = hira(answer.trim());
  if (!/^[ぁ-ゖー]+$/.test(r)) return api.toast("讀音請用假名");
  const [, , wi, ti] = line.seg[un.segs[0]];
  const pieces = HAS_KANJI.test(surface) ? splitOkurigana(surface, r) : [[surface, null]];
  line.seg.splice(un.segs[0], un.segs.length, ...pieces.map(([p, ruby]) => [p, ruby, wi, ti]));
  if (ti !== null && Array.isArray(line.wr)) {
    line.wr[ti] = romanize(r);
    fixGeminates(line.wr);
    setRomaji(line);
  }
  commit();
}

/** Two lines from one, the second starting at word u; its start is estimated by the length of the text. */
function splitAt(u) {
  if (!leaveText()) return;
  const line = lines[i];
  const cut = units(line)[u].segs[0];
  const segA = line.seg.slice(0, cut), segB = line.seg.slice(cut);
  const tiCut = segB.map((s) => s[3]).find((t) => t !== null && t !== undefined);
  const wr = Array.isArray(line.wr) ? line.wr : [];
  const wrA = tiCut === undefined ? wr : wr.slice(0, tiCut);
  const wrB = tiCut === undefined ? [] : wr.slice(tiCut);
  const lenA = segA.map((s) => s[0]).join("").length, lenB = segB.map((s) => s[0]).join("").length;
  let mid = null;
  if (typeof line.start === "number") {
    const next = lines[i + 1];
    const end = typeof line.end === "number" ? line.end : typeof next?.start === "number" ? next.start : line.start + 4;
    mid = Math.round((line.start + (end - line.start) * lenA / Math.max(lenA + lenB, 1)) * 100) / 100;
  }
  const a = { ...line, seg: segA, wr: wrA, end: mid ?? line.end, changed: true };
  const b = { ...line, id: `${line.id ?? "line"}.2`, seg: segB.map(([t, r, w, ti]) => [t, r, w,
    ti === null || ti === undefined || tiCut === undefined ? ti : ti - tiCut]), wr: wrB,
  start: mid ?? line.start, tr: "", changed: true };
  delete b.ex;
  setRomaji(a);
  setRomaji(b);
  lines.splice(i, 1, a, b);
  selected = null;
  commit();
  api.toast("拆成兩句了：翻譯留在第一句，第二句的翻譯請自己填；第二句的開始時間是估的，可以再調");
}

async function retokenize(text) {
  const line = lines[i];
  text = text.trim();
  if (!text || text === segText(line)) { pendingText = null; return render(); }
  const ds = api.ds;
  if ((ds.lang || "ja").split("-")[0] !== "ja") {
    Object.assign(line, { seg: [[text, null, null, null]], wr: [], romaji: "" });
    pendingText = null;
    return commit();
  }
  const status = panel.querySelector(".edit-status");
  if (status) status.textContent = "分詞中…（第一次需要下載約 12 MB）";
  try {
    const index = new Map(ds.words.map((w, k) => [w.key, k]));
    const [b] = await buildJapanese([text], ds.words, index, api.datasets());
    Object.assign(line, { seg: b.seg, wr: b.wr, romaji: b.romaji });
    pendingText = null;
    commit();
  } catch (err) {
    if (status) status.textContent = "";
    api.toast(String(err.message || err));
  }
}

// ---------- times ----------

const round = (t) => Math.round(t * 100) / 100;
const fmt = (t) => (typeof t === "number" ? `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, "0")}` : "—");

function setTime(field, t) {
  const line = lines[i];
  t = round(Math.max(0, t));
  if (field === "start") {
    const prev = lines[i - 1];
    if (prev && typeof prev.end === "number" && Math.abs(prev.end - line.start) < 0.01) prev.end = t;  // still joined
    line.start = t;
  } else line.end = t;
  if (typeof line.start === "number" && typeof line.end === "number" && line.end <= line.start) {
    return api.toast("結束要在開始之後");
  }
  commit();
}

function setNow(field) {
  const t = api.time();
  if (t === null) return api.toast("先播放影片，再按「設成現在」");
  setTime(field, t);
}

// ---------- translation (saved a moment after typing stops) ----------

function flushTranslation() {
  if (!trTimer) return;
  clearTimeout(trTimer);
  trTimer = null;
  commit();
}

// ---------- the panel ----------

function render() {
  if (!panel) return;                                 // closed while tokenizing: the change is kept all the same
  const el = api.el;
  const line = lines[i];
  for (const li of document.querySelectorAll(".line")) li.classList.toggle("editing-now", Number(li.dataset.i) === i);
  if (!line) return close();
  const us = units(line);
  const wr = Array.isArray(line.wr) ? line.wr : [];
  const btn = (label, onclick, attrs = {}) => el("button", { class: "chip small-chip", onclick, ...attrs }, label);

  const tokens = el("div", { class: "edit-tokens" }, us.map((un, u) => {
    const jp = el("span", { class: "edit-jp" }, un.segs.map((k) => {
      const [t, ruby] = line.seg[k];
      return ruby ? el("ruby", {}, t, el("rt", {}, ruby)) : t;
    }));
    return el("button", { class: "edit-tok" + (selected === u ? " selected" : ""), "aria-pressed": String(selected === u),
      onclick: () => { selected = selected === u ? null : u; render(); } },
    jp, el("span", { class: "edit-ro" }, un.ti !== null ? wr[un.ti] || "" : ""));
  }));

  const sel = selected !== null && us[selected] ? us[selected] : null;
  const actions = el("div", { class: "edit-actions" },
    sel ? [
      btn("✕ 刪除這個詞", () => deleteUnit(selected)),
      HAS_KANJI.test(sel.segs.map((k) => line.seg[k][0]).join("")) || sel.ti !== null ? btn("改讀音", () => editReading(selected)) : null,
      selected > 0 ? btn("✂ 從這裡拆成新的一句", () => splitAt(selected)) : null,
    ] : el("span", { class: "hint" }, "點一個詞：刪除、改讀音，或從那裡拆句。日文和拼音一起刪。"));

  // typed text survives the other buttons (they re-draw the panel) until it is applied or given up
  const textInput = el("input", { class: "edit-text", value: pendingText ?? segText(line), "aria-label": "這句的日文" });
  const applyBtn = btn(pendingText !== null ? "重新分詞（未套用）" : "重新分詞", () => retokenize(textInput.value));
  const showPending = () => {
    applyBtn.classList.toggle("edit-pending", pendingText !== null);
    applyBtn.textContent = pendingText !== null ? "重新分詞（未套用）" : "重新分詞";
  };
  textInput.addEventListener("input", () => {
    pendingText = textInput.value.trim() === segText(line) ? null : textInput.value;
    showPending();
  });
  textInput.addEventListener("keydown", (ev) => { if (ev.key === "Enter") retokenize(textInput.value); });
  showPending();
  const tr = el("textarea", { class: "edit-tr", rows: "2", "aria-label": "翻譯" });
  tr.value = line.tr || "";
  tr.addEventListener("input", () => {
    line.tr = tr.value;
    line.changed = true;
    clearTimeout(trTimer);
    trTimer = setTimeout(() => { trTimer = null; api.save(lines); lines = api.lines(); }, 600);
  });

  const timeRow = (label, field) => el("div", { class: "edit-time" },
    el("span", { class: "edit-label" }, label),
    btn("−0.1", () => setTime(field, (line[field] ?? 0) - 0.1)),
    el("span", { class: "edit-t" }, fmt(line[field])),
    btn("+0.1", () => setTime(field, (line[field] ?? 0) + 0.1)),
    btn("設成現在", () => setNow(field)));

  panel.replaceChildren(el("div", { class: "edit-card" },
    el("div", { class: "edit-head" },
      el("button", { class: "icon-btn", "aria-label": "上一句", disabled: i === 0, onclick: () => goTo(i - 1) }, "‹"),
      el("strong", {}, `第 ${i + 1} 句／共 ${lines.length} 句`),
      el("button", { class: "icon-btn", "aria-label": "下一句", disabled: i >= lines.length - 1, onclick: () => goTo(i + 1) }, "›"),
      el("span", { class: "edit-status" }),
      el("button", { class: "icon-btn", "aria-label": "完成", onclick: close }, "✕")),
    tokens, actions,
    el("label", { class: "edit-label" }, "改字（按 Enter 或「重新分詞」，讀音和拼音會重新產生）"),
    el("div", { class: "edit-row" }, textInput, applyBtn),
    el("label", { class: "edit-label" }, "翻譯（自由修改）"), tr,
    typeof line.start === "number" || typeof line.end === "number"
      ? [timeRow("開始", "start"), timeRow("結束", "end"), el("div", { class: "edit-row" }, btn("▶ 播這句", () => api.playLine(i)))]
      : null,
    el("div", { class: "edit-row edit-foot" },
      i + 1 < lines.length ? btn("⊕ 和下一句合併", () => {
        if (!leaveText()) return;
        lines.splice(i, 2, api.join(lines[i], lines[i + 1]));
        commit(false);
      }) : null,
      btn("刪除這句", () => {
        if (!leaveText()) return;
        if (!confirm("刪除這一句？（按「復原本句」可以救回來）")) return;
        lines.splice(i, 1);
        api.save(lines);
        lines = api.lines();
        i = Math.min(i, lines.length - 1);
        render();
      }),
      btn("↺ 復原本句", () => {
        pendingText = null;
        lines = structuredClone(snapshot);
        selected = null;
        commit(false);
      }))));
}
