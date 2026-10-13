"""Japanese: fugashi + UniDic tokenizer, Hepburn romanizer.

Install with `uv sync --extra ja` (fugashi, unidic-lite).
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from ..model import Token

KATAKANA = re.compile(r"[ァ-ヶ]")
KANA_ONLY = re.compile(r"[ぁ-ゖァ-ヺー]+")
# a lemma worth learning contains kana or kanji (drops punctuation, digits, latin-script words)
WORD = re.compile(r"[ぁ-ゖァ-ヺー㐀-鿿豈-﫿々〆ヵヶ]")


def kata_to_hira(s: str) -> str:
    return KATAKANA.sub(lambda m: chr(ord(m.group()) - 0x60), s)


# ---------- POS ----------

def upos(pos1: str, pos2: str) -> str:
    """UniDic pos1/pos2 -> Universal POS (close to UD Japanese conventions)."""
    if pos1 == "名詞":
        return {"固有名詞": "PROPN", "数詞": "NUM"}.get(pos2, "NOUN")
    if pos1 == "助詞":
        return {"接続助詞": "SCONJ", "準体助詞": "SCONJ", "終助詞": "PART"}.get(pos2, "ADP")
    if pos1 == "接尾辞":
        return {"形容詞的": "ADJ", "形状詞的": "ADJ", "動詞的": "VERB"}.get(pos2, "NOUN")
    return {
        "代名詞": "PRON", "形状詞": "ADJ", "形容詞": "ADJ", "連体詞": "DET", "副詞": "ADV",
        "接続詞": "CCONJ", "感動詞": "INTJ", "動詞": "VERB", "助動詞": "AUX", "接頭辞": "NOUN",
        "記号": "SYM", "補助記号": "PUNCT",
    }.get(pos1, "X")


POS_LABELS_ZH = {
    "名詞": "名詞", "代名詞": "代名詞", "動詞": "動詞", "形容詞": "い形容詞", "形状詞": "な形容詞",
    "副詞": "副詞", "連体詞": "連體詞", "接続詞": "接續詞", "感動詞": "感嘆詞", "助詞": "助詞",
    "助動詞": "助動詞", "接頭辞": "接頭詞", "接尾辞": "接尾詞",
}


def pos_label(pos_native: str) -> str:
    """Learner-facing POS name in Traditional Chinese, from the UniDic POS string."""
    parts = pos_native.split("-")
    if parts[:2] == ["名詞", "固有名詞"]:
        return "專有名詞"
    if parts[:2] == ["名詞", "数詞"]:
        return "數詞"
    return POS_LABELS_ZH.get(parts[0], parts[0])


# ---------- tokenizer ----------

def _clean_lemma(lemma: str) -> str:
    # UniDic marks loanwords with their source: "アイドル-idol"
    return lemma.split("-", 1)[0] if "-" in lemma and not lemma.startswith("-") else lemma


def _modern_lemma(lemma: str, base: str, lemma_reading: str | None, surface: str) -> tuple[str, str, str | None]:
    """Learner-friendly dictionary forms.

    - UniDic files 信じる/感じる under the classical サ変 lemma 信ずる/感ずる; use the modern -じる verb
      when the text actually uses a -じ form.
    - Potential verbs (会える) have the plain verb (会う) as lemma but keep the potential spelling as base;
      show the plain verb so base and lemma_reading agree.
    """
    if lemma.endswith("ずる") and "じ" in surface:
        lemma = base = lemma[:-2] + "じる"
        lemma_reading = lemma_reading[:-2] + "じる" if lemma_reading else None
    elif base != lemma and base[:1] == lemma[:1] and re.match(r"[㐀-鿿]", base):
        base = lemma
    return lemma, base, lemma_reading


class JapaneseTokenizer:
    lang = "ja"
    version = "4"           # bump when tokenization or reading alignment changes, so indexes get rebuilt
    word_pattern = WORD

    def __init__(self, names: Iterable[str] = ()):
        import fugashi  # optional dependency: uv sync --extra ja

        self._tagger = fugashi.Tagger()
        self.names = sorted({n.strip() for n in names if n.strip()}, key=len, reverse=True)
        self._names_re = re.compile("|".join(map(re.escape, self.names))) if self.names else None

    def with_names(self, names: Iterable[str]) -> JapaneseTokenizer:
        """Same tagger, different protected-name list (names are per source)."""
        clone = object.__new__(JapaneseTokenizer)
        clone._tagger = self._tagger
        clone.names = sorted({n.strip() for n in names if n.strip()}, key=len, reverse=True)
        clone._names_re = re.compile("|".join(map(re.escape, clone.names))) if clone.names else None
        return clone

    def tokenize(self, text: str) -> list[Token]:
        if not self._names_re:
            return self._tag(text, 0)
        out: list[Token] = []
        pos = 0
        for m in self._names_re.finditer(text):
            out += self._tag(text[pos:m.start()], pos)
            name = m.group()
            reading = kata_to_hira(name) if KANA_ONLY.fullmatch(name) else None
            out.append(Token(surface=name, lemma=name, reading=reading, pos="PROPN",
                             pos_native="名詞-固有名詞-名前", start=m.start(), end=m.end(), is_proper=True,
                             base=name, lemma_reading=reading))
            pos = m.end()
        out += self._tag(text[pos:], pos)
        return out

    def _tag(self, text: str, offset: int) -> list[Token]:
        tokens: list[Token] = []
        cursor = 0
        for w in self._tagger(text):
            surface = w.surface
            start = text.find(surface, cursor)
            if start < 0:
                start = cursor
            end = start + len(surface)
            cursor = end
            f = w.feature
            if f.pos1 == "空白" or not surface.strip():
                continue
            pos_native = "-".join(p for p in (f.pos1, f.pos2, f.pos3, f.pos4) if p and p != "*")
            u = upos(f.pos1, f.pos2)
            if f.lemma:          # known word
                lemma = _clean_lemma(f.lemma)
                base = f.orthBase or surface
                reading = kata_to_hira(f.kana) if f.kana else None
                lemma_reading = kata_to_hira(f.lForm) if f.lForm else None
                lemma, base, lemma_reading = _modern_lemma(lemma, base, lemma_reading, surface)
            else:                # unknown to the dictionary
                lemma = base = surface
                reading = lemma_reading = kata_to_hira(surface) if KANA_ONLY.fullmatch(surface) else None
            tokens.append(Token(surface=surface, lemma=lemma, reading=reading, pos=u, pos_native=pos_native,
                                start=offset + start, end=offset + end, is_proper=(u == "PROPN"),
                                base=base, lemma_reading=lemma_reading))
        return tokens

    def tokenize_with_hint(self, text: str, hint: str | None) -> list[Token]:
        tokens = self.tokenize(text)
        return align_readings(tokens, hint) if hint else tokens

    @staticmethod
    def pos_label(token_or_pos_native: Token | str) -> str:
        pn = token_or_pos_native if isinstance(token_or_pos_native, str) else token_or_pos_native.pos_native
        return pos_label(pn)


# ---------- reading correction from source-provided readings ----------

HINT_NOISE = re.compile(r"[^ぁ-ゖァ-ヺーA-Za-z0-9]")
KANJI_HEAD = re.compile(r"^([^ぁ-ゖァ-ヺー]+)([ぁ-ゖァ-ヺー]*)$")


CANNOT_START = {c for c in map(chr, range(0x3041, 0x3097)) if "SMALL" in unicodedata.name(c, "")} | {"\u30fc"}


def _loose(t: Token) -> re.Pattern:
    """Kana runs literally, other runs (kanji, digits) as anything."""
    runs = re.findall(r"[ぁ-ゖァ-ヺー]+|[^ぁ-ゖァ-ヺー]+", t.surface)
    return re.compile("".join(re.escape(kata_to_hira(r)) if KANA_ONLY.fullmatch(r) else ".+" for r in runs))


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def align_readings(tokens: list[Token], hint: str) -> list[Token]:
    """Replace token readings with the ones implied by a source reading (e.g. lyrics furigana).

    Dynamic programming over the hint: kana must match literally; for other characters the split that stays
    closest (edit distance) to the tokenizer's own readings wins. If nothing fits, tokens are returned unchanged.
    Uninflected tokens (and simple kanji+okurigana inflections) also get a corrected lemma reading.
    """
    words = [t for t in tokens if t.pos not in ("PUNCT", "SYM") and re.search(r"\w", t.surface)]
    if not words:
        return tokens
    target = HINT_NOISE.sub("", kata_to_hira(hint)).lower()
    n = len(target)
    INF = float("inf")
    # best[i][pos] = (cost, previous pos) after aligning words[:i] to target[:pos]
    best: list[dict[int, tuple[float, int]]] = [{0: (0.0, -1)}] + [{} for _ in words]
    for i, t in enumerate(words):
        for start, (cost, _) in best[i].items():
            if KANA_ONLY.fullmatch(t.surface) or re.fullmatch(r"[A-Za-z]+", t.surface):
                lit = kata_to_hira(t.surface).lower()
                if target.startswith(lit, start):
                    _relax(best[i + 1], start + len(lit), cost, start)
                continue
            orig = t.reading or ""
            loose = _loose(t)
            max_len = max(len(orig) + 4, 4 * len(t.surface))
            if start < n and target[start] in CANNOT_START:
                continue                       # no word starts with a small kana or a long-vowel mark
            for end in range(start + 1, min(n, start + max_len) + 1):
                seg = target[start:end]
                if loose.fullmatch(seg):
                    # changing a token costs 1 plus the edit distance, so fewer changed tokens win ties
                    change = 0 if seg == orig else 1 + _edit_distance(seg, orig)
                    _relax(best[i + 1], end, cost + change, start)
    if n not in best[-1] or best[-1][n][0] == INF:
        return tokens
    spans, pos = [], n
    for i in range(len(words), 0, -1):
        prev = best[i][pos][1]
        spans.append((prev, pos))
        pos = prev
    spans.reverse()
    fixed = {}
    for t, (s0, s1) in zip(words, spans, strict=True):
        r = target[s0:s1]
        if r == t.reading or not re.fullmatch(r"[ぁ-ゖー]+", r) or re.search(r"\d", t.surface):
            continue
        # a voicing-only change (rendaku: け -> げ in compounds) changes the sound here, not the word
        sandhi = t.reading is not None and _devoice(r) == _devoice(t.reading)
        lemma_reading = t.lemma_reading if sandhi else _lemma_reading(t, r)
        fixed[id(t)] = Token(**{**t.__dict__, "reading": r, "lemma_reading": lemma_reading})
    return [fixed.get(id(t), t) for t in tokens]


def _devoice(s: str) -> str:
    """Drop (han)dakuten: voiced kana decompose into base kana + U+3099 / U+309A."""
    return unicodedata.normalize("NFC", "".join(c for c in unicodedata.normalize("NFD", s)
                                                 if c not in "\u3099\u309a"))


def _relax(cell: dict[int, tuple[float, int]], pos: int, cost: float, prev: int) -> None:
    if pos not in cell or cost < cell[pos][0]:
        cell[pos] = (cost, prev)


def _lemma_reading(t: Token, reading: str) -> str | None:
    base = t.base or t.lemma
    if t.surface == base:
        return reading
    ms, mb = KANJI_HEAD.match(t.surface), KANJI_HEAD.match(base)
    if ms and mb and ms.group(1) == mb.group(1) and reading.endswith(kata_to_hira(ms.group(2))):
        stem = reading[: len(reading) - len(ms.group(2))] if ms.group(2) else reading
        return stem + kata_to_hira(mb.group(2))
    return t.lemma_reading


# ---------- romanizer ----------

# Hepburn romaji for U+3041..U+3096 in code-point order (small kana carry their vowel; small tsu is handled apart)
_BLOCK_ROMAJI = (
    "a a i i u u e e o o ka ga ki gi ku gu ke ge ko go sa za shi ji su zu se ze so zo ta da chi ji - tsu zu te de "
    "to do na ni nu ne no ha ba pa hi bi pi fu bu pu he be pe ho bo po ma mi mu me mo ya ya yu yu yo yo "
    "ra ri ru re ro wa wa i e o n vu ka ke"
)
_BLOCK = _BLOCK_ROMAJI.split()
_MONO = {chr(0x3041 + i): r for i, r in enumerate(_BLOCK) if r != "-"}
_SMALL = {c for c in _MONO if "SMALL" in unicodedata.name(c)}


def _combine(base: str, small: str) -> str | None:
    """Romaji for a kana followed by a small kana: kyo, sha, fa, ti, wi, tsa, kwa ..."""
    b, v = _MONO[base], _MONO[small]
    if v not in ("a", "i", "u", "e", "o", "ya", "yu", "yo") or b in ("a", "e", "o"):
        return None
    cons = b.rstrip("aiueo")
    if v in ("ya", "yu", "yo"):
        if b.endswith("i") and b not in ("i",):
            return (cons if cons in ("sh", "ch", "j") else cons + "y") + v[1]
        return None if b in ("i", "u") else cons + v
    if b == "u":
        return "w" + v
    if b == "i":
        return "y" + v if v == "e" else None
    if b in ("ku", "gu") and v == "a":
        return cons + "wa"
    return cons + v


_DIGRAPHS = {base + small: r for base in _MONO if base not in _SMALL for small in _SMALL
             if (r := _combine(base, small)) is not None}
_PARTICLES = {"は": "wa", "へ": "e", "を": "o"}
_MACRONS = {"aa": "ā", "ii": "ī", "uu": "ū", "ee": "ē", "oo": "ō", "ou": "ō"}


class HepburnRomanizer:
    """Hepburn for learners: し=shi, ち=chi, つ=tsu, ふ=fu, じ=ji.

    macrons=False (default) keeps long vowels as written (とうきょう -> toukyou) so the spelling maps
    one-to-one onto kana. ん before a vowel or y is written n' (きんようび -> kin'youbi).
    """

    lang = "ja"

    def __init__(self, macrons: bool = False):
        self.macrons = macrons

    def romanize(self, reading: str) -> str:
        s = kata_to_hira(reading)
        out: list[str] = []
        i, geminate, after_n = 0, False, False
        while i < len(s):
            two, ch = s[i:i + 2], s[i]
            if two in _DIGRAPHS:
                syl, i = _DIGRAPHS[two], i + 2
            elif ch in _MONO:
                syl, i = _MONO[ch], i + 1
            elif ch == "っ":
                geminate, i = True, i + 1
                continue
            elif ch == "ー":
                syl = next((c for c in reversed("".join(out)) if c in "aeiou"), "")
                i += 1
            else:
                syl, i = ch, i + 1
            if geminate and syl and syl[0] not in "aeioun'":
                syl = "t" + syl if syl.startswith("ch") else syl[0] + syl
            geminate = False
            if after_n and syl[:1] in ("a", "i", "u", "e", "o", "y"):
                out[-1] = "n'"
            after_n = ch == "ん" and syl == "n"
            out.append(syl)
        if geminate:
            out.append("'")          # trailing small tsu (glottal stop), e.g. あっ -> a'
        text = "".join(out)
        if self.macrons:
            for k, v in _MACRONS.items():
                text = text.replace(k, v)
        return text

    def romanize_word(self, lemma: str, reading: str, upos: str) -> str:
        """Dictionary-form romanization; particles are spelled as pronounced (は -> wa)."""
        if upos in ("ADP", "PART", "SCONJ") and lemma in _PARTICLES:
            return _PARTICLES[lemma]
        return self.romanize(reading)

    def romanize_token(self, token: Token) -> str:
        if token.pos_native.startswith("助詞") and token.surface in _PARTICLES:
            return _PARTICLES[token.surface]
        return self.romanize(token.reading or token.surface)

    def romanize_tokens(self, tokens: Sequence[Token]) -> str:
        return " ".join(self.romanize_token(t) for t in tokens if t.pos != "PUNCT")
