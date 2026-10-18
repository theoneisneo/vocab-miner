"""Command line interface: uv run vm <command>."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from .config import ConfigError, load_config
from .ingest import SourceError, ingest
from .model import NO_STATS_TAG, read_jsonl
from .pipeline import Pipeline, corpus_files, names_path, read_names

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Build vocabulary lists from your own material.")

@app.callback()
def _main() -> None:
    # Windows consoles default to a legacy code page; Japanese output needs UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


RootOpt = Annotated[Path | None, typer.Option("--root", help="Project root containing config files.")]


def _config(root: Path | None):
    try:
        return load_config(root)
    except ConfigError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(2)


@app.command()
def sources(root: RootOpt = None):
    """List configured sources."""
    cfg = _config(root)
    for b in cfg.sources():
        typer.echo(f"{b['id']:<30} {b['plugin']}")


@app.command(name="ingest")
def ingest_cmd(
    only: Annotated[list[str] | None, typer.Argument(help="Source ids to ingest (default: all).")] = None,
    root: RootOpt = None,
):
    """Run sources and write data/corpus/<source_id>.jsonl."""
    cfg = _config(root)
    try:
        results = ingest(cfg, only)
    except (ConfigError, SourceError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    for r in results:
        note = f", {len(r.no_stats_docs)} doc(s) excluded from stats" if r.no_stats_docs else ""
        typer.echo(f"{r.source_id}: {r.utterances} utterances in {r.docs} docs{note} -> {r.path}")


@app.command()
def stats(root: RootOpt = None):
    """Show utterance counts per corpus file."""
    cfg = _config(root)
    files = sorted(cfg.corpus_dir.rglob("*.jsonl")) if cfg.corpus_dir.is_dir() else []
    if not files:
        typer.echo("no corpus yet; run `vm ingest`")
        return
    for f in files:
        us = list(read_jsonl(f))
        docs = Counter(u.doc_id for u in us)
        no_stats = sum(NO_STATS_TAG in u.tags for u in us)
        tr = sum(bool(u.translations) for u in us)
        media = sum(u.media is not None for u in us)
        typer.echo(f"{f.relative_to(cfg.corpus_dir).as_posix():<36} {len(us):>6} utt  {len(docs):>4} docs  "
                   f"{tr:>6} translated  {media:>6} with media  {no_stats:>5} no-stats")


@app.command()
def build(force: Annotated[bool, typer.Option(help="Re-tokenize everything.")] = False, root: RootOpt = None):
    """Tokenize the corpus into the index (.cache/index.sqlite). Only changed sources are redone."""
    try:
        Pipeline(_config(root)).build(force=force, log=typer.echo)
    except (ConfigError, ImportError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)


@app.command()
def vocab(
    source: Annotated[list[str] | None, typer.Option("--source", "-s", help="Only these source ids.")] = None,
    doc: Annotated[list[str] | None, typer.Option("--doc", "-d", help="Only these doc ids (e.g. one song).")] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output CSV path.")] = None,
    root: RootOpt = None,
):
    """Build the vocabulary list (out/vocab.csv) and the grammar-word list (out/grammar.csv)."""
    from .export.csv import CsvExporter

    cfg = _config(root)
    pipe = Pipeline(cfg)
    try:
        pipe.build(log=lambda m: None)
        res = pipe.vocab(source, doc, log=typer.echo)
    except (ConfigError, ImportError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    if not res.entries and not res.grammar:
        typer.echo("no entries; run `vm ingest` first or check --source/--doc")
        raise typer.Exit(1)
    suffix = "".join(f"_{d}" for d in (doc or []))
    path = out or cfg.out_dir / f"vocab{suffix}.csv"
    targets = [(res.entries, path, "words")]
    if res.foreign:
        targets.append((res.foreign, path.with_name(path.name.replace("vocab", "english", 1)
                                                    if "vocab" in path.name else f"english_{path.name}"),
                        "words in English"))
    if res.grammar:
        targets.append((res.grammar, path.with_name(path.name.replace("vocab", "grammar", 1)
                                                    if "vocab" in path.name else f"grammar_{path.name}"),
                        "grammar words"))
    for entries, p, label in targets:
        CsvExporter().export(entries, res.utterances, p)
        no_zh = sum(1 for e in entries if not e.gloss.get("zh-Hant"))
        typer.echo(f"{len(entries)} {label} -> {p}" + (f" ({no_zh} without a Chinese gloss)" if no_zh else ""))


@app.command()
def anki(
    source: Annotated[list[str] | None, typer.Option("--source", "-s", help="Only these source ids.")] = None,
    doc: Annotated[list[str] | None, typer.Option("--doc", "-d", help="Only these doc ids (e.g. one song).")] = None,
    limit: Annotated[int | None, typer.Option(help="Only the first N words (in learning order).")] = None,
    deck: Annotated[str | None, typer.Option(help="Deck name (default from [anki] deck).")] = None,
    romaji_front: Annotated[bool | None, typer.Option(
        "--romaji-front/--no-romaji-front", help="Romaji on the card front (default from [anki] romaji_front).")] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output .apkg path.")] = None,
    root: RootOpt = None,
):
    """Export the vocabulary as an Anki deck (out/vocab.apkg). Known words are skipped."""
    try:
        from .export.anki import AnkiExporter
    except ImportError:
        typer.secho("needs genanki: uv sync --extra anki", fg="red", err=True)
        raise typer.Exit(1)

    cfg = _config(root)
    acfg = cfg.get("anki", {})
    pipe = Pipeline(cfg)
    try:
        pipe.build(log=lambda m: None)
        res = pipe.vocab(source, doc, log=typer.echo)
    except (ConfigError, ImportError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    romanizer = pipe.romanizer()
    exporter = AnkiExporter(deck=deck or acfg.get("deck", "vocab-miner"), limit=limit or acfg.get("limit"),
                            include_known=acfg.get("include_known", False),
                            romaji_front=acfg.get("romaji_front", False) if romaji_front is None else romaji_front,
                            romanize_tokens=getattr(romanizer, "romanize_tokens", None))
    suffix = "".join(f"_{d}" for d in (doc or []))
    path = out or cfg.out_dir / f"vocab{suffix}.apkg"
    n = exporter.export(res.entries, res.utterances, path, tokens=pipe.tokens_for(res.utterances))
    typer.echo(f"{n} cards -> {path}")


@app.command()
def web(
    source: Annotated[list[str] | None, typer.Option("--source", "-s", help="Only these source ids.")] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output path.")] = None,
    title: Annotated[str | None, typer.Option(help="Name shown in the app (default from [web] title).")] = None,
    root: RootOpt = None,
):
    """Write the data file for the sing-along web app (out/web/songs.json). Import it in the app on your phone."""
    from .export.web import build_web_data, write_web_data

    cfg = _config(root)
    pipe = Pipeline(cfg)
    try:
        pipe.build(log=lambda m: None)
        res = pipe.vocab(source, log=typer.echo)
    except (ConfigError, ImportError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    with pipe.open_index() as idx:
        utts = list(idx.iter_utterances(source))
        tokens = {u.id: idx.tokens(u.id) for u in utts}
        titles = idx.doc_titles()
    from .explain import explain_path, read_explanations
    explanations: dict[str, str] = {}
    for sid in {u.source_id for u in utts}:
        explanations.update(read_explanations(explain_path(cfg.data_dir, sid)))
    romanizer = pipe.romanizer()
    data = build_web_data(res.entries, res.grammar, utts, tokens, titles, cfg.get("target_lang", "ja"),
                          getattr(romanizer, "romanize_tokens", None),
                          title=title or cfg.get("web", {}).get("title", ""),
                          romanize_token_list=getattr(romanizer, "romanize_token_list", None),
                          explanations=explanations, foreign=res.foreign)
    path = out or cfg.out_dir / "web" / "songs.json"
    write_web_data(data, path)
    typer.echo(f"{len(data['docs'])} docs, {len(utts)} lines, {len(data['words'])} words -> {path} "
               f"({path.stat().st_size // 1024} KB)")


@app.command()
def kana(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output .apkg path.")] = None,
    root: RootOpt = None,
):
    """Kana deck (out/kana.apkg): hiragana and katakana ordered by frequency in your material, with example words."""
    try:
        from .export.kana import KanaDeckExporter, build_units
    except ImportError:
        typer.secho("needs genanki and the Japanese extras: uv sync --extra ja --extra anki", fg="red", err=True)
        raise typer.Exit(1)

    cfg = _config(root)
    pipe = Pipeline(cfg)
    try:
        pipe.build(log=lambda m: None)
        res = pipe.vocab(log=lambda m: None)
    except (ConfigError, ImportError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    with pipe.open_index() as idx:
        texts = [u.text for u in idx.iter_utterances() if NO_STATS_TAG not in u.tags]
    units = build_units(texts, res.entries + res.grammar)
    path = out or cfg.out_dir / "kana.apkg"
    n = KanaDeckExporter().export(units, path)
    hira = sum(u.script == "hiragana" for u in units)
    typer.echo(f"{n} cards ({hira} hiragana, {n - hira} katakana) -> {path}")


@app.command(name="explain-todo")
def explain_todo(
    doc: Annotated[list[str] | None, typer.Option("--doc", "-d", help="Only these doc ids (e.g. one song).")] = None,
    source: Annotated[list[str] | None, typer.Option("--source", "-s", help="Only these source ids.")] = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the list here instead of stdout.")] = None,
    root: RootOpt = None,
):
    """List lines without an explanation (JSON Lines). Fill in "explanation" and run `vm explain-import`."""
    import json

    from .explain import explain_path, read_explanations, todo_row

    cfg = _config(root)
    pipe = Pipeline(cfg)
    pipe.build(log=lambda m: None)
    res = pipe.vocab(log=lambda m: None)
    glosses = {e.key: e.gloss.get("zh-Hant", "") for e in res.entries + res.grammar}
    rows = []
    with pipe.open_index() as idx:
        titles = idx.doc_titles()
        utts = list(idx.iter_utterances(source, doc))
        done: dict[str, dict[str, str]] = {}
        for i, u in enumerate(utts):
            if u.source_id not in done:
                done[u.source_id] = read_explanations(explain_path(cfg.data_dir, u.source_id))
            if u.id in done[u.source_id]:
                continue
            prev = utts[i - 1] if i > 0 and utts[i - 1].doc_id == u.doc_id else None
            nxt = utts[i + 1] if i + 1 < len(utts) and utts[i + 1].doc_id == u.doc_id else None
            rows.append(todo_row(u, idx.tokens(u.id), glosses, titles.get((u.source_id, u.doc_id), u.doc_id),
                                 prev, nxt))
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"{len(rows)} lines -> {out}")
    else:
        typer.echo(text, nl=False)


@app.command(name="explain-import")
def explain_import(
    file: Annotated[Path, typer.Argument(help="JSON Lines with id and explanation (as written by explain-todo).")],
    origin: Annotated[str, typer.Option(help="Origin for rows without one.")] = "machine",
    root: RootOpt = None,
):
    """Append explanations to data/explain/<source_id>.jsonl. Existing explanations are never changed."""
    import json
    from collections import defaultdict

    from .explain import append_explanations, explain_path, source_of

    cfg = _config(root)
    by_source: dict[str, list[dict]] = defaultdict(list)
    for n, line in enumerate(file.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            typer.secho(f"line {n}: not JSON ({e})", fg="red", err=True)
            raise typer.Exit(1)
        if row.get("id") and row.get("explanation"):
            by_source[source_of(row["id"])].append(row)
    for sid, rows in by_source.items():
        path = explain_path(cfg.data_dir, sid)
        typer.echo(f"{sid}: added {append_explanations(path, rows, origin)} of {len(rows)} -> {path}")
    if not by_source:
        typer.echo("nothing to import (no rows with an explanation)")


@app.command(name="setup-dict")
def setup_dict(root: RootOpt = None):
    """Download JMdict (English glosses, CC BY-SA 4.0) into .cache/dict/."""
    from .dictionaries.jmdict import DEFAULT_GZ, JMDICT_URL, download

    cfg = _config(root)
    dest = cfg.resolve(DEFAULT_GZ)
    typer.echo(f"downloading {JMDICT_URL} -> {dest}")
    download(dest)
    typer.echo("done")


@app.command()
def names(
    source_id: Annotated[str, typer.Argument(help="Source id, e.g. songs/artist-x")],
    min_count: Annotated[int, typer.Option(help="Minimum occurrences.")] = 2,
    root: RootOpt = None,
):
    """Suggest katakana names the tokenizer splits into pieces (candidates for data/names/<source>.txt)."""
    import re
    from collections import Counter

    cfg = _config(root)
    files = corpus_files(cfg)
    if source_id not in files:
        typer.secho(f"no corpus for {source_id}; known: {', '.join(files) or '(none)'}", fg="red", err=True)
        raise typer.Exit(1)
    pipe = Pipeline(cfg)
    tok = pipe.tokenizer
    known = set(read_names(names_path(cfg, source_id)))
    run = re.compile(r"[ァ-ヺー]{3,}")
    counts: Counter = Counter()
    for u in read_jsonl(files[source_id]):
        tokens = tok.tokenize(u.text)
        for m in run.finditer(u.text):
            inside = [t for t in tokens if t.start < m.end() and t.end > m.start()]
            if len(inside) > 1 and m.group() not in known:
                counts[m.group()] += 1
    path = names_path(cfg, source_id)
    typer.echo(f"# candidates for {path} (add the real names, one per line)")
    for w, n in counts.most_common():
        if n >= min_count:
            typer.echo(f"{w}\t{n}")


def _gloss_path(cfg, lang: str) -> Path:
    return cfg.data_dir / "gloss" / f"{cfg.get('target_lang', 'ja')}-{lang.split('-')[0]}.tsv"


@app.command(name="gloss-todo")
def gloss_todo(
    lang: Annotated[str, typer.Option(help="Gloss language.")] = "zh-Hant",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write the list here instead of stdout.")] = None,
    root: RootOpt = None,
):
    """List entries without a gloss in LANG, in rank order, as an importable TSV.

    Fill in the gloss column and run `vm gloss-import`. The columns after pos are context only.
    """
    from .dictionaries.tsv import HEADER

    cfg = _config(root)
    pipe = Pipeline(cfg)
    pipe.build(log=lambda m: None)
    res = pipe.vocab(log=lambda m: None)
    entries, utts = res.entries + res.grammar + res.foreign, res.utterances
    lines = ["\t".join([*HEADER, "pos_label", "gloss_en", "example", "example_translation"])]
    for e in entries:
        if e.gloss.get(lang):
            continue
        ex = utts.get(e.examples[0]) if e.examples else None
        lines.append("\t".join([e.lemma, e.reading or "", "", "", e.pos, "", e.pos_label or "", e.gloss.get("en", ""),
                                ex.text if ex else "", ex.translations.get(lang, "") if ex else ""]))
    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"{len(lines) - 1} entries -> {out}")
    else:
        typer.echo(text, nl=False)


@app.command(name="gloss-import")
def gloss_import(
    file: Annotated[Path, typer.Argument(help="TSV: lemma, reading, gloss[, origin]")],
    lang: Annotated[str, typer.Option(help="Gloss language.")] = "zh-Hant",
    origin: Annotated[str, typer.Option(help="Origin for rows without one.")] = "machine",
    root: RootOpt = None,
):
    """Append glosses to data/gloss/<lang>.tsv. Existing rows are never changed."""
    from .dictionaries.tsv import append_rows, read_rows

    cfg = _config(root)
    rows = [{**r, "origin": r["origin"] or origin} for r in read_rows(file) if r["gloss"]]
    n = append_rows(_gloss_path(cfg, lang), rows)
    typer.echo(f"added {n} of {len(rows)} rows -> {_gloss_path(cfg, lang)}")


if __name__ == "__main__":
    app()


# ---------- YouTube: playlist -> video list -> subtitles ----------

YT_DIR = Path("data") / "raw" / "youtube"


@app.command(name="yt-list")
def yt_list(
    playlist: Annotated[str, typer.Argument(help="YouTube playlist url.")],
    output: Annotated[Path | None, typer.Option("-o", "--output",
                                                help="List file (default: data/raw/youtube/<playlist id>.tsv).")] = None,
):
    """List the videos of a playlist (id, title, channel, length, url) without downloading anything."""
    from .fetch import youtube
    try:
        title, entries = youtube.playlist_entries(playlist)
    except ImportError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    m = re.search(r"[?&]list=([\w-]+)", playlist)
    out = output or YT_DIR / f"{m.group(1) if m else 'playlist'}.tsv"
    youtube.write_list(out, entries)
    typer.echo(f"{title}: {len(entries)} videos -> {out}")


@app.command(name="yt-subs")
def yt_subs(
    items: Annotated[list[str], typer.Argument(help="List files from yt-list, text files of urls, or urls / ids.")],
    output: Annotated[Path, typer.Option("-o", "--output", help="Folder for <video id>.vtt files.")] = YT_DIR / "subs",
    lang: Annotated[str, typer.Option(help="Subtitle language.")] = "en",
    auto: Annotated[bool, typer.Option(help="Fall back to auto-generated captions (often wrong for songs).")] = False,
):
    """Download the subtitle track of each video (never the video). Already downloaded videos are skipped."""
    from .fetch import youtube
    try:
        targets = youtube.read_targets(items)
        results = youtube.download_subtitles(
            targets, output, lang=lang, auto=auto,
            progress=lambda n, total, r: typer.echo(f"[{n}/{total}] {r.id} {r.title[:40]:<40} {r.status} {r.detail}"))
    except (ImportError, ValueError) as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    youtube.write_report(output / "report.tsv", results)
    counts = Counter(r.status for r in results)
    typer.echo("\n" + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f" -> {output / 'report.tsv'}")
    if counts.get("auto-available"):
        typer.echo("Some videos only have auto-generated captions; add --auto to download them anyway.")


AUDIO_SUFFIXES = (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus", ".webm", ".mp4", ".mkv")


@app.command(name="transcribe")
def transcribe_cmd(
    items: Annotated[list[str], typer.Argument(
        help="Audio/video files, or YouTube urls / ids / list files from yt-list (their audio is downloaded).")],
    lyrics: Annotated[Path | None, typer.Option(
        help="Folder with lyrics text <name>.txt (no timing). Matching files get Whisper's timing; "
             "results are written here too.")] = None,
    output: Annotated[Path | None, typer.Option("-o", "--output",
                                                help="Folder for .lrc results (default: --lyrics or data/raw/transcripts).")] = None,
    lang: Annotated[str, typer.Option(help="Language spoken/sung.")] = "en",
    model: Annotated[str, typer.Option(help="Whisper model.")] = "large-v3",
    force: Annotated[bool, typer.Option(help="Redo items that already have timed lyrics/subtitles.")] = False,
):
    """Timed .lrc from audio with Whisper. With lyrics text, only the timing comes from Whisper."""
    from . import transcribe as tr
    from .fetch import youtube
    out = output or lyrics or Path("data") / "raw" / "transcripts"
    out.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, str, Path | None]] = []     # (name, title, local audio or None for YouTube)
    try:
        for item in items:
            p = Path(item)
            if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES:
                jobs.append((p.stem, p.stem, p))
            else:
                jobs += [(vid, title, None) for vid, title in youtube.read_targets([item])]
    except ValueError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    todo = [j for j in jobs if force or not any((out / f"{j[0]}{s}").exists() for s in (".lrc", ".vtt", ".srt"))]
    typer.echo(f"{len(todo)} to do, {len(jobs) - len(todo)} already timed in {out}")
    if not todo:
        return
    try:
        whisper = tr.load_model(model)
    except ImportError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1)
    for n, (name, title, audio) in enumerate(todo, 1):
        try:
            audio = audio or youtube.download_audio(name, Path("data") / "raw" / "youtube" / "audio")
        except Exception as e:  # noqa: BLE001 - one unavailable video should not stop the rest
            typer.secho(f"[{n}/{len(todo)}] {name} {title[:40]:<40} no audio: {str(e).splitlines()[0]}", fg="red")
            continue
        words, heard = tr.transcribe(whisper, audio, lang)
        text_file = (lyrics / f"{name}.txt") if lyrics else None
        if text_file and text_file.is_file():
            lines, kind = tr.align(tr.read_lyrics(text_file), words), "lyrics timed"
        else:
            lines, kind = heard, "transcribed (check for mistakes)"
        (out / f"{name}.lrc").write_text(tr.to_lrc(lines, title, transcribed=kind != "lyrics timed"), encoding="utf-8")
        typer.echo(f"[{n}/{len(todo)}] {name} {title[:40]:<40} {len(lines)} lines, {kind}")
        if not tr.looks_like(" ".join(w.text for w in words), lang):
            typer.secho(f"    Whisper did not hear {lang} here: the audio may be in another language", fg="yellow")
