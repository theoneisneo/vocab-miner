/* Optional feature: time a song's lines by tapping (對時, in the 編輯歌詞 mode).
 *
 * The song plays; when a line starts being sung, tap 「這句開始」 (or press Enter): that line's start becomes the
 * time of the tap minus a lead, since a tap always comes a moment after the sound was heard. The lead is set in
 * the panel (default 0.3 s, kept per device) and counts in real seconds: at 0.5x speed it is half that much song.
 * The next line is then the one to tap. ‹ › choose another line, 倒回 goes back a few seconds to tap again, and
 * 復原 undoes the last tap.
 *
 * Changes are kept like the line editor's (edit.js): each tapped line counts as changed, 匯出資料檔 writes them,
 * and `vm apply-edits` writes the times back to the lyrics files. Uses only the `api` object the app passes.
 */

let api, panel, k = 0, last = null;

const round = (t) => Math.round(t * 100) / 100;
const fmt = (t) => (typeof t === "number" ? `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, "0")}` : "—");
const segText = (line) => line.seg.map((s) => s[0]).join("");

export function openTapTiming(appApi) {
  api = appApi;
  ensureCss();
  panel?.remove();
  panel = api.el("div", { class: "edit-panel tap-panel", role: "dialog", "aria-label": "對時" });
  document.body.append(panel);
  document.addEventListener("keydown", onKey, true);
  last = null;
  k = firstAhead();
  render();
}

function close() {
  panel?.remove();
  panel = null;
  document.removeEventListener("keydown", onKey, true);
  for (const li of document.querySelectorAll(".line.editing-now")) li.classList.remove("editing-now");
}

function ensureCss() {
  if (document.querySelector("link[data-edit-css]")) return;
  document.head.append(api.el("link", { rel: "stylesheet", href: new URL("edit.css", import.meta.url).href,
    "data-edit-css": "" }));
}

/** The first line that starts after the playing position: the next one to be sung. */
function firstAhead() {
  const lines = api.lines();
  const t = api.time();
  if (t === null) return 0;
  const n = lines.findIndex((l) => typeof l.start === "number" && l.start > t);
  return n < 0 ? lines.length - 1 : n;
}

function onKey(ev) {
  if (!panel) return;
  if (ev.key === "Escape") { close(); return; }
  if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.target.closest?.("input, textarea, select")) return;
  if (ev.key === "Enter") {
    ev.preventDefault();
    ev.stopPropagation();                        // not also a click on the focused button
    tap();
  }
}

/** The tap: line k starts now minus the lead; then the next line is the one to tap. */
function tap() {
  const now = api.time();
  if (now === null) return api.toast("先播放影片，再按「這句開始」");
  const lines = api.lines();
  const line = lines[k];
  if (!line) return;
  const t = round(Math.max(0, now - api.lead() * api.rate()));
  last = { k, before: structuredClone([lines[k - 1] ?? null, line]), t, old: line.start };
  const prev = lines[k - 1];
  // the line before ended where this one started: it still does
  if (prev && typeof prev.end === "number" && typeof line.start === "number" && Math.abs(prev.end - line.start) < 0.01) {
    prev.end = t;
    prev.changed = true;
  }
  line.start = t;
  if (typeof line.end === "number" && line.end <= t) {
    const next = lines[k + 1];
    line.end = typeof next?.start === "number" && next.start > t ? next.start : round(t + 2);
  }
  line.changed = true;
  if (prev && typeof prev.start === "number" && prev.start >= t) api.toast(`比第 ${k} 句的開始還早，確認一下是不是按錯句了`);
  api.save(lines);
  if (k < lines.length - 1) k++;
  render();
}

function undo() {
  if (!last) return;
  const lines = api.lines();
  const [prev, line] = last.before;
  if (prev) lines[last.k - 1] = prev;
  lines[last.k] = line;
  api.save(lines);
  k = last.k;
  last = null;
  render();
}

function back(seconds) {
  const now = api.time();
  if (now === null) return api.toast("先播放影片");
  api.seek(Math.max(0, now - seconds));
}

function render() {
  if (!panel) return;
  const el = api.el;
  const lines = api.lines();
  k = Math.max(0, Math.min(k, lines.length - 1));
  const line = lines[k];
  for (const li of document.querySelectorAll(".line")) li.classList.toggle("editing-now", Number(li.dataset.i) === k);
  document.querySelector(`.line[data-i="${k}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  const btn = (label, onclick, attrs = {}) => el("button", { class: "chip small-chip", onclick, ...attrs }, label);

  const lead = el("input", { type: "number", class: "tap-lead", min: "0", max: "2", step: "0.05",
    value: String(api.lead()), "aria-label": "提前秒數" });
  lead.addEventListener("change", () => {
    const v = Number(lead.value);
    if (Number.isFinite(v) && v >= 0 && v <= 2) api.setLead(round(v));
    else lead.value = String(api.lead());
  });

  const done = last
    ? el("div", { class: "tap-last" }, `第 ${last.k + 1} 句：${fmt(last.old)} → ${fmt(last.t)}`
      + (typeof last.old === "number" ? `（${last.t - last.old >= 0 ? "+" : ""}${(last.t - last.old).toFixed(2)} 秒）` : ""),
    btn("↺ 復原", undo))
    : el("div", { class: "tap-last hint" }, "播放歌曲，聽到下面這句開始唱時按「這句開始」（或 Enter）。");

  panel.replaceChildren(el("div", { class: "edit-card" },
    el("div", { class: "edit-head" },
      el("button", { class: "icon-btn", "aria-label": "上一句", disabled: k === 0, onclick: () => { k--; render(); } }, "‹"),
      el("strong", {}, `對時：第 ${k + 1} 句／共 ${lines.length} 句`),
      el("button", { class: "icon-btn", "aria-label": "下一句", disabled: k >= lines.length - 1,
        onclick: () => { k++; render(); } }, "›"),
      el("span", { class: "edit-status" }, `目前 ${fmt(line?.start)}`),
      el("button", { class: "icon-btn", "aria-label": "完成", onclick: close }, "✕")),
    el("div", { class: "tap-text" }, line ? segText(line) : ""),
    el("button", { class: "tap-btn", onclick: (ev) => { ev.currentTarget.blur(); tap(); } }, "這句開始"),
    done,
    el("div", { class: "edit-row tap-row" },
      btn("⟲ 倒回 3 秒", () => back(3)),
      btn("⟲ 倒回 10 秒", () => back(10)),
      btn("跳到播放位置", () => { k = firstAhead(); render(); }),
      el("label", { class: "tap-lead-row" }, "按下時提前", lead, "秒")),
    el("div", { class: "hint" }, "按下的時間減去提前的秒數，記成這句的開始（放慢播放時會自動換算）。"
      + "改好後按上方的「匯出資料檔」。")));
}
