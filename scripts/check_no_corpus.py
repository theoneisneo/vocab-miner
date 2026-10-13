"""Pre-commit guard: keep material text and private details out of the public repo.

Checks staged files for:
  1. forbidden paths (private/, data/, out/, local config ...)
  2. too much kana outside tests/fixtures/ (a sign that lyrics/dialogue leaked into code or docs)
  3. any term listed in private/blocklist.txt (one per line; e.g. tool names, site names, game titles)

Usage:  uv run python scripts/check_no_corpus.py          (checks staged files)
        uv run python scripts/check_no_corpus.py --all    (checks all tracked files)
Install: uv run python scripts/install_hooks.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PREFIXES = ("private/", "data/", "out/", ".cache/")
FORBIDDEN_FILES = {"config.local.toml", "CLAUDE.local.md"}
FIXTURE_DIR = "tests/fixtures/"
KANA = re.compile(r"[぀-ヿ]")
MAX_KANA = 300            # docs may contain a few example words, not whole texts


def git_files(all_files: bool) -> list[str]:
    cmd = ["git", "ls-files"] if all_files else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def staged_text(path: str, all_files: bool) -> str | None:
    if all_files:
        p = ROOT / path
        data = p.read_bytes() if p.is_file() else b""
    else:
        data = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True).stdout
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None           # binary


def load_blocklist() -> list[str]:
    p = ROOT / "private" / "blocklist.txt"
    if not p.is_file():
        return []
    return [w.strip() for w in p.read_text(encoding="utf-8-sig").splitlines()
            if w.strip() and not w.startswith("#")]


def main() -> int:
    all_files = "--all" in sys.argv
    blocklist = load_blocklist()
    problems: list[str] = []

    for path in git_files(all_files):
        norm = path.replace("\\", "/")
        if norm.startswith(FORBIDDEN_PREFIXES) or norm in FORBIDDEN_FILES:
            problems.append(f"{path}: private path must not be committed")
            continue
        text = staged_text(path, all_files)
        if text is None:
            continue
        if not norm.startswith(FIXTURE_DIR):
            n = len(KANA.findall(text))
            if n > MAX_KANA:
                problems.append(f"{path}: {n} kana characters (limit {MAX_KANA}) - material text leaked?")
        lower = text.lower()
        for term in blocklist:
            if term.lower() in lower:
                problems.append(f"{path}: contains a blocklisted term")
                break        # don't print the term itself

    if problems:
        print("check_no_corpus: commit blocked\n  " + "\n  ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
