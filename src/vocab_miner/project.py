"""A song project of its own: `vm new` writes one, `vm update` runs everything for it.

    data/<name>/config.local.toml   language settings (copied from the main project), the lyrics source, [songs], [web]
    data/<name>/playlists.txt       the YouTube playlists / albums, one per line
    data/raw/<name>/                timed lyrics, translations, titles.tsv, skip.txt, quality.tsv

Commands for it take `--root data/<name>`.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .config import Config

LANG_TABLES = ("tokenizer", "romanizer", "vocab", "examples")      # copied as they are from the main project
LANG_KEYS = ("target_lang", "gloss_langs")
NAME = re.compile(r"^[A-Za-z0-9][\w-]*$")


def toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{toml_key(k)} = {toml_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def toml_key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else toml_value(k)


def toml_table(name: str, table: dict, array: bool = False) -> list[str]:
    head = f"[[{name}]]" if array else f"[{name}]"
    return [head, *(f"{toml_key(k)} = {toml_value(v)}" for k, v in table.items() if not isinstance(v, dict) or v)]


def shown(p: Path) -> str:
    """A path as typed in a command: relative to the current folder when it is inside it."""
    try:
        return Path(p).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def rebase(base: Config, p: str, new_root: Path) -> str:
    """A path of the main project's config, relative to the new project's root (absolute on another drive)."""
    try:
        return Path(os.path.relpath(base.resolve(p), new_root)).as_posix()
    except ValueError:
        return base.resolve(p).as_posix()


def album_name(playlist_title: str) -> str:
    """"Album - diorama" (YouTube's name for an album playlist) -> "diorama"."""
    return re.sub(r"^\s*album\s*[-:]\s*", "", playlist_title, flags=re.IGNORECASE).strip() or "-"


def new_project(base: Config, name: str, urls: Sequence[str], artist: str = "", lang: str | None = None,
                translations: Sequence[str] = ("zh-Hant",), title: str = "", parent: Path | None = None,
                album_title: Callable[[str], str] | None = None) -> Path:
    """Write data/<name>/config.local.toml and playlists.txt. Returns the new root.
    `album_title(url)` names each playlist's section in the app (default: none, edit playlists.txt)."""
    if not NAME.match(name):
        raise ValueError(f"project name {name!r}: use letters, digits, '-' or '_'")
    parent = parent or base.data_dir
    root = parent / name
    if (root / "config.local.toml").exists():
        raise FileExistsError(f"{root / 'config.local.toml'} already exists")
    lang = lang or base.get("target_lang", "ja")
    if base.get("target_lang") != lang:
        raise ValueError(f"the main project is for {base.get('target_lang')!r}, not {lang!r}: run `vm new` with "
                         f"--root pointing at a project in {lang!r} to copy its language settings")
    raw = parent / "raw" / name
    lines = [f"# Songs project made by `vm new`. Run its commands with:  uv run vm <command> --root {shown(root)}",
             'data_dir = "."',
             f"out_dir = {toml_value(rebase(base, base.get('out_dir', 'out'), root) + '/' + name)}"]
    lines += [f"{k} = {toml_value(base.get(k))}" for k in LANG_KEYS if base.get(k) is not None]
    for t in LANG_TABLES:
        if isinstance(base.get(t), dict):
            lines += ["", *toml_table(t, base.get(t))]
    from .pipeline import DEFAULT_DICTIONARIES
    for d in base.get("dictionaries", DEFAULT_DICTIONARIES):
        d = dict(d)
        if "path" in d:
            d["path"] = rebase(base, d["path"], root)
        lines += ["", *toml_table("dictionaries", d, array=True)]
    rel_raw = Path(os.path.relpath(raw, root)).as_posix()
    source = {"id": f"songs/{name}", "plugin": "vocab_miner.sources.subtitle:SubtitleSource", "path": rel_raw,
              "lang": lang, "video_list": f"{rel_raw}/videos.tsv",
              "translations": {t: "file" for t in translations}}
    songs = {"playlists": "playlists.txt", "output": rel_raw,
             "list_dir": rebase(base, base.get("web", {}).get("playlist_dir", "data/raw/youtube"), root),
             "translations": list(translations)}
    web = {"title": title or artist or name, "playlists": "playlists.txt", "playlist_dir": songs["list_dir"],
           "file_name": f"{name}.json"}
    if copy_to := base.get("web", {}).get("copy_to"):
        web["copy_to"] = [str(base.resolve(c).as_posix()) for c in copy_to]
    if artist:
        web["artist"] = artist
    if search := base.get("web", {}).get("search_links"):
        web["search_links"] = search
    lines += ["", "# lyrics: timed files named by video id, translations as <id>.<lang>.lrc next to them",
              *toml_table("sources", source, array=True),
              "", "# `vm update`: playlists -> lyrics -> translations from the uploader's subtitles",
              "# translations: the languages to look for, e.g. [\"zh-Hant\"], [\"en\"], [] for none",
              *toml_table("songs", songs), "", *toml_table("web", web)]
    pl = ["# language | album | playlist url   (album = the section name in the app; \"-\" = no section)"]
    for url in urls:
        pl.append(f"{lang} | {album_title(url) if album_title else '-'} | {url}")
    root.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    (root / "config.local.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "playlists.txt").write_text("\n".join(pl) + "\n", encoding="utf-8")
    return root


def songs_settings(cfg: Config) -> dict[str, Any]:
    """[songs] of a project, paths resolved; ValueError when the project has none."""
    s = cfg.get("songs")
    if not s:
        raise ValueError(f"{cfg.root}: no [songs] table in the config; `vm new` writes one, or see "
                         "docs/getting-started.md")
    return {"playlists": cfg.resolve(s.get("playlists", "playlists.txt")).resolve(),
            "output": cfg.resolve(s["output"]).resolve(),
            "list_dir": cfg.resolve(s.get("list_dir", "data/raw/youtube")).resolve(),
            "translations": list(s.get("translations", [])),
            "whisper": s.get("whisper", True),
            "lang": cfg.get("target_lang", "ja")}


def summary(data: dict, gloss_lang: str | None) -> dict[str, int]:
    """What the web data still lacks: lines without a translation, words without a gloss in `gloss_lang`."""
    lines = [ln for d in data["docs"] for ln in d["lines"]]
    words = [w for w in data["words"] if not w.get("grammar")]
    short = (gloss_lang or "").split("-")[0]
    return {"songs": len(data["docs"]), "lines": len(lines), "untranslated": sum(not ln.get("tr") for ln in lines),
            "songs_untranslated": sum(not any(ln.get("tr") for ln in d["lines"]) for d in data["docs"]),
            "words": len(words), "no_gloss": sum(not w.get(short) for w in words) if short else 0}
