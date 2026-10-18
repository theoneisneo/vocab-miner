import csv
import gzip
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vocab_miner.cli import app
from vocab_miner.config import load_config
from vocab_miner.dictionaries.jmdict import JMdictDictionary
from vocab_miner.dictionaries.tsv import TsvGlossDictionary, append_rows, read_rows
from vocab_miner.examples import DefaultExampleSelector
from vocab_miner.export.csv import COLUMNS, CsvExporter, media_link
from vocab_miner.index import Index
from vocab_miner.model import MediaRef, Token, Utterance, VocabEntry
from vocab_miner.rankers import FrequencyRanker
from vocab_miner.vocab import (
    VocabOptions,
    add_coverage,
    apply_false_friends,
    apply_status,
    collect,
    load_false_friends,
)

FIX = Path(__file__).parent / "fixtures"


def utt(i, doc, text, **kw):
    return Utterance(id=f"s:{doc}:{i}", source_id="s", doc_id=doc, seq=i, lang="ja", text=text, **kw)


def fake_tokenize(u: Utterance) -> list[Token]:
    """Whitespace 'tokenizer' so index/vocab tests do not depend on a dictionary."""
    out, pos = [], 0
    for w in u.text.split():
        start = u.text.index(w, pos)
        pos = start + len(w)
        p = "PUNCT" if w in "。、" else "PROPN" if w.istitle() else "NOUN"
        out.append(Token(surface=w, lemma=w.rstrip("s"), reading=w, pos=p, pos_native=p, start=start, end=pos,
                         is_proper=p == "PROPN", base=w.rstrip("s"), lemma_reading=w.rstrip("s")))
    return out


@pytest.fixture
def index(tmp_path):
    idx = Index(tmp_path / "i.sqlite")
    us = [
        utt(1, "a", "rain falls 。", translations={"zh-Hant": "下雨"}),
        utt(2, "a", "rain rains Tom", media=MediaRef("youtube", "VID", 3.0, 5.0)),
        utt(1, "b", "sun falls"),
        utt(1, "c", "rain rain rain", tags=["no-stats", "title:Alt"]),
    ]
    idx.add_source("s", tmp_path / "s.jsonl", "sig", us, fake_tokenize)
    yield idx
    idx.close()


def test_index_queries(index):
    assert index.signature("s") == "sig" and index.source_ids() == ["s"]
    assert [t.surface for t in index.tokens("s:a:2")] == ["rain", "rains", "Tom"]
    assert index.utterance_ids_for("rain\train") == ["s:a:1", "s:a:2", "s:c:1"]   # includes no-stats
    assert index.doc_titles()[("s", "c")] == "Alt"
    assert index.utterance("s:a:2").media.uri == "VID"
    assert index.remove_missing(set()) == ["s"] and index.source_ids() == []


def test_collect_counts_skip_no_stats_punct_and_names(index):
    entries = {e.key: e for e in collect(index, "ja", VocabOptions())}
    rain = entries["rain\train"]
    assert (rain.count, rain.doc_freq, rain.forms[0]) == (3, 1, "rain")       # doc c is no-stats
    assert set(rain.forms) == {"rain", "rains"}
    assert "Tom\tTom" not in entries and "。\t。" not in entries
    with_names = {e.key for e in collect(index, "ja", VocabOptions(include_proper=True))}
    assert "Tom\tTom" in with_names


def test_collect_filters_by_doc(index):
    entries = collect(index, "ja", VocabOptions(), doc_ids=["b"])
    assert {e.lemma for e in entries} == {"sun", "fall"}


def test_rank_and_coverage(index):
    entries = FrequencyRanker().rank(collect(index, "ja", VocabOptions()), set())
    assert [e.lemma for e in entries] == ["fall", "rain", "sun"]              # fall is in 2 docs
    assert [e.rank for e in entries] == [1, 2, 3]
    add_coverage(entries)
    assert entries[-1].coverage == pytest.approx(1.0)
    by_count = FrequencyRanker(by="count").rank(entries, set())
    assert by_count[0].lemma == "rain"
    with pytest.raises(ValueError):
        FrequencyRanker(by="alpha")


def test_status_and_false_friends():
    es = [VocabEntry(lemma="手紙", lang="ja", pos="NOUN", key="手紙\tてがみ", reading="てがみ"),
          VocabEntry(lemma="する", lang="ja", pos="VERB", key="為る\tする", reading="する"),
          VocabEntry(lemma="大家", lang="ja", pos="NOUN", key="大家\tたいか", reading="たいか")]
    apply_status(es, known={"為る"}, learning={"手紙"})
    assert [e.status for e in es] == ["learning", "known", "new"]
    table = load_false_friends("ja", "zh-Hant")
    apply_false_friends(es, table)
    assert "信件" in es[0].false_friend
    assert es[2].false_friend is None                                     # restricted to another reading


def test_example_selector_prefers_media_translation_and_spreads_docs():
    e = VocabEntry(lemma="x", lang="ja", pos="NOUN", key="x\tx")
    cands = [utt(1, "a", "あああああああ"), utt(2, "a", "いいいいいいい", translations={"zh-Hant": "z"}),
             utt(3, "a", "ううううううう", translations={"zh-Hant": "z"}, media=MediaRef("youtube", "V", 1.0)),
             utt(1, "b", "えええええええ"), utt(1, "c", "おおお", tags=["spoiler"])]
    sel = DefaultExampleSelector()
    assert sel.select(e, cands, set(), 2) == ["s:a:3", "s:b:1"]
    assert "s:c:1" not in sel.select(e, cands, set(), 10)
    assert len(sel.select(e, cands, set(), 3)) == 3


def test_tsv_gloss_dictionary_and_append(tmp_path):
    path = tmp_path / "g.tsv"
    assert append_rows(path, [{"lemma": "雨", "reading": "あめ", "gloss": "雨"}]) == 1
    assert append_rows(path, [{"lemma": "雨", "reading": "あめ", "gloss": "changed"},
                              {"lemma": "する", "reading": "する", "gloss": "做"}]) == 1   # never overwrites
    rows = read_rows(path)
    assert [r["gloss"] for r in rows] == ["雨", "做"] and rows[0]["origin"] == "machine"
    d = TsvGlossDictionary(path, "zh-Hant")
    assert d.lookup("為る", "する", base="する") == {"zh-Hant": "做"}
    assert d.lookup("雨", "あめ") == {"zh-Hant": "雨"}
    assert d.lookup("無い") == {}


MINI_JMDICT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMdict [
<!ENTITY n "noun (common) (futsuumeishi)">
<!ENTITY v1 "Ichidan verb">
<!ENTITY prt "particle">
<!ENTITY uk "word usually written using kana alone">
]>
<JMdict>
<entry><ent_seq>1</ent_seq><k_ele><keb>葉</keb><ke_pri>ichi1</ke_pri></k_ele><r_ele><reb>は</reb></r_ele>
<sense><pos>&n;</pos><gloss>leaf</gloss></sense></entry>
<entry><ent_seq>2</ent_seq><r_ele><reb>は</reb></r_ele>
<sense><pos>&prt;</pos><gloss>topic marker</gloss></sense></entry>
<entry><ent_seq>3</ent_seq><k_ele><keb>食べる</keb><ke_pri>ichi1</ke_pri></k_ele><r_ele><reb>たべる</reb></r_ele>
<sense><pos>&v1;</pos><gloss>to eat</gloss><gloss>to live on</gloss></sense>
<sense><gloss>to make a living</gloss></sense></entry>
<entry><ent_seq>4</ent_seq><k_ele><keb>為る</keb></k_ele><r_ele><reb>する</reb></r_ele>
<sense><pos>&v1;</pos><misc>&uk;</misc><gloss>to do</gloss></sense></entry>
</JMdict>
"""


def test_jmdict_lookup(tmp_path):
    gz = tmp_path / "JMdict_e.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        f.write(MINI_JMDICT)
    d = JMdictDictionary(gz, max_senses=2, max_glosses=1)
    assert d.lookup("食べる", "たべる", "VERB") == {"en": "to eat / to make a living"}
    assert d.lookup("は", "は", "ADP") == {"en": "topic marker"}
    assert d.lookup("葉", "は", "NOUN") == {"en": "leaf"}
    assert d.lookup("為る", "する", "VERB", base="する") == {"en": "to do"}
    assert d.lookup("歯", "は", "NOUN") == {}                              # homophone only: no match
    assert d.db_path.is_file()
    with pytest.raises(FileNotFoundError):
        JMdictDictionary(tmp_path / "missing.gz").lookup("x")


def test_csv_export(tmp_path):
    u = utt(1, "a", "雨が降る", translations={"zh-Hant": "下雨"}, media=MediaRef("youtube", "VID", 12.7))
    e = VocabEntry(lemma="雨", lang="ja", pos="NOUN", pos_label="名詞", reading="あめ", romaji="ame",
                   gloss={"zh-Hant": "雨", "en": "rain"}, count=3, doc_freq=2, coverage=0.125,
                   forms=["雨"], docs=["A", "B"], false_friend="x", examples=[u.id], rank=1)
    out = tmp_path / "v.csv"
    CsvExporter().export([e], {u.id: u}, out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")                    # BOM for Excel
    (row,) = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert list(row) == COLUMNS
    assert row["coverage"] == "12.5%" and row["docs"] == "A、B" and row["false_friend"] == "⚠ x"
    assert row["example_link"] == "https://www.youtube.com/watch?v=VID&t=12s"
    assert media_link(MediaRef("file", "a.mp3", 1.5)) == "a.mp3#t=1.50"


def test_cli_build_and_vocab_end_to_end(tmp_path):
    pytest.importorskip("fugashi")
    shutil.copy(FIX / "ja_sample.txt", tmp_path / "ja_sample.txt")
    (tmp_path / "config.toml").write_text(
        '[[sources]]\nid = "demo/text"\nplugin = "vocab_miner.sources.text:TextSource"\n'
        'path = "ja_sample.txt"\nlang = "ja"\n'
        '[[dictionaries]]\nplugin = "vocab_miner.dictionaries.tsv:TsvGlossDictionary"\n'
        'path = "data/gloss/ja-zh.tsv"\ngloss_lang = "zh-Hant"\n', encoding="utf-8")
    (tmp_path / "data" / "gloss").mkdir(parents=True)
    (tmp_path / "data" / "gloss" / "ja-zh.tsv").write_text("雨\tあめ\t雨\tuser\n", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["ingest", "--root", str(tmp_path)]).exit_code == 0
    res = runner.invoke(app, ["build", "--root", str(tmp_path)])
    assert res.exit_code == 0 and "indexed 8" in res.output
    assert "up to date" in runner.invoke(app, ["build", "--root", str(tmp_path)]).output
    res = runner.invoke(app, ["vocab", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    rows = list(csv.DictReader((tmp_path / "out" / "vocab.csv").open(encoding="utf-8-sig")))
    rain = next(r for r in rows if r["lemma"] == "雨")
    assert rain["gloss_zh"] == "雨" and rain["romaji"] == "ame" and rain["doc_freq"] == "1"
    assert int(rain["count"]) == 2 and rain["example"]
    assert not any(r["lemma"] in ("は", "が", "た") for r in rows)          # grammar words are split off
    grammar = list(csv.DictReader((tmp_path / "out" / "grammar.csv").open(encoding="utf-8-sig")))
    assert {"は", "た"} <= {r["lemma"] for r in grammar}
    assert next(r for r in grammar if r["lemma"] == "は")["romaji"] == "wa"
    assert float(rows[-1]["coverage"].rstrip("%")) == pytest.approx(100.0)   # coverage within each list
    assert load_config(tmp_path).out_dir == tmp_path / "out"


def test_tsv_gloss_pos_disambiguates(tmp_path):
    path = tmp_path / "g.tsv"
    append_rows(path, [{"lemma": "ない", "reading": "ない", "gloss": "not", "pos": "AUX"},
                       {"lemma": "ない", "reading": "ない", "gloss": "nonexistent", "pos": "ADJ"},
                       {"lemma": "雨", "reading": "あめ", "gloss": "rain"}])
    d = TsvGlossDictionary(path, "en")
    assert d.lookup("無い", "ない", "AUX", base="ない") == {"en": "not"}
    assert d.lookup("無い", "ない", "ADJ", base="ない") == {"en": "nonexistent"}
    assert d.lookup("雨", "あめ", "NOUN") == {"en": "rain"}                 # rows without pos match any pos


def test_tsv_short_column(tmp_path):
    path = tmp_path / "g.tsv"
    append_rows(path, [{"lemma": "セーブ", "reading": "せーぶ", "gloss": "節省；存檔", "short": "保存"},
                       {"lemma": "雨", "reading": "あめ", "gloss": "雨"}])
    d = TsvGlossDictionary(path, "zh-Hant")
    assert d.lookup("セーブ", "せーぶ") == {"zh-Hant": "節省；存檔", "zh-Hant:short": "保存"}
    assert d.lookup("雨", "あめ") == {"zh-Hant": "雨"}                       # no short: none returned
    assert read_rows(path)[0]["short"] == "保存"
