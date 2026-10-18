"""Config loading (config.toml + config.local.toml) and plugin loading ("module.path:ClassName")."""
from __future__ import annotations

import importlib
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILES = ("config.toml", "config.local.toml")   # later files override earlier ones


class ConfigError(Exception):
    pass


def deep_merge(base: dict, override: dict) -> dict:
    """Merge nested tables; any non-table value (including arrays such as [[sources]]) is replaced."""
    out = dict(base)
    for k, v in override.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@dataclass
class Config:
    root: Path
    data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.data.get("data_dir", "data"))

    @property
    def out_dir(self) -> Path:
        return self.resolve(self.data.get("out_dir", "out"))

    @property
    def corpus_dir(self) -> Path:
        return self.data_dir / "corpus"

    def resolve(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else self.root / p

    def corpus_path(self, source_id: str) -> Path:
        """data/corpus/<source_id>.jsonl; a "/" in the id becomes a subdirectory."""
        parts = [s for s in source_id.split("/") if s]
        if not parts or any(s in (".", "..") for s in parts):
            raise ConfigError(f"invalid source id: {source_id!r}")
        return self.corpus_dir.joinpath(*parts).with_suffix(".jsonl")

    def sources(self) -> list[dict[str, Any]]:
        blocks = self.data.get("sources", [])
        ids = [b.get("id") for b in blocks]
        missing = [i for i, b in enumerate(blocks) if not b.get("id") or not b.get("plugin")]
        if missing:
            raise ConfigError(f"[[sources]] entries {missing} need both 'id' and 'plugin'")
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ConfigError(f"duplicate source ids: {sorted(dup)}")
        return blocks


def load_config(root: Path | None = None, files: tuple[str, ...] = CONFIG_FILES) -> Config:
    root = (root or Path.cwd()).resolve()
    found = [root / f for f in files if (root / f).is_file()]
    if not found:
        raise ConfigError(f"no config found in {root}; copy config.example.toml to config.local.toml")
    data: dict[str, Any] = {}
    for f in found:
        with f.open("rb") as fh:
            data = deep_merge(data, tomllib.load(fh))
    return Config(root=root, data=data)


def load_plugin(spec: str, root: Path | None = None) -> type:
    """Import "package.module:ClassName". The project root is put on sys.path so private.* plugins work."""
    mod_name, sep, attr = spec.partition(":")
    if not sep or not mod_name or not attr:
        raise ConfigError(f"plugin must look like 'module.path:ClassName', got {spec!r}")
    if root is not None and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(mod_name)
    except ImportError as e:
        raise ConfigError(f"cannot import plugin module {mod_name!r}: {e}") from e
    try:
        return getattr(module, attr)
    except AttributeError as e:
        raise ConfigError(f"module {mod_name!r} has no attribute {attr!r}") from e


PATH_KEYS = ("path", "video_list")


def build_source(block: dict[str, Any], config: Config):
    """Instantiate a source from its [[sources]] block. 'id' -> source_id, 'path' resolved against the root."""
    kwargs = {k: v for k, v in block.items() if k not in ("id", "plugin")}
    for k in PATH_KEYS:
        if k in kwargs:
            kwargs[k] = config.resolve(kwargs[k])
    cls = load_plugin(block["plugin"], config.root)
    try:
        return cls(source_id=block["id"], **kwargs)
    except TypeError as e:
        raise ConfigError(f"source {block['id']!r}: bad options for {block['plugin']}: {e}") from e
