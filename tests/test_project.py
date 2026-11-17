import tomllib
from pathlib import Path

import pytest

from vocab_miner.config import load_config
from vocab_miner.project import album_name, new_project, songs_settings, summary

BASE = """
data_dir = "data"
out_dir = "out"
target_lang = "ja"
gloss_langs = ["zh-Hant", "en"]

[tokenizer]
plugin = "vocab_miner.tokenizers.ja:JapaneseTokenizer"

[romanizer]
plugin = "vocab_miner.tokenizers.ja:HepburnRomanizer"
macrons = false

[[dictionaries]]
plugin = "vocab_miner.dictionaries.tsv:TsvGlossDictionary"
path = "data/gloss/ja-zh.tsv"
gloss_lang = "zh-Hant"

[web]
copy_to = ["shared"]
search_links = { Spotify = "https://open.spotify.com/search/{artist}%20{title}" }
"""


def base(tmp_path: Path):
    (tmp_path / "config.local.toml").write_text(BASE, encoding="utf-8")
    return load_config(tmp_path)


def test_new_project_writes_a_working_config(tmp_path: Path):
    root = new_project(base(tmp_path), "singer", ["https://www.youtube.com/playlist?list=PLx"], artist="Singer",
                       album_title=lambda url: "First Album")
    assert root == tmp_path / "data" / "singer"
    cfg = load_config(root)
    assert cfg.get("target_lang") == "ja" and cfg.get("romanizer")["macrons"] is False
    assert cfg.resolve(cfg.get("dictionaries")[0]["path"]).resolve() ==(tmp_path / "data/gloss/ja-zh.tsv").resolve()
    assert cfg.out_dir.resolve() == (tmp_path / "out" / "singer").resolve()
    src = cfg.sources()[0]
    assert src["id"] == "songs/singer" and src["translations"] == {"zh-Hant": "file"}
    assert cfg.resolve(src["path"]).resolve() == (tmp_path / "data/raw/singer").resolve()
    s = songs_settings(cfg)
    assert s["playlists"] == root / "playlists.txt" and s["translations"] == ["zh-Hant"]
    assert cfg.get("web")["artist"] == "Singer" and cfg.get("web")["file_name"] == "singer.json"
    assert "ja | First Album | https://www.youtube.com/playlist?list=PLx" in (root / "playlists.txt").read_text(
        encoding="utf-8")
    with pytest.raises(FileExistsError):
        new_project(base(tmp_path), "singer", [])


def test_new_project_checks_name_and_language(tmp_path: Path):
    with pytest.raises(ValueError):
        new_project(base(tmp_path), "../x", [])
    with pytest.raises(ValueError):
        new_project(base(tmp_path), "en-songs", [], lang="en")


def test_new_project_without_translations(tmp_path: Path):
    root = new_project(base(tmp_path), "quiet", [], translations=[])
    data = tomllib.loads((root / "config.local.toml").read_text(encoding="utf-8"))
    assert data["songs"]["translations"] == [] and "translations" not in data["sources"][0]


def test_new_project_copies_the_default_dictionaries(tmp_path: Path):
    (tmp_path / "config.local.toml").write_text('target_lang = "ja"\n', encoding="utf-8")
    cfg = load_config(new_project(load_config(tmp_path), "plain", []))
    paths = [cfg.resolve(d["path"]).resolve() for d in cfg.get("dictionaries")]
    assert (tmp_path / "data/gloss/ja-zh.tsv").resolve() in paths


def test_songs_settings_needs_the_table(tmp_path: Path):
    with pytest.raises(ValueError):
        songs_settings(base(tmp_path))


def test_album_name_and_summary():
    assert album_name("Album - diorama") == "diorama"
    assert album_name("My mix") == "My mix"
    data = {"docs": [{"lines": [{"tr": "a"}, {"tr": ""}]}, {"lines": [{"tr": ""}]}],
            "words": [{"zh": "x"}, {"zh": ""}, {"zh": "", "grammar": True}]}
    assert summary(data, "zh-Hant") == {"songs": 2, "lines": 3, "untranslated": 2, "songs_untranslated": 1,
                                        "words": 2, "no_gloss": 1}
