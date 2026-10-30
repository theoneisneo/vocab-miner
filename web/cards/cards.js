/* Optional feature: word cards and a quiz from all the words of a data file (Japanese), not song by song.
 *
 *   cards  kanji / kana / romaji / 🔊 / Chinese, with the words that share the first or last part
 *   quiz   20 questions: pick the Chinese meaning out of 5; the wrong choices come from those related words
 *          first. Results and wrongly answered words are kept on this device until "重計測驗結果".
 *
 * "Related": words with kanji share their first / last kanji (okurigana ignored: 歩く → 歩); kana-only words share
 * their first / last two kana (katakana counted as hiragana).
 *
 * Self-contained like web/create: the app loads this file when the 單字卡 tab is opened and talks to it through
 * the `api` object (featureApi in app.js). To switch it off, set FEATURES.cards = false in app.js.
 */

const STORE = "vm.cards";
const QUIZ_SIZE = 20;
const CHOICES = 5;
const FREQ_POOL = 60;           // "高頻詞": 20 drawn from the 60 most frequent words not marked as learned
const EXAMPLE_LENGTH = 12;     // characters of a good example line
const REVIEW_DONE = 2;         // a wrongly answered word leaves review after this many right answers in a row
const KANJI = /[㐀-鿿豈-﫿々〆ヵヶ]/;
const KATAKANA_WORD = /^[゠-ヿー・]+$/;

let api;

// ---------- words ----------

const hira = (s) => s.replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));
const kanaOf = (w) => (KATAKANA_WORD.test(w.lemma) ? w.lemma : w.reading || w.lemma);
const hasKanji = (w) => KANJI.test(w.lemma);
const kanaLength = (w) => [...kanaOf(w)].length;

/** The meaning shown as a choice: the first sense, without notes in brackets. */
function meaning(w) {
  return (w.zh || "").replace(/（[^）]*）|\([^)]*\)/g, "").split(/[；;/]/)[0].trim() || w.zh || "";
}

/** First / last part used for "related" words, or null when the word is too short to have one. */
function ends(w) {
  const k = [...w.lemma].filter((c) => KANJI.test(c));
  if (k.length) return { head: `k:${k[0]}`, tail: `k:${k[k.length - 1]}` };
  const r = [...hira(kanaOf(w))];
  return r.length >= 2 ? { head: `h:${r.slice(0, 2).join("")}`, tail: `t:${r.slice(-2).join("")}` } : null;
}

class Deck {
  constructor(dsId, ds) {
    this.dsId = dsId;
    this.ds = ds;
    // where each word occurs: word index -> [{doc, i}] (also: only words in this file's lines are cards, as a
    // setlist file keeps the whole word list but only some songs)
    this.occurs = new Map();
    for (const doc of ds.docs) {
      doc.lines.forEach((l, i) => {
        for (const wi of new Set(l.seg.map((s) => s[2]).filter((x) => x !== null && x !== undefined))) push(this.occurs, wi, { doc, i });
      });
    }
    this.index = new Map(ds.words.map((w, i) => [w, i]));
    const used = this.occurs;
    this.words = ds.words.filter((w, i) => used.has(i) && !w.grammar && !w.foreign && w.lemma && w.zh)
      .sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9));
    this.byHead = new Map();
    this.byTail = new Map();
    for (const w of this.words) {
      const e = ends(w);
      if (!e) continue;
      push(this.byHead, e.head, w);
      push(this.byTail, e.tail, w);
    }
  }
  /** Lines with the word, easiest first: few words you have not learned, about EXAMPLE_LENGTH characters (a
   * two-word fragment shows little of how the word is used); one per song first. */
  examples(w) {
    const wi = this.index.get(w);
    const score = ({ doc, i }) => {
      const l = doc.lines[i];
      const unknown = new Set(l.seg.map((s) => s[2]).filter((x) => x !== null && x !== undefined && x !== wi
        && !this.ds.words[x]?.grammar && !api.isKnown(this.ds.words[x]))).size;
      const len = l.seg.reduce((a, s) => a + s[0].length, 0);
      return unknown + Math.abs(len - EXAMPLE_LENGTH) / 4 + (l.tr ? 0 : 2);
    };
    const all = (this.occurs.get(wi) || []).map((o) => ({ ...o, score: score(o) })).sort((a, b) => a.score - b.score);
    const firstPerSong = [], rest = [], songs = new Set();
    for (const o of all) (songs.has(o.doc) ? rest : firstPerSong).push(o), songs.add(o.doc);
    return { wi, list: [...firstPerSong, ...rest] };
  }

  sameHead(w) { const e = ends(w); return e ? (this.byHead.get(e.head) || []).filter((x) => x !== w) : []; }
  sameTail(w) { const e = ends(w); return e ? (this.byTail.get(e.tail) || []).filter((x) => x !== w) : []; }

  /** Length groups ({label, min, max}) with at least one quiz each: rare lengths join their neighbour. */
  lengthGroups() {
    const counts = new Map();
    for (const w of this.words) counts.set(kanaLength(w), (counts.get(kanaLength(w)) || 0) + 1);
    const groups = [...counts].sort((a, b) => a[0] - b[0]).map(([n, c]) => ({ min: n, max: n, count: c }));
    for (let small; groups.length > 1 && (small = groups.findIndex((g) => g.count < QUIZ_SIZE)) >= 0;) {
      const into = small === groups.length - 1 ? small - 1 : small === 0 ? 1 : small - 1;
      const [a, b] = [groups[Math.min(small, into)], groups[Math.max(small, into)]];
      groups.splice(Math.min(small, into), 2, { min: a.min, max: b.max, count: a.count + b.count });
    }
    const last = groups.length - 1;
    return groups.map((g, i) => ({ ...g, label: i === last && i > 0 ? `${g.min} 字以上`
      : g.min === g.max ? `${g.min} 字` : `${g.min}–${g.max} 字` }));
  }
}

function push(map, key, w) {
  if (!map.has(key)) map.set(key, []);
  map.get(key).push(w);
}

const shuffle = (a) => {
  const b = a.slice();
  for (let i = b.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [b[i], b[j]] = [b[j], b[i]];
  }
  return b;
};

// ---------- records (this device only) ----------

function load() {
  try {
    const r = JSON.parse(localStorage.getItem(STORE) || "{}");
    return { tests: Array.isArray(r.tests) ? r.tests : [], words: r.words && typeof r.words === "object" ? r.words : {} };
  } catch {
    return { tests: [], words: {} };
  }
}
function save(rec) {
  try { localStorage.setItem(STORE, JSON.stringify(rec)); } catch { /* private mode: results last this visit */ }
}
const inReview = (rec, w) => !!rec.words[w.key]?.review;

function record(rec, w, right) {
  const r = rec.words[w.key] || (rec.words[w.key] = { right: 0, wrong: 0, streak: 0, review: false });
  if (right) {
    r.right++;
    r.streak++;
    if (r.review && r.streak >= REVIEW_DONE) r.review = false;
  } else {
    r.wrong++;
    r.streak = 0;
    r.review = true;
  }
}

// ---------- speech ----------

function speak(text) {
  if (!("speechSynthesis" in window)) return api.toast("這個瀏覽器不支援語音");
  const voices = speechSynthesis.getVoices();
  const voice = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith("ja"));
  if (voices.length && !voice) api.toast("這台裝置沒有日文語音：到系統設定的「文字轉語音」下載日文語音");
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ja-JP";
  if (voice) u.voice = voice;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

// ---------- the 單字卡 tab on the home page ----------

export function renderCards(box, appApi, dsId, ds) {
  api = appApi;
  ensureCss();
  const el = api.el;
  const deck = new Deck(dsId, ds);
  const rec = load();
  const review = deck.words.filter((w) => inReview(rec, w));
  const total = rec.tests.reduce((a, t) => [a[0] + t.ok, a[1] + t.n], [0, 0]);
  const pct = (ok, n) => (n ? `${Math.round(ok / n * 100)}%` : "—");
  const groups = deck.lengthGroups();
  const lengthSel = el("select", { class: "cards-select" },
    groups.map((g, i) => el("option", { value: String(i) }, `${g.label}（${g.count} 個）`)));
  const start = (label, words) => openQuiz(deck, label, words, () => renderCards(box, api, dsId, ds));

  box.replaceChildren(el("div", { class: "cards-home" },
    el("section", { class: "cards-block" },
      el("h3", {}, `單字卡（${deck.words.length} 個詞，不分歌曲）`),
      el("button", { class: "secondary", onclick: () => openBrowser(deck, deck.words, 0) }, "瀏覽單字卡（依學習順序）"),
      el("button", { class: "secondary", onclick: () => openBrowser(deck, shuffle(deck.words), 0) }, "隨機瀏覽")),
    el("section", { class: "cards-block" },
      el("h3", {}, `測驗（每次 ${QUIZ_SIZE} 題，選出中文意思）`),
      el("div", { class: "cards-row" },
        el("button", { class: "secondary", onclick: () => start("高頻詞", pickFrequent(deck)) }, "高頻詞"),
        el("button", { class: "secondary", onclick: () => start("隨機", shuffle(deck.words)) }, "隨機")),
      el("div", { class: "cards-row" }, lengthSel,
        el("button", { class: "secondary", onclick: () => {
          const g = groups[Number(lengthSel.value)];
          start(`依字數：${g.label}`, shuffle(deck.words.filter((w) => kanaLength(w) >= g.min && kanaLength(w) <= g.max)));
        } }, "依字數")),
      el("button", { class: "secondary", disabled: !review.length,
        onclick: () => start("答錯複習", shuffle(review)) }, `答錯複習（${review.length} 個）`)),
    el("section", { class: "cards-block" },
      el("h3", {}, "測驗紀錄"),
      el("p", {}, `累積答對率 ${pct(...total)}（${rec.tests.length} 次測驗、共 ${total[1]} 題）`),
      rec.tests.length ? el("ol", { class: "cards-tests", reversed: true },
        rec.tests.slice(-10).reverse().map((t) => el("li", {},
          `${t.at.slice(5, 16).replace("T", " ")}　${t.mode}　${t.ok}/${t.n}（${pct(t.ok, t.n)}）`))) : null,
      el("button", { class: "secondary danger-text", disabled: !rec.tests.length && !Object.keys(rec.words).length,
        onclick: () => {
          if (!confirm("清除所有測驗紀錄、答對率和答錯的詞？")) return;
          save({ tests: [], words: {} });
          renderCards(box, api, dsId, ds);
          api.toast("已重計測驗結果");
        } }, "重計測驗結果"))));
}

function pickFrequent(deck) {
  const notKnown = deck.words.filter((w) => !api.isKnown(w));
  return shuffle((notKnown.length >= QUIZ_SIZE ? notKnown : deck.words).slice(0, FREQ_POOL));
}

// ---------- full screen panel ----------

let panel = null;
function openPanel() {
  closePanel();
  panel = api.el("div", { class: "cards-panel", role: "dialog", "aria-modal": "true" });
  document.body.append(panel);
  document.body.classList.add("cards-open");
  return panel;
}
function closePanel() {
  panel?.remove();
  panel = null;
  document.body.classList.remove("cards-open");
  document.removeEventListener("keydown", onKey);
}
let onKey = () => {};
function listenKeys(fn) {
  document.removeEventListener("keydown", onKey);
  onKey = (ev) => { if (!ev.ctrlKey && !ev.metaKey && !ev.altKey) fn(ev); };
  document.addEventListener("keydown", onKey);
}

function head(title, onClose) {
  const el = api.el;
  return el("div", { class: "cards-head" }, el("h2", {}, title),
    el("button", { class: "icon-btn", "aria-label": "關閉", onclick: onClose }, "✕"));
}

/** Lines a–d of a card (kanji, kana, romaji, 🔊); e (Chinese) is added by the caller. */
function cardFace(w) {
  const el = api.el;
  return [
    el("div", { class: "card-jp card-a" }, hasKanji(w) ? w.lemma : ""),
    el("div", { class: "card-jp card-b" }, kanaOf(w)),
    el("div", { class: "card-c" }, w.romaji || ""),
    el("button", { class: "card-d", "aria-label": "唸出來", onclick: () => speak(kanaOf(w)) }, "🔊"),
  ];
}

/** "同字首 / 同字尾" buttons; the list opens below them and each word in it opens its card. */
function related(deck, w, open) {
  const el = api.el;
  const list = el("div", { class: "card-related" });
  const show = (label, words) => {
    list.replaceChildren(words.length
      ? el("div", { class: "cards-row wrap" }, words.map((x) => el("button", { class: "chip small-chip",
        onclick: () => open(x) }, `${x.lemma}${hasKanji(x) ? `（${kanaOf(x)}）` : ""}`)))
      : el("p", { class: "hint" }, `沒有${label}的詞`));
  };
  const head = deck.sameHead(w), tail = deck.sameTail(w);
  return el("div", {},
    el("div", { class: "cards-row" },
      el("button", { class: "chip small-chip", onclick: () => show("同字首", head) }, `同字首（${head.length}）`),
      el("button", { class: "chip small-chip", onclick: () => show("同字尾", tail) }, `同字尾（${tail.length}）`)),
    list);
}

const EXAMPLES = 3;

/** The lyric lines a word appears in (EXAMPLES first, the rest on request); a line opens its song there.
 * `leave` is asked before leaving (e.g. in the middle of a quiz). */
function examples(deck, w, leave = () => true) {
  const el = api.el;
  const { wi, list } = deck.examples(w);
  if (!list.length) return null;
  const box = el("div", { class: "card-examples" });
  const show = (n) => {
    box.replaceChildren(el("h3", {}, `歌詞裡的例句（${list.length} 句）`),
      ...list.slice(0, n).map(({ doc, i }) => {
        const ex = api.exampleLine(deck.dsId, deck.ds, doc, i, wi);
        ex.querySelector(".example-song").addEventListener("click", (ev) => {
          if (!leave()) return ev.preventDefault();
          closePanel();
        });
        return ex;
      }),
      n < list.length ? el("button", { class: "link-btn", onclick: () => show(list.length) }, `顯示全部 ${list.length} 句`) : null);
  };
  show(EXAMPLES);
  return box;
}

// ---------- 1. cards ----------

function openBrowser(deck, words, i, back = []) {
  const el = api.el;
  const p = panel || openPanel();
  const w = words[i];
  const go = (j) => openBrowser(deck, words, (j + words.length) % words.length, back);
  const open = (x) => openBrowser(deck, [x], 0, [...back, { words, i }]);
  p.replaceChildren(el("div", { class: "cards-card" },
    head(`單字卡 ${words.length > 1 ? `${i + 1} / ${words.length}` : ""}`, closePanel),
    back.length ? el("button", { class: "link-btn", onclick: () => {
      const prev = back[back.length - 1];
      openBrowser(deck, prev.words, prev.i, back.slice(0, -1));
    } }, "← 回上一張") : null,
    el("div", { class: "card" }, ...cardFace(w), el("div", { class: "card-e" }, w.zh)),
    related(deck, w, open),
    words.length > 1 ? el("div", { class: "cards-row" },
      el("button", { class: "secondary", onclick: () => go(i - 1) }, "‹ 上一張"),
      el("button", { class: "primary", onclick: () => go(i + 1) }, "下一張 ›")) : null,
    examples(deck, w)));
  p.scrollTop = 0;
  listenKeys((ev) => {
    if (ev.key === "ArrowRight" && words.length > 1) go(i + 1);
    else if (ev.key === "ArrowLeft" && words.length > 1) go(i - 1);
    else if (ev.key === "Escape") closePanel();
  });
}

// ---------- 2. quiz ----------

/** A meaning without punctuation, ellipses and brackets, for telling whether two choices say the same thing. */
const core = (s) => (s || "").replace(/[\s…・、，,。．.!！?？~〜「」『』（）()［］\[\]\-—–;；:：/]/g, "");

/** Four wrong meanings: words with the same first / last part first (4 drawn at random when there are more),
 * then words of the same part of speech, then any. Left out, so that only one choice is right: the same word
 * written the same way (あの as 那個… and as 嗯 are two entries), a homophone of a kana-only answer, and a meaning
 * that contains or is contained in another choice's or appears in the answer's full meaning. */
function distractors(deck, w) {
  const full = core(w.zh);
  const seen = [core(meaning(w))];
  const out = [];
  const clash = (m) => full.includes(m) || seen.some((s) => s.includes(m) || m.includes(s));
  const take = (cands) => {
    for (const x of shuffle(cands)) {
      if (out.length >= CHOICES - 1) return;
      const m = core(meaning(x));
      if (x === w || !m || x.lemma === w.lemma || (!hasKanji(w) && kanaOf(x) === kanaOf(w)) || clash(m)) continue;
      seen.push(m);
      out.push(x);
    }
  };
  take([...new Set([...deck.sameHead(w), ...deck.sameTail(w)])]);
  take(deck.words.filter((x) => x.upos && x.upos === w.upos));
  take(deck.words);
  return out;
}

function openQuiz(deck, mode, pool, onDone) {
  const questions = pool.slice(0, QUIZ_SIZE);
  if (!questions.length) return api.toast("沒有可以考的詞");
  const answers = [];
  openPanel();
  const ask = (n) => {
    const el = api.el;
    const w = questions[n];
    const choices = shuffle([w, ...distractors(deck, w)]);
    let done = false;
    const e = el("div", { class: "card-e quiz-hidden" }, "？");
    const buttons = choices.map((x, k) => el("button", { class: "quiz-choice", onclick: () => answer(k) },
      el("span", { class: "quiz-num" }, String(k + 1)), meaning(x)));
    const next = el("button", { class: "primary", hidden: true, onclick: () => advance() },
      n + 1 < questions.length ? "下一題 ›" : "看結果");
    const after = el("div", {});
    const answer = (k) => {
      if (done) return;
      done = true;
      const right = choices[k] === w;
      answers.push({ w, right });
      buttons.forEach((b, j) => {
        b.disabled = true;
        if (choices[j] === w) b.classList.add("right");
        else if (j === k) b.classList.add("wrong");
      });
      e.textContent = w.zh;
      e.classList.remove("quiz-hidden");
      after.replaceChildren(related(deck, w, (x) => openPeek(deck, x)) || "",
        examples(deck, w, () => confirm("離開測驗去聽這首歌？這次的結果不會記錄。")) || "");
      next.hidden = false;
      next.focus();
    };
    const advance = () => (n + 1 < questions.length ? ask(n + 1) : finish());
    panel.replaceChildren(el("div", { class: "cards-card" },
      head(`${mode}　${n + 1} / ${questions.length}`, () => { if (confirm("結束這次測驗？這次的結果不會記錄。")) closePanel(); }),
      el("div", { class: "card" }, ...cardFace(w), e),
      el("div", { class: "quiz-choices" }, buttons), next, after));
    listenKeys((ev) => {
      if (!done && /^[1-5]$/.test(ev.key) && Number(ev.key) <= choices.length) answer(Number(ev.key) - 1);
      else if (done && ev.key === "Enter") { ev.preventDefault(); advance(); }
    });
  };
  const finish = () => {
    const el = api.el;
    const rec = load();
    for (const a of answers) record(rec, a.w, a.right);
    const ok = answers.filter((a) => a.right).length;
    rec.tests.push({ at: new Date().toISOString(), mode, n: answers.length, ok });
    save(rec);
    const wrong = answers.filter((a) => !a.right);
    panel.replaceChildren(el("div", { class: "cards-card" },
      head("測驗結果", () => { closePanel(); onDone(); }),
      el("p", { class: "quiz-score" }, `${ok} / ${answers.length}（${Math.round(ok / answers.length * 100)}%）`),
      wrong.length ? el("div", {}, el("h3", {}, "答錯的詞（已加進答錯複習）"),
        el("ul", { class: "quiz-wrong" }, wrong.map(({ w }) => el("li", {},
          el("b", {}, w.lemma), hasKanji(w) ? `（${kanaOf(w)}）` : "", `　${w.zh}`))))
        : el("p", {}, "全部答對！"),
      el("div", { class: "cards-row" },
        el("button", { class: "secondary", onclick: () => { closePanel(); onDone(); } }, "回到單字卡"),
        el("button", { class: "primary", onclick: () => openQuiz(deck, mode, shuffle(pool), onDone) }, "再考一次"))));
    listenKeys((ev) => { if (ev.key === "Escape") { closePanel(); onDone(); } });
  };
  ask(0);
}

/** A related word's card over the quiz, without leaving the question. */
function openPeek(deck, w) {
  const el = api.el;
  const box = el("div", { class: "cards-peek", onclick: (ev) => { if (ev.target === box) box.remove(); } },
    el("div", { class: "card" }, ...cardFace(w), el("div", { class: "card-e" }, w.zh),
      el("button", { class: "secondary", onclick: () => box.remove() }, "關閉")));
  panel.append(box);
}

function ensureCss() {
  if (document.querySelector("link[data-cards-css]")) return;
  document.head.append(api.el("link", { rel: "stylesheet", href: new URL("cards.css", import.meta.url).href,
    "data-cards-css": "" }));
}
