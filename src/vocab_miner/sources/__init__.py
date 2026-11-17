"""Built-in sources. Shared helpers for sources that read files from a path (file or directory)."""
from __future__ import annotations

from pathlib import Path


def iter_files(path: Path, suffixes: tuple[str, ...]) -> list[tuple[str, Path]]:
    """Return (doc_id, file) pairs. doc_id is the path relative to the directory, without suffix, "/"-separated.
    Folders whose name starts with "." are skipped (tools keep downloads and caches there)."""
    path = Path(path)
    if path.is_file():
        return [(path.stem, path)]
    if not path.is_dir():
        raise FileNotFoundError(path)
    files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in suffixes
                   and not any(part.startswith(".") for part in p.relative_to(path).parts[:-1]))
    return [(p.relative_to(path).with_suffix("").as_posix(), p) for p in files]


def read_text(path: Path) -> str:
    """UTF-8 (with or without BOM); newlines normalized to \\n."""
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
