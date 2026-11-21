/* Japanese in the browser, shared by the optional features (create a song, edit lines):
 * tokenizing (kuromoji.js, downloaded on first use, about 12 MB), readings split over the kanji, Hepburn romaji
 * with the same rules as the Python romanizer, and words matched to the ones data files already have.
 * Only tokenize() needs the download; the rest works offline.
 */

const KUROMOJI = "https://cdn.jsdelivr.net/npm/kuromoji@0.1.2/build/kuromoji.js";
const KUROMOJI_DICT = "https://cdn.jsdelivr.net/npm/kuromoji@0.1.2/dict/";

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

export function japaneseTokenizer() {
  if (!tokenizerPromise) {
    tokenizerPromise = loadScript(KUROMOJI).then(() => new Promise((resolve, reject) => {
      window.kuromoji.builder({ dicPath: KUROMOJI_DICT }).build((err, t) => (err ? reject(err) : resolve(t)));
    })).catch((err) => { tokenizerPromise = null; throw err; });
  }
  return tokenizerPromise;
}

export const KANA = /^[ぁ-ゖァ-ヺー]+$/;
export const HAS_KANJI = /[㐀-鿿豈-﫿々〆ヶ]/;
export const hira = (s) => s.replace(/[ァ-ヶ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0x60));

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
export function splitOkurigana(surface, reading) {
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

export function romanize(reading) {
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

/** A small tsu at the end of a token doubles the next token's first consonant (きっ|と -> kit to). */
export function fixGeminates(wr) {
  for (let k = 0; k < wr.length; k++) {
    if (wr[k].endsWith("'")) {
      const nxt = wr.slice(k + 1).find((x) => x) || "";
      if (/^[b-df-hj-np-tv-z]/.test(nxt)) wr[k] = wr[k].slice(0, -1) + (nxt.startsWith("ch") ? "t" : nxt[0]);
    }
  }
  return wr;
}

/** Words already known from data files, so new lines reuse their glosses and "known" marks. */
function existingWords(datasets) {
  // most specific first: same spelling, reading and part of speech (ない the auxiliary is not ない the adjective)
  const exact = new Map(), byLemmaReading = new Map(), byLemma = new Map();
  const addUnique = (map, k, w) => { if (!map.has(k)) map.set(k, w); else if (map.get(k) !== w) map.set(k, null); };
  for (const ds of datasets) {
    for (const w of ds.words) {
      if (!exact.has(`${w.lemma}|${w.reading}|${w.upos}`)) exact.set(`${w.lemma}|${w.reading}|${w.upos}`, w);
      addUnique(byLemmaReading, `${w.lemma}|${w.reading}`, w);
      addUnique(byLemma, w.lemma, w);
    }
  }
  return (lemma, reading, upos) => exact.get(`${lemma}|${reading}|${upos}`)
    || byLemmaReading.get(`${lemma}|${reading}`) || byLemma.get(lemma) || null;
}

/** Lines of text -> [{seg, wr, romaji}] in the data file format. `words` / `wordIndex` (key -> index) are the
 * word list the seg indexes point into; new words are appended to it. `datasets`: data files to reuse words from. */
export async function buildJapanese(texts, words, wordIndex, datasets) {
  const tokenizer = await japaneseTokenizer();
  const lookup = existingWords(datasets);
  return texts.map((text) => {
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
      if (u !== "PUNCT" && /[ぁ-ゖァ-ヺー㐀-鿿豈-﫿]/.test(lemma)) {
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
    fixGeminates(wr);
    return { seg, wr, romaji: wr.filter((x) => x).join(" ") };
  });
}
