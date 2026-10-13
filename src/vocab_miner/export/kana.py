"""Kana deck for beginners: hiragana and katakana, spoken aloud, with the kanji each one came from.

Order (default "rows"): the gojuon chart row by row (あいうえお, かきくけこ ...), then voiced kana, then
combinations (きゃ, ティ ...); rows share a consonant and the vowels always run a-i-u-e-o, which is easier to
remember than a scattered order. order="frequency" sorts each stage by how often the kana appears in your
material instead. Either way each card shows example words from your vocabulary that contain the kana.
"""
from __future__ import annotations

import hashlib
import html
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from ..model import VocabEntry
from ..tokenizers.ja import _DIGRAPHS, _MONO, HepburnRomanizer, kata_to_hira

# v2: Origin and Speech fields, spoken front
MODEL_NAME = "vocab-miner kana v2"
FIELDS = ["Key", "Kana", "Romaji", "Script", "Note", "Examples", "Count", "Order", "Origin", "Speech"]

NOTES = {
    "は": "當助詞（主題標記）時唸 wa，例如「僕は」boku wa",
    "へ": "當助詞（方向）時唸 e",
    "を": "唸 o，幾乎只用在助詞（標示受詞）",
    "ん": "鼻音 n；後面接母音或 y 時拼音寫成 n'",
    "ぢ": "和 じ 同音（ji），很少用",
    "づ": "和 ず 同音（zu），很少用",
    "っ": "促音：下一個子音停頓一拍，拼音寫成雙子音（がっこう gakkou）",
    "ー": "長音：把前一個母音拉長（ラーメン raamen）",
}

# the front speaks the kana as soon as it is shown; AnkiDroid also shows a replay button
FRONT = """<div class="kana">{{Kana}}</div><div class="script">{{Script}}</div>
{{#Speech}}{{tts ja_JP:Speech}}{{/Speech}}"""
BACK = """<div class="kana">{{Kana}}</div><div class="script">{{Script}}</div>
<hr id="answer">
<div class="romaji">{{Romaji}}</div>
{{#Origin}}<div class="origin">{{Origin}}</div>{{/Origin}}
{{#Note}}<div class="note">{{Note}}</div>{{/Note}}
{{#Examples}}<div class="examples">{{Examples}}</div>{{/Examples}}
{{#Count}}<div class="count">在你的素材裡出現 {{Count}} 次</div>{{/Count}}
"""
CSS = """
.card { font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", sans-serif; text-align: center;
        font-size: 20px; color: #1f1f1f; background: #fafafa; }
.nightMode.card, .night_mode .card { color: #e8e8e8; background: #1e1e1e; }
.kana { font-size: 5em; line-height: 1.2; margin-top: .2em; }
.script { font-size: .8em; color: #888; }
.romaji { font-size: 2em; color: #2563eb; letter-spacing: .05em; }
.nightMode .romaji, .night_mode .romaji { color: #93c5fd; }
.origin { font-size: 1em; margin: .3em 0; }
.origin .kanji { font-size: 1.6em; vertical-align: middle; margin: 0 .15em; }
.note { font-size: .9em; color: #b45309; margin: .4em 0; }
.examples { margin-top: .8em; font-size: 1em; line-height: 1.9; }
.examples b { color: #2563eb; }
.nightMode .examples b, .night_mode .examples b { color: #93c5fd; }
.examples .ro { color: #888; font-size: .8em; }
.examples .zh { font-size: .85em; }
.count { margin-top: .6em; font-size: .75em; color: #888; }
"""


def _stable_id(name: str) -> int:
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16) + (1 << 30)


def _hira_to_kata(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def _base_and_mark(c: str) -> tuple[str, str | None]:
    """が -> (か, dakuten), ぱ -> (は, handakuten), か -> (か, None)."""
    d = unicodedata.normalize("NFD", c)
    if "゙" in d:
        return d.replace("゙", ""), "濁點（゛）"
    if "゚" in d:
        return d.replace("゚", ""), "半濁點（゜）"
    return c, None


def load_origins() -> dict[str, str]:
    text = resources.files("vocab_miner.data").joinpath("kana_origins_ja.tsv").read_text(encoding="utf-8")
    return dict(ln.split("\t")[:2] for ln in text.splitlines() if ln.strip() and not ln.startswith("#"))


@dataclass
class KanaUnit:
    kana: str
    script: str            # "hiragana" / "katakana"
    stage: int             # 0 basic, 1 voiced and special marks, 2 combinations
    romaji: str
    position: int = 0      # place in the gojuon chart
    count: int = 0
    examples: list[str] = field(default_factory=list)
    origin: str = ""


def hiragana_units() -> list[tuple[str, int]]:
    """(kana, stage) in chart order: 46 basic, 25 voiced + small tsu, 33 combinations."""
    out = []
    for c in _MONO:                                   # code-point order is the gojuon chart order
        name = unicodedata.name(c)
        if "SMALL" in name or c in ("ゐ", "ゑ", "ゔ"):
            continue
        out.append((c, 1 if _base_and_mark(c)[1] else 0))
    out.append(("っ", 1))
    # yoon: an i-row kana + small ya/yu/yo (きゃ, しゅ, ちょ ...); ぢゃ/ぢゅ/ぢょ sound like じゃ.. and are left out
    out += [(d, 2) for d in _DIGRAPHS
            if d[1] in "ゃゅょ" and _MONO[d[0]].endswith("i") and len(_MONO[d[0]]) > 1 and d[0] != "ぢ"]
    return out


def katakana_units() -> list[tuple[str, int]]:
    out = [(_hira_to_kata(k), stage) for k, stage in hiragana_units()]
    out.append(("ー", 1))
    out += [(_hira_to_kata(d), 2) for d in _DIGRAPHS if d[1] in "ぁぃぅぇぉ"]   # loanword sounds (ティ, ファ ...)
    return out


def count_kana(texts: Iterable[str], units: Sequence[str]) -> Counter:
    """Occurrences of each unit as written (combinations counted as a pair)."""
    pairs = {u for u in units if len(u) == 2}
    c: Counter = Counter()
    for t in texts:
        for i, ch in enumerate(t):
            c[ch] += 1
            if t[i:i + 2] in pairs:
                c[t[i:i + 2]] += 1
    return c


def _romaji(unit: str, romanizer: HepburnRomanizer) -> str:
    if unit in ("っ", "ッ"):
        return "（促音）"
    if unit == "ー":
        return "（長音）"
    return romanizer.romanize(unit)


def _origin(unit: str, script: str, origins: dict[str, str]) -> str:
    """Where the kana comes from, as HTML: the source kanji, or the kana it is built from."""
    if len(unit) == 2:
        return f"＝ {html.escape(unit[0])} ＋ 小 {html.escape(unit[1])}"
    base, mark = _base_and_mark(unit)
    if mark:
        return f"＝ {html.escape(base)} ＋ {mark}"
    kanji = origins.get(unit)
    if not kanji:
        return ""
    how = "整個字的草書" if script == "hiragana" else "取這個字的一部分"
    return f'字源：<span class="kanji">{html.escape(kanji)}</span>（{how}）'


def _example_html(e: VocabEntry, unit: str) -> str:
    """One example line: written form (with the kana bold), reading, romaji, Chinese gloss."""
    def bold(s: str) -> str:
        return html.escape(s).replace(html.escape(unit), f"<b>{html.escape(unit)}</b>")

    word = bold(e.lemma) if unit in e.lemma else html.escape(e.lemma)
    reading = ""
    if e.reading and e.reading != e.lemma:
        reading = f"（{bold(e.reading) if unit in e.reading else html.escape(e.reading)}）"
    zh = html.escape(e.gloss.get("zh-Hant", "").split("；")[0])
    return f'{word}{reading} <span class="ro">{html.escape(e.romaji or "")}</span> <span class="zh">{zh}</span>'


def build_units(texts: Sequence[str], entries: Sequence[VocabEntry], examples: int = 3,
                order: str = "rows") -> list[KanaUnit]:
    if order not in ("rows", "frequency"):
        raise ValueError(f"order must be rows or frequency, got {order!r}")
    romanizer = HepburnRomanizer()
    origins = load_origins()
    units: list[KanaUnit] = []
    for script, defs in (("hiragana", hiragana_units()), ("katakana", katakana_units())):
        counts = count_kana(texts, [k for k, _ in defs])
        for pos, (kana, stage) in enumerate(defs):
            n = counts[kana]
            if stage == 2 and n == 0:
                continue                                   # combinations only when they actually occur
            units.append(KanaUnit(kana, script, stage, _romaji(kana, romanizer), pos, n,
                                  origin=_origin(kana, script, origins)))
    ranked = sorted(entries, key=lambda e: e.rank)
    for u in units:
        if u.script == "hiragana":
            written = [e for e in ranked if u.kana in e.lemma]
            by_reading = [e for e in ranked if u.kana not in e.lemma and u.kana in (e.reading or "")]
            pool = written + by_reading
        else:
            pool = [e for e in ranked if u.kana in e.lemma]
        seen, chosen = set(), []
        for e in pool:
            if e.lemma not in seen and e.lemma.strip("〜") == e.lemma:
                seen.add(e.lemma)
                chosen.append(e)
            if len(chosen) == examples:
                break
        u.examples = [_example_html(e, u.kana) for e in chosen]
    within = (lambda u: u.position) if order == "rows" else (lambda u: (-u.count, u.position))
    units.sort(key=lambda u: (u.script != "hiragana", u.stage, within(u)))
    return units


class KanaDeckExporter:
    def __init__(self, deck: str = "五十音"):
        self.deck = deck

    def export(self, units: Sequence[KanaUnit], out: Path) -> int:
        import genanki

        model = genanki.Model(_stable_id(MODEL_NAME), MODEL_NAME, fields=[{"name": f} for f in FIELDS],
                              templates=[{"name": "Kana → romaji", "qfmt": FRONT, "afmt": BACK}], css=CSS,
                              sort_field_index=FIELDS.index("Order"))
        decks = {s: genanki.Deck(_stable_id(f"deck:{self.deck}:{s}"), f"{self.deck}::{label}")
                 for s, label in (("hiragana", "平假名"), ("katakana", "片假名"))}
        for i, u in enumerate(units, 1):
            note_text = NOTES.get(kata_to_hira(u.kana) if u.kana != "ー" else "ー", "")
            speech = "" if u.kana in ("っ", "ッ", "ー") else u.kana     # a lone small tsu / long mark has no sound
            fields = [f"{u.script}:{u.kana}", u.kana, u.romaji, "平假名" if u.script == "hiragana" else "片假名",
                      html.escape(note_text), "<br>".join(u.examples), str(u.count) if u.count else "", str(i),
                      u.origin, speech]
            decks[u.script].add_note(genanki.Note(model=model, fields=fields, due=i,
                                                  guid=genanki.guid_for("vocab-miner-kana", u.script, u.kana)))
        out.parent.mkdir(parents=True, exist_ok=True)
        genanki.Package(list(decks.values())).write_to_file(str(out))
        return len(units)
