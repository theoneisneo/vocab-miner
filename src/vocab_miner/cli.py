"""Command line interface: uv run vm <command>."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from .config import ConfigError, load_config
from .ingest import SourceError, ingest
from .model import NO_STATS_TAG, read_jsonl

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Build vocabulary lists from your own material.")

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


if __name__ == "__main__":
    app()
