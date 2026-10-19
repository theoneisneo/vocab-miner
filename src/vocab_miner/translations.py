"""Sentence translations filled in by you ("you are the API"): export the lines that have none, translate them
any way you like (a chat AI, a website, a friend, yourself), import the result.

    vm translate-todo -o todo.txt      numbered lines per doc, with instructions you can paste into a chat AI
    vm translate-import todo.txt       checked line by line, then stored

Stored per source in data/translations/<source_id>.<lang>.tsv (doc, original line, translation) and applied by
`vm ingest`. Lines are matched by their text, not their time, so re-timing a song keeps its translations.
Translations a source already provides (e.g. bilingual subtitles) are never overwritten.
"""
from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .model import Utterance

HEADER = ["doc", "text", "translation"]
LANG_NAMES = {"zh-Hant": "繁體中文", "zh-Hans": "简体中文", "zh": "中文", "en": "英文", "ja": "日文", "ko": "韓文"}
SECTION = re.compile(r"^##\s*\[(\d+)\]")
LINE = re.compile(r"^\s*(\d+)\s*[|｜]\s?(.*)$")


def store_path(data_dir: Path, source_id: str, lang: str) -> Path:
    return data_dir.joinpath("translations", *source_id.split("/")).with_name(
        f"{source_id.split('/')[-1]}.{lang}.tsv")


def read_store(path: Path) -> dict[tuple[str, str], str]:
    if not path.is_file():
        return {}
    rows = csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines(), delimiter="\t")
    return {(r["doc"], r["text"]): r["translation"] for r in rows if r.get("translation")}


def write_store(path: Path, store: dict[tuple[str, str], str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(HEADER)
        w.writerows([doc, text, tr] for (doc, text), tr in sorted(store.items()))


def stores_for(data_dir: Path, source_id: str) -> dict[str, dict[tuple[str, str], str]]:
    """{lang: store} for every translation file of a source."""
    base = store_path(data_dir, source_id, "x")
    out = {}
    for p in sorted(base.parent.glob(f"{base.name[:-len('x.tsv')]}*.tsv")):
        lang = p.name[len(base.name) - len("x.tsv"):-len(".tsv")]
        out[lang] = read_store(p)
    return out


def apply(utterances: Iterable[Utterance], stores: dict[str, dict[tuple[str, str], str]]) -> Iterator[Utterance]:
    for u in utterances:
        for lang, store in stores.items():
            if not u.translations.get(lang) and (tr := store.get((u.doc_id, u.text))):
                u.translations[lang] = tr
        yield u


# ---------- the to-do file ----------

@dataclass
class Section:
    source: str
    doc: str
    title: str
    lines: list[str] = field(default_factory=list)


def todo_sections(utterances: Iterable[Utterance], lang: str, titles: dict[tuple[str, str], str]) -> list[Section]:
    """Lines without a translation in `lang`, each distinct line once per doc, in order."""
    sections: dict[tuple[str, str], Section] = {}
    for u in utterances:
        if u.translations.get(lang):
            continue
        key = (u.source_id, u.doc_id)
        sec = sections.setdefault(key, Section(u.source_id, u.doc_id, titles.get(key, u.doc_id)))
        if u.text not in sec.lines:
            sec.lines.append(u.text)
    return list(sections.values())


def instructions(lang: str, source_lang: str) -> str:
    to, frm = LANG_NAMES.get(lang, lang), LANG_NAMES.get(source_lang, source_lang)
    return (f"# 請把每一行「|」後面的{frm}翻成自然的{to}。\n"
            f"# 規則：保留每行開頭的編號和「|」；不要合併、拆開或刪除任何一行；「## [數字]」標題行原樣保留。\n"
            f"# 可以把整份檔案直接貼給聊天 AI（ChatGPT、Gemini、Claude…），再把回覆整份貼回這個檔案存檔；\n"
            f"# 也可以自己翻。沒翻的行留著原文就好，下次 translate-todo 會再列出來。\n")


def write_todo(path: Path, sections: list[Section], lang: str, source_lang: str) -> int:
    parts = [instructions(lang, source_lang)]
    for k, sec in enumerate(sections, 1):
        parts.append(f"\n## [{k}] {sec.title}\n" + "".join(f"{i}|{t}\n" for i, t in enumerate(sec.lines, 1)))
    path.write_text("".join(parts), encoding="utf-8")
    keys = {"lang": lang, "sections": [{"source": s.source, "doc": s.doc, "title": s.title, "lines": s.lines}
                                       for s in sections]}
    keys_path(path).write_text(json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    return sum(len(s.lines) for s in sections)


def keys_path(todo: Path) -> Path:
    return todo.with_name(todo.name + ".keys.json")


@dataclass
class ImportResult:
    rows: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)   # source -> {(doc, text): tr}
    problems: list[str] = field(default_factory=list)
    untranslated: int = 0


def read_todo(path: Path) -> ImportResult:
    """Translations from a filled-in to-do file, checked against the lines that were exported."""
    keys = json.loads(keys_path(path).read_text(encoding="utf-8"))
    sections = keys["sections"]
    res = ImportResult()
    current: int | None = None
    seen: dict[int, set[int]] = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if raw.lstrip().startswith("#") and not SECTION.match(raw.strip()):
            continue
        if m := SECTION.match(raw.strip()):
            current = int(m.group(1)) - 1
            if not 0 <= current < len(sections):
                res.problems.append(f"第 {n} 行：沒有第 [{current + 1}] 段")
                current = None
            continue
        if not raw.strip():
            continue
        m = LINE.match(raw)
        if current is None or not m:
            res.problems.append(f"第 {n} 行看不懂（應該是「編號|翻譯」）：{raw[:40]}")
            continue
        sec, i, tr = sections[current], int(m.group(1)), m.group(2).strip()
        if not 1 <= i <= len(sec["lines"]):
            res.problems.append(f"「{sec['title']}」沒有第 {i} 句（第 {n} 行）")
            continue
        seen.setdefault(current, set()).add(i)
        original = sec["lines"][i - 1]
        if not tr or tr == original:
            res.untranslated += 1
            continue
        res.rows.setdefault(sec["source"], {})[(sec["doc"], original)] = tr
    for k, sec in enumerate(sections):
        missing = sorted(set(range(1, len(sec["lines"]) + 1)) - seen.get(k, set()))
        if missing:
            res.problems.append(f"「{sec['title']}」少了第 {', '.join(map(str, missing[:10]))}"
                                f"{' …' if len(missing) > 10 else ''} 句")
    return res
