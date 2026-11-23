"""Kana chart (五十音表) with how often each sound occurs in a sing-along data file.

    uv run --with pillow python scripts/kana_chart.py out/web/songs.json -o kana_chart.png
    ... --theme light          white paper, for printing (also: dark = default, sepia)
    ... --summary              add the make-up of all sounds at the bottom

Counts the readings of the lines (kanji by their ruby reading, kana as written); hiragana and katakana of one
sound share a cell, with the dakuon (が) and handakuon (ぱ) on its right. Contracted sounds (きゃ) follow
below in a table laid out the same way. A contracted sound (きゃ) or a foreign-sound pair (ファ)
counts as one sound, not as き + ゃ. Percentages are of all sounds. PNG keeps the text sharp; use a .jpg name for JPEG.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# (row label, kana per column with " " for an empty cell, romaji per column with "-" for an empty cell and "_"
# for a space inside one)
PLAIN = [("あ行", "あいうえお", "a i u e o"), ("か行", "かきくけこ", "ka ki ku ke ko"),
         ("さ行", "さしすせそ", "sa shi su se so"), ("た行", "たちつてと", "ta chi tsu te to"),
         ("な行", "なにぬねの", "na ni nu ne no"), ("は行", "はひふへほ", "ha hi fu he ho"),
         ("ま行", "まみむめも", "ma mi mu me mo"), ("や行", "や ゆ よ", "ya - yu - yo"),
         ("ら行", "らりるれろ", "ra ri ru re ro"), ("わ行", "わ   を", "wa - - - wo"), ("ん", "ん    ", "n - - - -")]
VOICED = [("が行", "がぎぐげご", "ga gi gu ge go"), ("ざ行", "ざじずぜぞ", "za ji zu ze zo"),
          ("だ行", "だぢづでど", "da ji_(di) zu_(du) de do"), ("ば行", "ばびぶべぼ", "ba bi bu be bo"),
          ("ぱ行", "ぱぴぷぺぽ", "pa pi pu pe po")]
# contracted sounds: (head kana, romaji start); voiced ones go in the cell of the plain one
YOON = [("き", "ky", "ki"), ("し", "sh", "shi"), ("ち", "ch", "chi"), ("に", "ny", "ni"), ("ひ", "hy", "hi"),
        ("み", "my", "mi"), ("り", "ry", "ri")]
YOON_VOICED = {"き": [("ぎ", "gy")], "し": [("じ", "j")], "ひ": [("び", "by"), ("ぴ", "py")]}
YOON_HEAD = set("きしちにひみりぎじぢびぴ")
COLS = ["あ段", "い段", "う段", "え段", "お段"]
YOON_COLS = [("ゃ", "ya"), ("ゅ", "yu"), ("ょ", "yo")]
YOON_TAIL = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
FOREIGN_TAIL = set("ぁぃぅぇぉ")
SMALL = set("ぁぃぅぇぉっゃゅょゎゕゖ")
FONTS = ["C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/msgothic.ttc",
         "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]
MONO = ["C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]

THEMES = {   # colors per theme
    "dark": {"paper": "#16161a", "cell": "#202026", "empty": "#1b1b20", "label": "#26262d", "ink": "#ececf1",
            "muted": "#9a9aa6", "line": "#3a3a46", "kata": "#b69cff", "roma": "#ff7aa2", "accent": "#ff7aa2"},
    "light": {"paper": "#ffffff", "cell": "#ffffff", "empty": "#fafafa", "label": "#f4f4f4", "ink": "#222222",
             "muted": "#7a7a7a", "line": "#e3c4cf", "kata": "#7b3fd0", "roma": "#d1235b", "accent": "#d1235b"},
    "sepia": {"paper": "#f4ecd8", "cell": "#fbf5e6", "empty": "#efe5cc", "label": "#e9dfc4", "ink": "#3b2f22",
             "muted": "#8a7a62", "line": "#d8c6a0", "kata": "#7a4f9a", "roma": "#a8432c", "accent": "#a8432c"},
}

KINDS = {"plain": "清音（46 音）", "voiced": "濁音（が、ざ、だ、ば行）", "semi": "半濁音（ぱ行）",
         "yoon": "拗音（きゃ、しゅ、ちょ…）", "sokuon": "促音 っ", "long": "長音 ー",
         "foreign": "外來音（ファ、ティ、ウェ…）", "other": "其他小字"}


def to_hiragana(ch: str) -> str:
    return chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch


def to_katakana(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "\u3041" <= c <= "\u3096" else c for c in s)


def sounds(reading: str):
    """The sounds of a reading, in hiragana: single kana, contracted pairs (きゃ), foreign pairs (ふぁ), っ and ー."""
    hs = [to_hiragana(c) for c in reading]
    i = 0
    while i < len(hs):
        c = hs[i]
        nxt = hs[i + 1] if i + 1 < len(hs) else ""
        if c == "ー":
            yield c
        elif "\u3041" <= c <= "\u3096":
            if c not in SMALL and (nxt in YOON_TAIL or nxt in FOREIGN_TAIL):
                yield c + nxt
                i += 1
            else:
                yield c
        i += 1


def kind(s: str) -> str:
    if s == "ー":
        return "long"
    if s == "っ":
        return "sokuon"
    if len(s) == 2:
        return "yoon" if s[1] in YOON_TAIL and s[0] in YOON_HEAD else "foreign"
    if s in SMALL:
        return "other"
    base = unicodedata.normalize("NFD", s)
    return "voiced" if "\u3099" in base else "semi" if "\u309a" in base else "plain"


def count_sounds(data: dict) -> tuple[Counter, Counter]:
    """(counts by sound, counts by kind) over the readings of every line."""
    by_sound, by_kind = Counter(), Counter()
    for doc in data["docs"]:
        for line in doc["lines"]:
            for s in sounds("".join(seg[1] or seg[0] for seg in line["seg"])):
                by_sound[s] += 1
                by_kind[kind(s)] += 1
    return by_sound, by_kind


def font(paths: list[str], size: int, user: str | None = None):
    for p in [user, *paths]:
        if p and Path(p).is_file():
            return ImageFont.truetype(p, size)
    raise SystemExit("no suitable font found: pass --font path/to/japanese-font.ttc")


def table(rows) -> list[tuple[str, list]]:
    """[(label, [(kana, romaji) or None per column])] from (label, kana, romaji) rows like PLAIN."""
    return [(label, [None if k == " " else (k, r) for k, r in zip(kana, romas(roma))]) for label, kana, roma in rows]


def romas(roma: str) -> list[str]:
    return [r.replace("_", " ") for r in roma.split()]


def plain_variants() -> dict:
    """Plain kana -> its dakuon / handakuon [(kana, romaji)]: が in the cell of か, ば and ぱ in the cell of は."""
    out: dict = {}
    for plain, row in [("かきくけこ", 0), ("さしすせそ", 1), ("たちつてと", 2), ("はひふへほ", 3), ("はひふへほ", 4)]:
        _, kana, roma = VOICED[row]
        for k, v, r in zip(plain, kana, romas(roma)):
            out.setdefault(k, []).append((v, r))
    return out


def yoon_rows() -> tuple[list, dict]:
    """The contracted-sound table (rows き…り; ゃゅょ in the columns of や, ゆ, よ, the other two empty) and its voiced variants (ぎゃ in the cell of きゃ)."""
    rows, variants = [], {}
    for head, roma, plain in YOON:
        ya, yu, yo = [(head + tail, roma + vowel) for tail, vowel in YOON_TAIL.items()]
        rows.append(((head, plain), [ya, None, yu, None, yo]))     # under や, ゆ, よ of the kana chart
        for tail, vowel in YOON_TAIL.items():
            if head in YOON_VOICED:
                variants[head + tail] = [(v + tail, r + vowel) for v, r in YOON_VOICED[head]]
    return rows, variants


class Chart:
    M, LW, CH, CW = 60, 150, 196, 480   # margin, row-label width, cell height, cell width of the kana chart
    WIDTH = 2 * M + LW + 5 * CW

    def __init__(self, data: dict, theme: str, font_path: str | None):
        self.t = THEMES[theme]
        self.title, self.n_docs = data.get("title") or "songs", len(data["docs"])
        self.counts, self.kinds = count_sounds(data)
        self.total = sum(self.kinds.values()) or 1
        self.digits = len(f"{max(self.counts.values(), default=0):,}")   # pad counts so every cell lines up
        self.pct_w = len(f"{max(self.counts.values(), default=0) / self.total * 100:.2f}")
        self.font_path = font_path
        self._fonts: dict = {}
        try:
            self.mono, self.mono_s = font(MONO, 26), font(MONO, 21)
        except SystemExit:
            self.mono, self.mono_s = self.jp(26), self.jp(21)

    def jp(self, size: int):
        if size not in self._fonts:
            self._fonts[size] = font(FONTS, size, self.font_path)
        return self._fonts[size]

    def numbers(self, cx: float, y: float, n: int, size: int = 26) -> None:
        """A small block centered on (cx, y): the count above the percentage, in a monospace font. Both lines are
        padded to the same width (the widest values) so they right-align and every cell lines up."""
        w = max(self.digits, self.pct_w + 1)
        mono, half = self.mono_font(size), size * 0.6
        self.d.text((cx, y - half), f"{n:>{w},}", font=mono, fill=self.t["ink"], anchor="mm")
        self.d.text((cx, y + half), f"{n / self.total * 100:{w - 1}.2f}%", font=mono, fill=self.t["ink"], anchor="mm")

    def kana_pair(self, cx: float, y: float, hira: str, size: int) -> None:
        """Hiragana and the katakana smaller beside it, centered on cx."""
        d, t = self.d, self.t
        big, small = self.jp(size), self.jp(int(size * 0.55))
        kata = to_katakana(hira)
        gap = size * 0.1
        w1, w2 = d.textlength(hira, font=big), d.textlength(kata, font=small)
        left = cx - (w1 + gap + w2) / 2
        d.text((left, y), hira, font=big, fill=t["ink"], anchor="lm")
        d.text((left + w1 + gap, y + size * 0.1), kata, font=small, fill=t["kata"], anchor="lm")

    def mono_font(self, size: int):
        try:
            return font(MONO, size)
        except SystemExit:
            return self.jp(size)

    def main_block(self, cx: float, y: int, kana: str, roma: str, size: int, num_size: int = 26) -> None:
        """Kana, romaji, then the count / percentage block."""
        ch = self.CH
        self.kana_pair(cx, y + ch * 0.27, kana, size)
        self.d.text((cx, y + ch * 0.52), roma, font=self.jp(26), fill=self.t["roma"], anchor="mm")
        self.numbers(cx, y + ch * 0.77, self.counts.get(kana, 0), num_size)

    def side_block(self, cx: float, y: int, kana: str, roma: str, size: int, width: float) -> None:
        """A dakuon / handakuon in a narrow column: kana, romaji, count, percentage on lines of their own. The kana
        shrink to fit the width."""
        d, t, ch, n = self.d, self.t, self.CH, self.counts.get(kana, 0)
        while size > 20 and (d.textlength(kana, font=self.jp(size)) * (1 + 0.55) + size * 0.1) > width - 16:
            size -= 2
        self.kana_pair(cx, y + ch * 0.26, kana, size)
        d.text((cx, y + ch * 0.48), roma, font=self.jp(22), fill=t["roma"], anchor="mm")
        self.numbers(cx, y + ch * 0.76, n, 21)

    def grid(self, y0: int, rows, cols: list[str], cw: int, size: int, variants: dict, vsize: int) -> int:
        """A table of kana cells: the plain kana in the left half of each cell, its dakuon / handakuon in the right
        half (one column each, so 50-25-25 for は). A row label can be (kana, romaji). Returns the y below it."""
        d, t, ch, x0 = self.d, self.t, self.CH, self.M
        for c, name in enumerate(cols):
            d.text((x0 + self.LW + c * cw + cw // 2, y0 + 25), name, font=self.jp(26), fill=t["accent"], anchor="mm")
        y = y0 + 55
        for label, cells in rows:
            d.rounded_rectangle((x0, y + 8, x0 + self.LW - 16, y + ch - 8), 14, fill=t["label"])
            lx = x0 + (self.LW - 16) // 2
            if isinstance(label, tuple):
                d.text((lx, y + ch * 0.42), label[0], font=self.jp(40), fill=t["ink"], anchor="mm")
                d.text((lx, y + ch * 0.68), label[1], font=self.jp(24), fill=t["roma"], anchor="mm")
            else:
                d.text((lx, y + ch // 2), label, font=self.jp(28), fill=t["ink"], anchor="mm")
            for c, cell in enumerate(cells):
                x = x0 + self.LW + c * cw
                box = (x + 8, y + 8, x + cw - 8, y + ch - 8)
                if cell is None:
                    d.rounded_rectangle(box, 14, fill=t["empty"])
                    continue
                kana, roma = cell
                d.rounded_rectangle(box, 14, outline=t["line"], width=2, fill=t["cell"])
                split = x + 8 + (cw - 16) * 0.5
                self.main_block((x + 8 + split) / 2, y, kana, roma, size)
                more = variants.get(kana, [])
                col_w = (x + cw - 8 - split) / max(len(more), 1)
                for i, (vk, vr) in enumerate(more):
                    left = split + i * col_w
                    d.line((left, y + 30, left, y + ch - 30), fill=t["line"], width=2 if i == 0 else 1)
                    if col_w >= 180:            # room for the same layout as the plain kana
                        self.main_block(left + col_w / 2, y, vk, vr, vsize, num_size=22)
                    else:
                        self.side_block(left + col_w / 2, y, vk, vr, int(vsize * 0.75), col_w)
            y += ch
        return y

    def section(self, y: int, title: str, note: str = "") -> int:
        d, t, M = self.d, self.t, self.M
        d.text((M, y), title, font=self.jp(44), fill=t["accent"])
        if note:
            d.text((M + d.textlength(title, font=self.jp(44)) + 24, y + 16), note, font=self.jp(26), fill=t["muted"])
        d.line((M, y + 68, self.WIDTH - M, y + 68), fill=t["line"], width=2)
        return y + 80

    def draw(self, summary: bool) -> Image.Image:
        """One image: the kana chart, the contracted sounds below it at the same width, then the make-up."""
        img = Image.new("RGB", (self.WIDTH, 8000), self.t["paper"])
        self.d = d = ImageDraw.Draw(img)
        M, t = self.M, self.t
        d.text((M, M), "五十音表 出現頻率", font=self.jp(60), fill=t["accent"])
        d.text((M, M + 90), f"{self.title}：{self.n_docs} 首、{self.total:,} 個音", font=self.jp(28), fill=t["muted"])
        d.text((M, M + 132), "依讀音計算，平假名與片假名合併；拗音（きゃ）算一個音；百分比是占全部的音",
               font=self.jp(24), fill=t["muted"])
        d.line((M, 250, self.WIDTH - M, 250), fill=t["accent"], width=6)
        y = self.grid(270, table(PLAIN), COLS, self.CW, 72, plain_variants(), 60) + 50

        y = self.section(y, "拗音", "い段的音＋小字 ゃ ゅ ょ")
        rows, variants = yoon_rows()
        cols = [f"{k} {v}" for k, v in YOON_COLS]
        y = self.grid(y, rows, [cols[0], "", cols[1], "", cols[2]], self.CW, 60, variants, 44)

        if summary:
            y = self.section(y + 50, "全部的音的組成")
            for i, (k, n) in enumerate(self.kinds.most_common()):
                d.text((M + 20, y + i * 46), f"{n / self.total * 100:6.2f}%", font=self.mono, fill=t["ink"])
                d.text((M + 170, y + i * 46), f"{KINDS[k]}　{n:,} 個", font=self.jp(30), fill=t["ink"])
            y += 46 * len(self.kinds)
        return img.crop((0, 0, self.WIDTH, y + M))


def draw_chart(data: dict, out: Path, theme: str = "dark", summary: bool = False, font_path: str | None = None) -> None:
    img = Chart(data, theme, font_path).draw(summary)
    img.save(out, quality=95) if out.suffix.lower() in (".jpg", ".jpeg") else img.save(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json", type=Path, help="data file written by vm web (songs.json)")
    ap.add_argument("-o", "--output", type=Path, default=Path("kana_chart.png"))
    ap.add_argument("--theme", choices=sorted(THEMES), default="dark",
                    help="dark (screens, default), light (printing), sepia (easy on the eyes)")
    ap.add_argument("--summary", action="store_true", help="add the make-up of all sounds at the bottom")
    ap.add_argument("--font", help="a font with Japanese characters (default: a system font)")
    args = ap.parse_args()
    draw_chart(json.loads(args.json.read_text(encoding="utf-8")), args.output, args.theme, args.summary, args.font)
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
