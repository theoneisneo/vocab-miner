from typer.testing import CliRunner

from vocab_miner.cli import app
from vocab_miner.model import read_jsonl

LRC = "[ti:Morning Walk]\n[00:01.00]The quick brown fox\n[00:04.00]Jumps over the dog\n[00:07.00]The quick brown fox\n"


def project(tmp_path, lrc=LRC):
    (tmp_path / "songs").mkdir(exist_ok=True)
    (tmp_path / "songs" / "walk.lrc").write_text(lrc, encoding="utf-8")
    (tmp_path / "config.toml").write_text(
        'target_lang = "en"\n[[sources]]\nid = "songs/demo"\nplugin = "vocab_miner.sources.subtitle:SubtitleSource"\n'
        'path = "songs"\nlang = "en"\n', encoding="utf-8")
    return tmp_path


def corpus(tmp_path):
    return list(read_jsonl(tmp_path / "data" / "corpus" / "songs" / "demo.jsonl"))


def test_round_trip_with_checks(tmp_path):
    root = project(tmp_path)
    run = CliRunner().invoke
    assert run(app, ["ingest", "--root", str(root)]).exit_code == 0
    todo = tmp_path / "todo.txt"
    res = run(app, ["translate-todo", "-o", str(todo), "--root", str(root)])
    assert res.exit_code == 0, res.output
    text = todo.read_text(encoding="utf-8")
    assert "## [1] Morning Walk" in text and "1|The quick brown fox" in text and "3|" not in text   # repeat once
    assert text.startswith("# 請把每一行")

    # a chat AI's answer: line 1 translated with a full-width bar, line 2 forgotten, plus a stray line
    todo.write_text(text.replace("1|The quick brown fox", "1｜敏捷的棕色狐狸").replace("2|Jumps over the dog\n", "")
                    + "7|多出來的一行\n", encoding="utf-8")
    res = run(app, ["translate-import", str(todo), "--root", str(root)])
    assert res.exit_code == 0, res.output
    assert "少了第 2 句" in res.output and "沒有第 7 句" in res.output and "imported 1" in res.output
    store = tmp_path / "data" / "translations" / "songs" / "demo.zh-Hant.tsv"
    assert "敏捷的棕色狐狸" in store.read_text(encoding="utf-8")

    assert run(app, ["ingest", "--root", str(root)]).exit_code == 0
    trs = [u.translations.get("zh-Hant") for u in corpus(tmp_path)]
    assert trs == ["敏捷的棕色狐狸", None, "敏捷的棕色狐狸"]

    res = run(app, ["translate-todo", "-o", str(todo), "--root", str(root)])     # only the missing line is left
    assert "1 lines in 1 docs" in res.output and "1|Jumps over the dog" in todo.read_text(encoding="utf-8")


def test_retimed_song_keeps_translations(tmp_path):
    root = project(tmp_path)
    run = CliRunner().invoke
    run(app, ["ingest", "--root", str(root)])
    todo = tmp_path / "todo.txt"
    run(app, ["translate-todo", "-o", str(todo), "--root", str(root)])
    todo.write_text(todo.read_text(encoding="utf-8").replace("1|The quick brown fox", "1|狐狸")
                    .replace("2|Jumps over the dog", "2|跳過狗"), encoding="utf-8")
    run(app, ["translate-import", str(todo), "--root", str(root)])
    project(tmp_path, LRC.replace("00:01.00", "00:02.50").replace("00:04.00", "00:05.10"))    # new timing
    run(app, ["ingest", "--root", str(root)])
    assert [u.translations.get("zh-Hant") for u in corpus(tmp_path)] == ["狐狸", "跳過狗", "狐狸"]


def test_import_without_keys_file(tmp_path):
    root = project(tmp_path)
    (tmp_path / "x.txt").write_text("## [1] t\n1|a\n", encoding="utf-8")
    res = CliRunner().invoke(app, ["translate-import", str(tmp_path / "x.txt"), "--root", str(root)])
    assert res.exit_code == 1 and "keys.json" in res.output
