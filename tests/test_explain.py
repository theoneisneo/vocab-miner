import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from vocab_miner.cli import app
from vocab_miner.explain import append_explanations, explain_path, read_explanations, source_of, todo_row
from vocab_miner.export.web import build_web_data
from vocab_miner.model import Token, Utterance

FIX = Path(__file__).parent / "fixtures"


def test_store_appends_and_never_overwrites(tmp_path):
    path = explain_path(tmp_path, "songs/demo")
    assert path == tmp_path / "explain" / "songs" / "demo.jsonl"
    assert append_explanations(path, [{"id": "songs/demo:a:1", "explanation": "first"},
                                      {"id": "songs/demo:a:2", "explanation": ""}]) == 1   # empty rows skipped
    assert append_explanations(path, [{"id": "songs/demo:a:1", "explanation": "changed"},
                                      {"id": "songs/demo:a:3", "text": "third", "origin": "user"}]) == 1
    assert read_explanations(path) == {"songs/demo:a:1": "first", "songs/demo:a:3": "third"}
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [r["origin"] for r in rows] == ["machine", "user"]
    assert read_explanations(tmp_path / "missing.jsonl") == {}


def test_source_of():
    assert source_of("songs/artist:359:001") == "songs/artist"


def test_todo_row_has_context():
    t = Token(surface="雨", lemma="雨", reading="あめ", pos="NOUN", pos_native="名詞", start=0, end=1,
              base="雨", lemma_reading="あめ")
    p = Token(surface="。", lemma="。", reading=None, pos="PUNCT", pos_native="補助記号", start=1, end=2)
    u = Utterance(id="s:d:2", source_id="s", doc_id="d", seq=2, lang="ja", text="雨。",
                  translations={"zh-Hant": "雨。"})
    prev = Utterance(id="s:d:1", source_id="s", doc_id="d", seq=1, lang="ja", text="前")
    row = todo_row(u, [t, p], {t.key: "雨"}, "Song", prev, None)
    assert row["reading"] == "あめ。" and row["prev"] == "前" and row["next"] == ""
    assert row["words"] == [{"surface": "雨", "lemma": "雨", "reading": "あめ", "gloss": "雨"}]   # no punctuation
    assert row["translation"] == "雨。" and row["explanation"] == ""


def test_web_data_includes_explanations():
    u = Utterance(id="s:d:1", source_id="s", doc_id="d", seq=1, lang="ja", text="雨")
    d = build_web_data([], [], [u], {}, {}, "ja", explanations={"s:d:1": "because"})
    assert d["docs"][0]["lines"][0]["ex"] == "because"
    assert "ex" not in build_web_data([], [], [u], {}, {}, "ja")["docs"][0]["lines"][0]


def test_cli_explain_roundtrip(tmp_path):
    shutil.copy(FIX / "ja_sample.txt", tmp_path / "ja_sample.txt")
    (tmp_path / "config.toml").write_text(
        '[[sources]]\nid = "demo/text"\nplugin = "vocab_miner.sources.text:TextSource"\n'
        'path = "ja_sample.txt"\nlang = "ja"\n[[dictionaries]]\n'
        'plugin = "vocab_miner.dictionaries.tsv:TsvGlossDictionary"\npath = "g.tsv"\ngloss_lang = "zh-Hant"\n',
        encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["ingest", "--root", str(tmp_path)]).exit_code == 0
    todo = tmp_path / "todo.jsonl"
    res = runner.invoke(app, ["explain-todo", "--root", str(tmp_path), "-o", str(todo)])
    assert res.exit_code == 0, res.output
    rows = [json.loads(x) for x in todo.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8 and rows[1]["prev"] == rows[0]["text"]
    rows[0]["explanation"] = "a note"
    todo.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    res = runner.invoke(app, ["explain-import", str(todo), "--root", str(tmp_path)])
    assert "added 1 of 1" in res.output
    res = runner.invoke(app, ["explain-todo", "--root", str(tmp_path)])
    assert len(res.output.strip().splitlines()) == 7                     # the explained line is done
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    assert runner.invoke(app, ["explain-import", str(bad), "--root", str(tmp_path)]).exit_code == 1
