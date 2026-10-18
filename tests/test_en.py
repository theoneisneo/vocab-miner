import csv
import json

import pytest
from typer.testing import CliRunner

from vocab_miner.cli import app
from vocab_miner.model import TRANSCRIBED_TAG, read_jsonl
from vocab_miner.sources.subtitle import SubtitleSource

pytest.importorskip("spacy")

VID = "abcDEF12345"
LRC = """[ti:Morning Walk]
[re:vocab-miner: Whisper transcription, may contain mistakes]
[00:01.00]I'm walking down the quiet streets
[00:04.00]The birds were singing, la-la-la
[00:08.00]She sang a song I don't know
[00:12.00]
"""


@pytest.fixture
def tokenizer():
    from vocab_miner.tokenizers.en import EnglishTokenizer
    return EnglishTokenizer()


def test_lemmas_contractions_and_vocables(tokenizer):
    toks = tokenizer.tokenize("I'm walking. She sang, la-la-la, don't cry")
    by = {t.surface: t for t in toks}
    assert by["I"].lemma == "I" and by["'m"].lemma == "be" and by["'m"].pos == "AUX"
    assert by["walking"].lemma == "walk" and by["sang"].lemma == "sing"
    assert by["n't"].lemma == "not"
    assert {t.pos for t in toks if t.surface.lower() == "la"} == {"INTJ"}
    text = "I'm walking. She sang, la-la-la, don't cry"
    assert all(text[t.start:t.end] == t.surface for t in toks)
    assert tokenizer.pos_label("VBD") == "動詞" and tokenizer.pos_label("NN") == "名詞"


def test_subtitle_source_titles_media_and_transcribed_tag(tmp_path):
    (tmp_path / "songs").mkdir()
    (tmp_path / "songs" / f"{VID}.lrc").write_text(LRC, encoding="utf-8")
    (tmp_path / "songs" / "other.lrc").write_text("[00:01.00]Hello there\n", encoding="utf-8")
    lst = tmp_path / "list.tsv"
    lst.write_text(f"index\tid\ttitle\tchannel\tduration\turl\n1\t{VID}\tRaw Title (Official)\tCh\t60\tu\n",
                   encoding="utf-8")
    src = SubtitleSource("s", tmp_path / "songs", "en", video_list=lst, titles={"other": "Other Song"})
    utts = list(src.utterances())
    first = next(u for u in utts if u.doc_id == VID)
    assert first.media.kind == "youtube" and first.media.uri == VID and first.media.start == 1.0
    assert "title:Morning Walk" in first.tags and TRANSCRIBED_TAG in first.tags   # [ti:] beats the list title
    other = next(u for u in utts if u.doc_id == "other")
    assert other.media is None and other.tags == ["title:Other Song"]


def test_english_project_end_to_end(tmp_path):
    (tmp_path / "songs").mkdir()
    (tmp_path / "songs" / f"{VID}.lrc").write_text(LRC, encoding="utf-8")
    (tmp_path / "list.tsv").write_text(f"index\tid\ttitle\tchannel\tduration\turl\n1\t{VID}\tX\tC\t60\tu\n",
                                       encoding="utf-8")
    (tmp_path / "config.toml").write_text(
        'target_lang = "en"\nromanizer = false\n'
        '[tokenizer]\nplugin = "vocab_miner.tokenizers.en:EnglishTokenizer"\n'
        '[[dictionaries]]\nplugin = "vocab_miner.dictionaries.tsv:TsvGlossDictionary"\n'
        'path = "data/gloss/en-zh.tsv"\ngloss_lang = "zh-Hant"\n'
        '[vocab]\nexclude_pos = ["PUNCT", "SYM", "NUM", "X", "INTJ"]\n'
        '[[sources]]\nid = "songs"\nplugin = "vocab_miner.sources.subtitle:SubtitleSource"\n'
        'path = "songs"\nlang = "en"\nvideo_list = "list.tsv"\n', encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["ingest", "--root", str(tmp_path)]).exit_code == 0
    corpus = list(read_jsonl(tmp_path / "data" / "corpus" / "songs.jsonl"))
    assert len(corpus) == 3

    todo = tmp_path / "todo.tsv"
    res = runner.invoke(app, ["gloss-todo", "--root", str(tmp_path), "-o", str(todo)])
    assert res.exit_code == 0, res.output
    rows = list(csv.DictReader(todo.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    sing = next(r for r in rows if r["lemma"] == "sing")
    assert sing["short"] == "" and sing["pos_label"] == "動詞" and sing["pos"] == "VERB"
    assert not any(r["lemma"] == "la" for r in rows)

    sing["gloss"], sing["short"] = "唱（歌）", "唱"
    with todo.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    assert runner.invoke(app, ["gloss-import", str(todo), "--root", str(tmp_path)]).exit_code == 0

    res = runner.invoke(app, ["web", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    data = json.loads((tmp_path / "out" / "web" / "songs.json").read_text(encoding="utf-8"))
    assert data["lang"] == "en"
    word = next(w for w in data["words"] if w["lemma"] == "sing")
    assert word["zh"] == "唱（歌）" and word["short"] == "唱" and word["romaji"] == ""
    doc = data["docs"][0]
    assert doc["title"] == "Morning Walk" and doc["media"] == {"kind": "youtube", "uri": VID}
    assert doc["transcribed"] is True
    assert all(line["romaji"] == "" and line["wr"] == [] for line in doc["lines"])
    assert "".join(s[0] for s in doc["lines"][0]["seg"]) == "I'm walking down the quiet streets"
