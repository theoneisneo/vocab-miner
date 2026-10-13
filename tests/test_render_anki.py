import sqlite3
import zipfile

import pytest

from vocab_miner.model import MediaRef, Token, Utterance, VocabEntry
from vocab_miner.render import anki_furigana, html_ruby, segments, split_okurigana


def tok(surface, start, reading=None, key="k\tk", pos="NOUN"):
    lemma, lr = key.split("\t")
    return Token(surface=surface, lemma=lemma, reading=reading, pos=pos, pos_native=pos, start=start,
                 end=start + len(surface), base=lemma, lemma_reading=lr)


@pytest.mark.parametrize("surface, reading, expected", [
    ("食べ", "たべ", [("食", "た"), ("べ", None)]),
    ("お茶", "おちゃ", [("お", None), ("茶", "ちゃ")]),
    ("取り出す", "とりだす", [("取", "と"), ("り", None), ("出", "だ"), ("す", None)]),
    ("今日", "きょう", [("今日", "きょう")]),
    ("カタカナ", "かたかな", [("カタカナ", None)]),
    ("食べ", "のみ", [("食べ", "のみ")]),                  # kana does not fit: whole reading on the whole word
])
def test_split_okurigana(surface, reading, expected):
    assert split_okurigana(surface, reading) == expected


TEXT = "今日、雨が降った"
TOKENS = [tok("今日", 0, "きょう", "今日\tきょう"), tok("、", 2, None, "、\t", "PUNCT"),
          tok("雨", 3, "あめ", "雨\tあめ"), tok("が", 4, "が", "が\tが", "ADP"),
          tok("降っ", 5, "ふっ", "降る\tふる", "VERB"), tok("た", 7, "た", "た\tた", "AUX")]


def test_segments_cover_text():
    segs = segments(TEXT, TOKENS)
    assert "".join(s.text for s in segs) == TEXT
    assert [s.ruby for s in segs if s.ruby] == ["きょう", "あめ", "ふ"]


def test_segments_keep_gaps_and_skip_misaligned_tokens():
    segs = segments("A 雨", [tok("雨", 2, "あめ"), tok("x", 0)])
    assert "".join(s.text for s in segs) == "A 雨"


def test_anki_furigana_and_highlight():
    out = anki_furigana(TEXT, TOKENS, highlight={4, 5})
    assert out == "今日[きょう]、 雨[あめ]が<b> 降[ふ]った</b>"


def test_html_ruby_escapes():
    out = html_ruby("<雨>", [tok("雨", 1, "あめ")], highlight={0})
    assert out == "&lt;<b><ruby>雨<rt>あめ</rt></ruby></b>&gt;"


def test_anki_export(tmp_path):
    pytest.importorskip("genanki")
    from vocab_miner.export.anki import FIELDS, AnkiExporter

    u = Utterance(id="s:d:1", source_id="s", doc_id="d", seq=1, lang="ja", text=TEXT,
                  translations={"zh-Hant": "今天下雨了"}, media=MediaRef("youtube", "VID", 61.5))
    rain = VocabEntry(lemma="雨", lang="ja", pos="NOUN", key="雨\tあめ", reading="あめ", romaji="ame",
                      gloss={"zh-Hant": "雨"}, examples=[u.id], rank=2, docs=["Song"])
    known = VocabEntry(lemma="今日", lang="ja", pos="NOUN", key="今日\tきょう", reading="きょう",
                       rank=1, status="known")
    kana = VocabEntry(lemma="もう", lang="ja", pos="ADV", key="もう\tもう", reading="もう", rank=3)
    out = tmp_path / "v.apkg"
    exp = AnkiExporter(deck="Test", romanize_tokens=lambda ts: "kyou ame ga futta")
    assert exp.export([known, rain, kana], {u.id: u}, out, tokens={u.id: TOKENS}) == 2   # known skipped

    with zipfile.ZipFile(out) as z:
        z.extract("collection.anki2", tmp_path)
    db = sqlite3.connect(tmp_path / "collection.anki2")
    rows = db.execute("SELECT n.flds, n.guid, c.due FROM notes n JOIN cards c ON c.nid = n.id ORDER BY c.due").fetchall()
    assert [r[2] for r in rows] == [2, 3]                                       # new-card order follows rank
    f = dict(zip(FIELDS, rows[0][0].split("\x1f"), strict=True))
    assert f["Word"] == "雨" and f["Reading"] == "あめ" and f["Meaning"] == "雨"
    assert f["Example"] == "今日[きょう]、<b> 雨[あめ]</b>が 降[ふ]った"
    assert f["ExampleMeaning"] == "今天下雨了" and "t=61s" in f["Link"]
    assert f["Key"] == "雨|あめ"
    kana_fields = dict(zip(FIELDS, rows[1][0].split("\x1f"), strict=True))
    assert kana_fields["Reading"] == ""                                        # reading equal to the word: hidden

    # re-export: same GUIDs, so Anki updates notes instead of duplicating them
    out2 = tmp_path / "v2.apkg"
    AnkiExporter(deck="Test").export([rain], {u.id: u}, out2, tokens={u.id: TOKENS})
    with zipfile.ZipFile(out2) as z:
        (tmp_path / "b").mkdir()
        z.extract("collection.anki2", tmp_path / "b")
    guid2 = sqlite3.connect(tmp_path / "b" / "collection.anki2").execute("SELECT guid FROM notes").fetchone()[0]
    assert guid2 == rows[0][1]

    assert AnkiExporter(limit=1).export([rain, kana], {u.id: u}, tmp_path / "l.apkg") == 1


def test_sentence_romaji_attaches_inflection():
    pytest.importorskip("fugashi")
    from vocab_miner.tokenizers.ja import HepburnRomanizer, JapaneseTokenizer

    r, t = HepburnRomanizer(), JapaneseTokenizer()
    assert r.romanize_tokens(t.tokenize("僕は食べられなかった")) == "boku wa taberarenakatta"
    assert r.romanize_tokens(t.tokenize("待って")) == "matte"


def test_web_data():
    from vocab_miner.export.web import FORMAT_VERSION, build_web_data

    u1 = Utterance(id="s:d:1", source_id="s", doc_id="d", seq=1, lang="ja", text=TEXT,
                   translations={"zh-Hant": "今天下雨了"}, media=MediaRef("youtube", "VID", 1.0, 3.0))
    u2 = Utterance(id="s:e:1", source_id="s", doc_id="e", seq=1, lang="ja", text="雨", tags=["no-stats"])
    rain = VocabEntry(lemma="雨", lang="ja", pos="NOUN", key="雨\tあめ", reading="あめ", rank=1,
                      gloss={"zh-Hant": "雨", "en": "rain"})
    ga = VocabEntry(lemma="が", lang="ja", pos="ADP", key="が\tが", reading="が", rank=1)
    d = build_web_data([rain], [ga], [u1, u2], {u1.id: TOKENS}, {("s", "d"): "Song"}, "ja",
                       romanize_tokens=lambda ts: "kyou ame ga futta")
    assert d["format"] == "vocab-miner-web" and d["version"] == FORMAT_VERSION
    assert [w["lemma"] for w in d["words"]] == ["雨", "が"] and d["words"][1]["grammar"] is True
    doc, other = d["docs"]
    assert (doc["title"], doc["media"], doc["noStats"]) == ("Song", {"kind": "youtube", "uri": "VID"}, False)
    assert (other["title"], other["media"], other["noStats"]) == ("e", None, True)
    line = doc["lines"][0]
    assert (line["start"], line["end"], line["tr"], line["romaji"]) == (1.0, 3.0, "今天下雨了", "kyou ame ga futta")
    assert "".join(s[0] for s in line["seg"]) == TEXT
    assert ["雨", "あめ", 0] in line["seg"] and ["が", None, 1] in line["seg"]
    assert ["今日", "きょう", None] in line["seg"]                        # not in the word lists: not linked
    assert other["lines"][0]["seg"] == [["雨", None, None]]               # no tokens: plain text


def test_anki_romaji_front(tmp_path):
    pytest.importorskip("genanki")
    from vocab_miner.export.anki import FIELDS, AnkiExporter

    e = VocabEntry(lemma="雨", lang="ja", pos="NOUN", key="雨\tあめ", reading="あめ", romaji="ame", rank=1)
    for flag, expected in ((True, "ame"), (False, "")):
        out = tmp_path / f"{flag}.apkg"
        AnkiExporter(romaji_front=flag).export([e], {}, out)
        with zipfile.ZipFile(out) as z:
            z.extract("collection.anki2", tmp_path / str(flag))
        db = sqlite3.connect(tmp_path / str(flag) / "collection.anki2")
        f = dict(zip(FIELDS, db.execute("SELECT flds FROM notes").fetchone()[0].split("\x1f"), strict=True))
        assert f["FrontHint"] == expected and f["Romaji"] == "ame"


def test_kana_units_and_deck(tmp_path):
    pytest.importorskip("genanki")
    from vocab_miner.export.kana import KanaDeckExporter, build_units, hiragana_units, katakana_units

    h = hiragana_units()
    assert sum(1 for _, s in h if s == 0) == 46                                # あ..ん incl. を
    assert sum(1 for _, s in h if s == 1) == 26                                # 25 voiced + small tsu
    yoon = {k for k, s in h if s == 2}
    assert len(yoon) == 33 and {"きゃ", "しゅ", "ちょ", "ぴょ"} <= yoon and "かゃ" not in yoon
    k = dict(katakana_units())
    assert k["ア"] == 0 and k["ー"] == 1 and k["ティ"] == 2

    texts = ["のののはは", "ティーカップ"]
    entries = [VocabEntry(lemma="この", lang="ja", pos="DET", key="此の\tこの", reading="この", romaji="kono",
                          gloss={"zh-Hant": "這個"}, rank=1),
               VocabEntry(lemma="カップ", lang="ja", pos="NOUN", key="カップ\tかっぷ", reading="かっぷ",
                          romaji="kappu", rank=2)]
    units = build_units(texts, entries)
    order = [u.kana for u in units]
    assert order[:2] == ["の", "は"]                                         # most frequent basic kana first
    assert order.index("ティ") > order.index("ー") > order.index("カ")       # stages within katakana
    assert "きゃ" not in order                                                # unused combinations are skipped
    no = next(u for u in units if u.kana == "の")
    assert no.count == 3 and "こ<b>の</b>" in no.examples[0] and "這個" in no.examples[0]
    assert next(u for u in units if u.kana == "っ").romaji == "（促音）"

    out = tmp_path / "kana.apkg"
    assert KanaDeckExporter().export(units, out) == len(units)
    with zipfile.ZipFile(out) as z:
        z.extract("collection.anki2", tmp_path)
    db = sqlite3.connect(tmp_path / "collection.anki2")
    import json
    names = {d["name"] for d in json.loads(db.execute("SELECT decks FROM col").fetchone()[0]).values()}
    assert {"五十音::平假名", "五十音::片假名"} <= names
    ha = next(f for (f,) in db.execute("SELECT flds FROM notes") if f.split("\x1f")[1] == "は")
    assert "wa" in ha.split("\x1f")[4]                                         # particle note on は
