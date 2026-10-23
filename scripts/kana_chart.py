"""Gojūon (plain kana, 清音) chart with how often each kana occurs in a sing-along data file.

    uv run --with pillow python scripts/kana_chart.py out/web/songs.json -o kana_chart.png
    ... --theme light          white paper, for printing (also: dark = default, sepia)
    ... --summary              add the make-up of all kana (dakuten, small kana, long marks) at the bottom

Counts the readings of the lines (kanji by their ruby reading, kana as written); hiragana and katakana of one
sound share a cell. Percentages are of all kana in the readings, dakuten etc. included. PNG keeps the text
sharp; use a .jpg name for JPEG.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROWS = [("あ行", "あいうえお", "a i u e o"), ("か行", "かきくけこ", "ka ki ku ke ko"),
        ("さ行", "さしすせそ", "sa shi su se so"), ("た行", "たちつてと", "ta chi tsu te to"),
        ("な行", "なにぬねの", "na ni nu ne no"), ("は行", "はひふへほ", "ha hi fu he ho"),
        ("ま行", "まみむめも", "ma mi mu me mo"), ("や行", "や ゆ よ", "ya - yu - yo"),
        ("ら行", "らりるれろ", "ra ri ru re ro"), ("わ行", "わ   を", "wa - - - wo"), ("ん", "ん    ", "n - - - -")]
COLS = ["あ段", "い段", "う段", "え段", "お段"]
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


def to_hiragana(ch: str) -> str:
    return chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch


def count_kana(data: dict) -> tuple[Counter, Counter]:
    """(plain kana counts by hiragana, totals by kind) over the readings of every line."""
    plain, kinds = Counter(), Counter()
    for doc in data["docs"]:
        for line in doc["lines"]:
            for seg in line["seg"]:
                for ch in (seg[1] or seg[0]):
                    if ch == "ー":
                        kinds["長音符號 ー"] += 1
                        continue
                    h = to_hiragana(ch)
                    if not "\u3041" <= h <= "\u3096":
                        continue
                    base = unicodedata.normalize("NFD", h)
                    if h in SMALL:
                        kinds["小字（拗音、促音：きゃ、っ）"] += 1
                    elif "\u3099" in base:
                        kinds["濁音（が、ざ、だ、ば）"] += 1
                    elif "\u309a" in base:
                        kinds["半濁音（ぱ）"] += 1
                    else:
                        kinds["清音（上表 46 音）"] += 1
                        plain[h] += 1
    return plain, kinds


def font(paths: list[str], size: int, user: str | None = None):
    for p in [user, *paths]:
        if p and Path(p).is_file():
            return ImageFont.truetype(p, size)
    raise SystemExit("no suitable font found: pass --font path/to/japanese-font.ttc")


def draw_chart(data: dict, out: Path, theme: str = "dark", summary: bool = False, font_path: str | None = None) -> None:
    t = THEMES[theme]
    plain, kinds = count_kana(data)
    total = sum(kinds.values()) or 1
    W, M, HEAD, CW, CH, LW = 1700, 60, 300, 290, 196, 150
    H = HEAD + 70 + CH * len(ROWS) + (330 if summary else 70)
    img = Image.new("RGB", (W, H), t["paper"])
    d = ImageDraw.Draw(img)
    f_title, f_sub, f_big = font(FONTS, 60, font_path), font(FONTS, 28, font_path), font(FONTS, 72, font_path)
    f_kata, f_small, f_num = font(FONTS, 40, font_path), font(FONTS, 26, font_path), font(FONTS, 30, font_path)
    try:
        mono = font(MONO, 26)
    except SystemExit:
        mono = f_small

    d.text((M, M), "五十音表（清音 46 音）出現頻率", font=f_title, fill=t["accent"])
    d.text((M, M + 90), f"{data.get('title') or 'songs'}：{len(data['docs'])} 首、{total:,} 個假名"
                        "（依讀音計算，平假名與片假名合併）", font=f_sub, fill=t["muted"])
    d.line((M, HEAD - 40, W - M, HEAD - 40), fill=t["accent"], width=6)

    x0, y0 = M + LW, HEAD
    for c, name in enumerate(COLS):
        d.text((x0 + c * CW + CW // 2, y0 + 30), name, font=f_small, fill=t["accent"], anchor="mm")
    y0 += 70
    width = max(plain.values(), default=0)
    digits = len(f"{width:,}")                       # pad counts to the widest one so every cell lines up
    for r, (label, kana, roma) in enumerate(ROWS):
        y = y0 + r * CH
        d.rounded_rectangle((M, y + 8, M + LW - 16, y + CH - 8), 14, fill=t["label"])
        d.text((M + (LW - 16) // 2, y + CH // 2), label, font=f_sub, fill=t["ink"], anchor="mm")
        romas = roma.split()
        for c in range(5):
            x = x0 + c * CW
            box = (x + 8, y + 8, x + CW - 8, y + CH - 8)
            h = kana[c] if c < len(kana) else " "
            if h == " ":
                d.rounded_rectangle(box, 14, fill=t["empty"])
                continue
            d.rounded_rectangle(box, 14, outline=t["line"], width=2, fill=t["cell"])
            cx = x + CW // 2
            d.text((cx - 22, y + 62), h, font=f_big, fill=t["ink"], anchor="mm")
            d.text((cx + 42, y + 72), chr(ord(h) + 0x60), font=f_kata, fill=t["kata"], anchor="mm")
            d.text((cx, y + 118), romas[c], font=f_small, fill=t["roma"], anchor="mm")
            n = plain.get(h, 0)
            # "14.20%   1,234次": both numbers padded in a monospace font; "次" in the Japanese font
            nums = f"{n / total * 100:6.2f}%  {n:>{digits},}"
            w_nums, w_unit = d.textlength(nums, font=mono), d.textlength("次", font=f_small)
            left = cx - (w_nums + 4 + w_unit) / 2
            d.text((left, y + 160), nums, font=mono, fill=t["ink"], anchor="lm")
            d.text((left + w_nums + 4, y + 160), "次", font=f_small, fill=t["muted"], anchor="lm")

    if summary:
        y = y0 + CH * len(ROWS) + 40
        d.line((M, y, W - M, y), fill=t["line"], width=2)
        y += 30
        d.text((M, y), "全部假名的組成", font=f_sub, fill=t["ink"])
        for i, (k, n) in enumerate(kinds.most_common()):
            d.text((M + 20, y + 55 + i * 46), f"{n / total * 100:6.2f}%", font=mono, fill=t["ink"])
            d.text((M + 170, y + 55 + i * 46), f"{k}　{n:,} 個", font=f_num, fill=t["ink"])
    img.save(out, quality=95) if out.suffix.lower() in (".jpg", ".jpeg") else img.save(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("json", type=Path, help="data file written by vm web (songs.json)")
    ap.add_argument("-o", "--output", type=Path, default=Path("kana_chart.png"))
    ap.add_argument("--theme", choices=sorted(THEMES), default="dark",
                    help="dark (screens, default), light (printing), sepia (easy on the eyes)")
    ap.add_argument("--summary", action="store_true", help="add the make-up of all kana at the bottom")
    ap.add_argument("--font", help="a font with Japanese characters (default: a system font)")
    args = ap.parse_args()
    draw_chart(json.loads(args.json.read_text(encoding="utf-8")), args.output, args.theme, args.summary, args.font)
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
