"""Command line interface: uv run vm <command>."""
from __future__ import annotations

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
    if res.grammar:
        targets.append((res.grammar, path.with_name(path.name.replace("vocab", "grammar", 1)
                                                    if "vocab" in path.name else f"grammar_{path.name}"),
                        "grammar words"))
    for entries, p, label in targets:
        CsvExporter().export(entries, res.utterances, p)
        no_zh = sum(1 for e in entries if not e.gloss.get("zh-Hant"))
        typer.echo(f"{len(entries)} {label} -> {p}" + (f" ({no_zh} without a Chinese gloss)" if no_zh else ""))


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
    entries, utts = res.entries + res.grammar, res.utterances
    lines = ["\t".join([*HEADER, "pos_label", "gloss_en", "example", "example_translation"])]
    for e in entries:
        if e.gloss.get(lang):
            continue
        ex = utts.get(e.examples[0]) if e.examples else None
        lines.append("\t".join([e.lemma, e.reading or "", "", "", e.pos, e.pos_label or "", e.gloss.get("en", ""),
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
