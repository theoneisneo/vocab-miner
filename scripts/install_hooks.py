"""Install the pre-commit hook (works with Git for Windows, which runs hooks through sh)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
hook = ROOT / ".git" / "hooks" / "pre-commit"
hook.parent.mkdir(parents=True, exist_ok=True)
hook.write_text("#!/bin/sh\nexec uv run python scripts/check_no_corpus.py\n", encoding="utf-8", newline="\n")
hook.chmod(0o755)
print(f"installed {hook}")
