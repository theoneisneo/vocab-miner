import pytest

pytest.importorskip("fugashi")

from vocab_miner.tokenizers.ja import (
    HepburnRomanizer,
    JapaneseTokenizer,
    align_readings,
    kata_to_hira,
    pos_label,
    upos,
)


@pytest.fixture(scope="module")
def tok():
    return JapaneseTokenizer()


def test_kata_to_hira():
    assert kata_to_hira("カタカナとひらがな") == "かたかなとひらがな"


def test_tokenize_lemma_base_and_readings(tok):
    ts = tok.tokenize("駅まで歩いて、電車に乗った。")
    by_surface = {t.surface: t for t in ts}
    walk = by_surface["歩い"]
    assert (walk.base, walk.lemma_reading, walk.pos) == ("歩く", "あるく", "VERB")
    assert by_surface["、"].pos == "PUNCT"
    assert ts[0].start == 0 and all(t.end > t.start for t in ts)
    assert "".join(t.surface for t in ts) == "駅まで歩いて、電車に乗った。"


def test_base_form_prefers_written_form(tok):
    (t,) = [t for t in tok.tokenize("宿題をしている") if t.lemma_reading == "する"]
    assert t.base == "する"                 # UniDic lemma is the rare kanji spelling; base keeps the kana


def test_offsets_point_into_text(tok):
    text = "雨　の日 は、静かだ"
    for t in tok.tokenize(text):
        assert text[t.start:t.end] == t.surface


def test_names_are_protected(tok):
    name = "ミラベルカ"
    plain = [t.surface for t in tok.tokenize(f"{name}は走った")]
    assert name not in plain
    protected = tok.with_names([name]).tokenize(f"{name}は走った")
    assert protected[0].surface == name and protected[0].pos == "PROPN" and protected[0].is_proper
    assert protected[0].reading == "みらべるか"
    assert protected[1].start == len(name)


def test_upos_and_labels():
    assert upos("名詞", "固有名詞") == "PROPN"
    assert upos("助詞", "終助詞") == "PART"
    assert upos("形状詞", "一般") == "ADJ"
    assert pos_label("形状詞-一般") == "な形容詞"
    assert pos_label("形容詞-一般") == "い形容詞"
    assert pos_label("名詞-固有名詞-人名") == "專有名詞"


@pytest.mark.parametrize("kana, expected", [
    ("とうきょう", "toukyou"), ("きんようび", "kin'youbi"), ("まっちゃ", "matcha"), ("がっこう", "gakkou"),
    ("しんや", "shin'ya"), ("おんな", "onna"), ("ラーメン", "raamen"), ("ふじさん", "fujisan"),
    ("ちぢみ", "chijimi"), ("ティーカップ", "tiikappu"), ("ヴァイオリン", "vaiorin"), ("あっ", "a'"),
])
def test_hepburn(kana, expected):
    assert HepburnRomanizer().romanize(kana) == expected


def test_hepburn_macrons_and_particles(tok):
    r = HepburnRomanizer(macrons=True)
    assert r.romanize("とうきょう") == "tōkyō"
    plain = HepburnRomanizer()
    assert plain.romanize_word("は", "は", "ADP") == "wa"
    assert plain.romanize_word("葉", "は", "NOUN") == "ha"
    assert plain.romanize_tokens(tok.tokenize("駅へ行く")) == "eki e iku"


# ---------- reading alignment from source-provided readings ----------

def readings(tokens):
    return [(t.surface, t.reading) for t in tokens]


def test_align_fixes_reading_and_lemma_reading(tok):
    ts = align_readings(tok.tokenize("目を擦る"), "めをこする")
    t = next(t for t in ts if t.surface == "擦る")
    assert (t.reading, t.lemma_reading) == ("こする", "こする")


def test_align_okurigana_inflection(tok):
    ts = align_readings(tok.tokenize("涙が溢れた"), "なみだがこぼれた")
    t = next(t for t in ts if t.surface.startswith("溢"))
    assert t.reading == "こぼれ" and t.lemma_reading == "こぼれる"


def test_align_prefers_fewest_changes(tok):
    # two kanji words in a row: the split must not borrow kana from the neighbour
    ts = align_readings(tok.tokenize("明日世界が"), "あしたせかいが")
    assert ("世界", "せかい") in readings(ts)
    assert ("明日", "あした") in readings(ts)


def test_align_rendaku_keeps_lemma_reading(tok):
    ts = tok.tokenize("山寺")
    if len(ts) != 2:
        pytest.skip("tokenized as one word")
    out = align_readings(ts, "やまでら")
    t = out[1]
    if t.reading != "でら":
        pytest.skip("dictionary already has the voiced reading")
    assert t.lemma_reading == ts[1].lemma_reading


def test_align_mismatch_leaves_tokens(tok):
    ts = tok.tokenize("雨が降る")
    assert align_readings(ts, "まったくちがう") == ts
    assert align_readings(ts, "") == ts


def test_align_skips_digits_and_punctuation(tok):
    ts = tok.tokenize("2人で、行く！")
    out = align_readings(ts, "ふたりでいく")
    assert next(t for t in out if t.surface == "2").reading is None


def test_te_form_auxiliaries_become_grammar_patterns(tok):
    plain = [t for t in tok.tokenize("猫がいる") if t.lemma_reading == "いる"]
    assert plain and plain[0].pos == "VERB"                       # 'to be' stays a vocabulary word
    aux = {t.surface: t for t in tok.tokenize("見ている") if t.pos == "AUX"}
    assert aux["いる"].lemma == "〜ている" and aux["いる"].lemma_reading == "ている"
    assert aux["いる"].reading == "いる"                          # surface reading unchanged (furigana)
    assert {t.lemma for t in tok.tokenize("読んでみる") if t.pos == "AUX"} == {"〜てみる"}   # で -> named with て
    assert {t.lemma for t in tok.tokenize("見て見る") if t.pos == "AUX"} == {"〜てみる"}     # kana name
    assert {t.lemma for t in tok.tokenize("来ていい") if t.pos == "AUX"} == {"〜ていい"}
    assert HepburnRomanizer().romanize_tokens(tok.tokenize("食べてしまった")) == "tabete shimatta"
