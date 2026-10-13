import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vocab_miner.cli import app
from vocab_miner.config import ConfigError, build_source, deep_merge, load_config, load_plugin
from vocab_miner.ingest import SourceError, ingest
from vocab_miner.model import NO_STATS_TAG, Utterance, read_jsonl
from vocab_miner.sources.text import TextSource

FIX = Path(__file__).parent / "fixtures"


def make_project(tmp_path: Path, local: str = "", public: str | None = None) -> Path:
    shutil.copy(FIX / "ja_sample.txt", tmp_path / "ja_sample.txt")
    if public is None:
        public = ('data_dir = "data"\n[[sources]]\nid = "demo/text"\n'
                  'plugin = "vocab_miner.sources.text:TextSource"\npath = "ja_sample.txt"\nlang = "ja"\n')
    (tmp_path / "config.toml").write_text(public, encoding="utf-8")
    if local:
        (tmp_path / "config.local.toml").write_text(local, encoding="utf-8")
    return tmp_path


def test_deep_merge_replaces_arrays_and_merges_tables():
    a = {"x": 1, "t": {"a": 1, "b": 2}, "sources": [1, 2]}
    b = {"t": {"b": 3}, "sources": [9]}
    assert deep_merge(a, b) == {"x": 1, "t": {"a": 1, "b": 3}, "sources": [9]}


def test_local_config_overrides(tmp_path):
    root = make_project(tmp_path, local='data_dir = "elsewhere"\n')
    cfg = load_config(root)
    assert cfg.data_dir == root / "elsewhere"
    assert cfg.corpus_path("songs/artist-x") == root / "elsewhere" / "corpus" / "songs" / "artist-x.jsonl"


def test_missing_config(tmp_path):
    with pytest.raises(ConfigError, match="config.example.toml"):
        load_config(tmp_path)


@pytest.mark.parametrize("bad", ["../x", "a/../b", "/", ""])
def test_corpus_path_rejects_escape(tmp_path, bad):
    with pytest.raises(ConfigError):
        make_project(tmp_path) and load_config(tmp_path).corpus_path(bad)


def test_load_plugin():
    assert load_plugin("vocab_miner.sources.text:TextSource") is TextSource
    for bad in ["vocab_miner.sources.text", "no_such_module_xyz:X", "vocab_miner.sources.text:Nope"]:
        with pytest.raises(ConfigError):
            load_plugin(bad)


def test_load_plugin_from_project_root(tmp_path):
    pkg = tmp_path / "myplugins_vm_test"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "src.py").write_text("class Hello:\n    pass\n", encoding="utf-8")
    assert load_plugin("myplugins_vm_test.src:Hello", tmp_path).__name__ == "Hello"


def test_build_source_resolves_path_and_reports_bad_options(tmp_path):
    cfg = load_config(make_project(tmp_path))
    src = build_source(cfg.sources()[0], cfg)
    assert isinstance(src, TextSource) and src.path == tmp_path / "ja_sample.txt"
    with pytest.raises(ConfigError, match="bad options"):
        build_source({**cfg.sources()[0], "nonsense": 1}, cfg)


def test_duplicate_source_ids(tmp_path):
    block = '[[sources]]\nid = "a"\nplugin = "x:Y"\n'
    cfg = load_config(make_project(tmp_path, public=block * 2))
    with pytest.raises(ConfigError, match="duplicate"):
        cfg.sources()


def test_ingest_writes_corpus_and_applies_tags(tmp_path):
    root = make_project(tmp_path)
    (root / "config.toml").write_text(
        (root / "config.toml").read_text(encoding="utf-8")
        + 'no_stats_docs = ["ja_sample"]\nadd_tags = ["demo"]\n', encoding="utf-8")
    (r,) = ingest(load_config(root))
    assert r.path == root / "data" / "corpus" / "demo" / "text.jsonl"
    assert (r.utterances, r.docs) == (8, 1)
    us = list(read_jsonl(r.path))
    assert all(u.tags == ["demo", NO_STATS_TAG] for u in us)
    assert not list(r.path.parent.glob("*.tmp"))


def test_ingest_unknown_no_stats_doc_fails_without_writing(tmp_path):
    root = make_project(tmp_path)
    (root / "config.toml").write_text(
        (root / "config.toml").read_text(encoding="utf-8") + 'no_stats_docs = ["nope"]\n', encoding="utf-8")
    with pytest.raises(SourceError, match="unknown docs"):
        ingest(load_config(root))
    assert not (root / "data" / "corpus" / "demo" / "text.jsonl").exists()


class BadSource:
    def __init__(self, source_id, mode):
        self.source_id, self.mode = source_id, mode

    def utterances(self):
        sid = "other" if self.mode == "wrong_id" else self.source_id
        yield Utterance(id=f"{sid}:1", source_id=sid, doc_id="d", seq=1, lang="ja", text="あ")
        if self.mode == "dup":
            yield Utterance(id=f"{sid}:1", source_id=sid, doc_id="d", seq=2, lang="ja", text="い")


@pytest.mark.parametrize("mode, msg", [("wrong_id", "wrong source id"), ("dup", "duplicate")])
def test_ingest_validates_source_output(tmp_path, mode, msg):
    public = f'[[sources]]\nid = "bad"\nplugin = "{__name__}:BadSource"\nmode = "{mode}"\n'
    with pytest.raises(SourceError, match=msg):
        ingest(load_config(make_project(tmp_path, public=public)))


def test_cli_ingest_and_stats(tmp_path):
    root = make_project(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["ingest", "--root", str(root)])
    assert res.exit_code == 0, res.output
    assert "demo/text: 8 utterances in 1 docs" in res.output
    res = runner.invoke(app, ["stats", "--root", str(root)])
    assert res.exit_code == 0 and "demo/text.jsonl" in res.output
    res = runner.invoke(app, ["ingest", "nope", "--root", str(root)])
    assert res.exit_code == 1


def test_demo_project_runs(tmp_path):
    """examples/demo is the tutorial's project: it must keep working."""
    demo = Path(__file__).parent.parent / "examples" / "demo"
    root = tmp_path / "demo"
    shutil.copytree(demo, root, ignore=shutil.ignore_patterns("data", "out", ".cache"))
    runner = CliRunner()
    res = runner.invoke(app, ["ingest", "--root", str(root)])
    assert res.exit_code == 0, res.output
    assert "demo/songs: 8 utterances" in res.output and "demo/scenes: 4 utterances" in res.output
    us = list(read_jsonl(root / "data" / "corpus" / "demo" / "songs.jsonl"))
    assert all(u.translations.get("zh-Hant") for u in us)
