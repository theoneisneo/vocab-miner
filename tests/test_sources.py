from pathlib import Path

import pytest

from vocab_miner.model import MediaRef
from vocab_miner.sources.subtitle import LrcSource, SrtSource, SubtitleSource, VttSource, parse_lrc
from vocab_miner.sources.text import TextSource, split_sentences
from vocab_miner.textclean import clean

FIX = Path(__file__).parent / "fixtures"
SUBS = FIX / "subs"


# ---------- textclean ----------

@pytest.mark.parametrize("raw, expected", [
    ("雨が\r\n降っている", "雨が降っている"),
    ("雨が\\r\\n降っている", "雨が降っている"),          # escaped breaks as found in exported string tables
    ("<color=red>{0}</color>は来た", "は来た"),
    ("[音楽] こんにちは", "こんにちは"),
    ("Hello\nworld", "Hello world"),
    ("  雨　　です  ", "雨 です"),
])
def test_clean(raw, expected):
    assert clean(raw) == expected


def test_clean_keeps_codes_when_disabled():
    assert clean("{0}です", control_codes=False) == "{0}です"


# ---------- TextSource ----------

def test_text_source_lines():
    us = list(TextSource("demo/text", FIX / "ja_sample.txt", "ja").utterances())
    assert len(us) == 8
    assert us[0].id == "demo/text:ja_sample:1"
    assert us[0].doc_id == "ja_sample" and us[0].seq == 1 and us[0].lang == "ja"
    assert us[0].text == "今日は朝から雨が降っている。"
    assert all(u.media is None and not u.translations for u in us)


def test_text_source_directory_and_modes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("雨が\n降った。風も吹いた！\n\n晴れた？", encoding="utf-8-sig")
    (tmp_path / "skip.md").write_text("ignored", encoding="utf-8")

    para = list(TextSource("t", tmp_path, "ja", split="paragraph").utterances())
    assert [u.text for u in para] == ["雨が降った。風も吹いた！", "晴れた？"]
    assert para[0].doc_id == "a/one"

    sent = list(TextSource("t", tmp_path, "ja", split="sentence").utterances())
    assert [u.text for u in sent] == ["雨が降った。", "風も吹いた！", "晴れた？"]
    assert [u.seq for u in sent] == [1, 2, 3]


def test_split_sentences_keeps_closing_quote():
    assert split_sentences("「行こう。」と言った。また") == ["「行こう。」", "と言った。", "また"]


def test_text_source_rejects_bad_split():
    with pytest.raises(ValueError):
        TextSource("t", FIX, "ja", split="word")


# ---------- subtitles ----------

def test_parse_lrc_repeats_sorts_and_strips_word_stamps():
    cues = parse_lrc((SUBS / "sample.lrc").read_text(encoding="utf-8"))
    starts = [c.start for c in cues]
    assert starts == sorted(starts)
    assert starts == [1.0, 4.5, 8.25, 12.0, 14.0, 20.0]
    assert cues[1].text == "駅まで歩いて、電車に乗った。"
    assert cues[0].end == 4.5 and cues[-1].end is None
    assert cues[2].text == cues[5].text                        # [00:08.25][00:20.00] repeated line


def test_parse_lrc_offset():
    cues = parse_lrc("[offset:500]\n[00:02.00]a\n[00:03.00]b")
    assert [(c.start, c.end) for c in cues] == [(1.5, 2.5), (2.5, None)]


def test_lrc_source_skips_empty_lines():
    us = list(LrcSource("songs/demo", SUBS / "sample.lrc", "ja").utterances())
    assert len(us) == 5                                         # the empty [00:12.00] line is dropped
    assert {u.doc_id for u in us} == {"sample"}
    assert all(u.media is None for u in us)


def test_directory_skips_translation_files():
    docs = {u.doc_id for u in LrcSource("songs/demo", SUBS, "ja").utterances()}
    assert docs == {"sample", "bilingual"}                       # sample.zh-Hant.lrc is not a doc


def test_srt_source():
    us = list(SrtSource("subs/demo", SUBS / "sample.srt", "ja").utterances())
    assert [u.text for u in us] == ["今日は朝から雨が降っている。", "さん、おはよう。"]   # "[音楽]" cue becomes empty
    assert us[0].media is None


def test_vtt_source_with_youtube():
    src = VttSource("subs/demo", SUBS / "sample.vtt", "ja", youtube={"sample": "VIDEO_ID_01"})
    us = list(src.utterances())
    assert [u.text for u in us] == ["二人でコーヒーを飲みながら、昔の話をした。", "雨はいつの間にか止んでいた。"]
    assert us[0].media == MediaRef(kind="youtube", uri="VIDEO_ID_01", start=1.0, end=3.0)
    assert us[1].media.start == 3604.0 and us[1].media.end == 3605.5


def test_subtitle_source_reads_all_kinds_and_finds_local_audio(tmp_path):
    for f in SUBS.glob("sample.*"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "sample.mp3").write_bytes(b"")
    us = list(SubtitleSource("s", tmp_path, "ja").utterances())
    assert len(us) == 5 + 2 + 2
    lrc = [u for u in us if u.media and u.media.kind == "file"]
    assert lrc and all(Path(u.media.uri).name == "sample.mp3" for u in lrc)


# ---------- bilingual subtitles ----------

def test_translation_last_line():
    us = list(SrtSource("s", SUBS / "bilingual.srt", "ja", translations={"zh-Hant": "last-line"}).utterances())
    assert [u.text for u in us] == ["今日は朝から雨が降っている。", "駅まで歩いた。", "♪"]
    assert [u.translations for u in us] == [{"zh-Hant": "今天從早上就在下雨。"}, {"zh-Hant": "走到了車站。"}, {}]
    # without the option both lines are one utterance
    plain = list(SrtSource("s", SUBS / "bilingual.srt", "ja").utterances())
    assert plain[0].text == "今日は朝から雨が降っている。今天從早上就在下雨。" and not plain[0].translations


def test_translation_same_time():
    us = list(LrcSource("s", SUBS / "bilingual.lrc", "ja", translations={"zh-Hant": "same-time"},
                        youtube={"bilingual": "VID"}).utterances())
    assert [u.text for u in us] == ["窓の外の街はまだ静かだった。", "友達に会うのは久しぶりだ。", "明日もまた会おう。"]
    assert us[0].translations == {"zh-Hant": "窗外的街道還很安靜。"} and us[2].translations == {}
    assert (us[0].media.start, us[0].media.end) == (1.0, 5.0)    # ends at the next original line
    assert [u.seq for u in us] == [1, 2, 3]


def test_translation_sidecar_file_matched_by_time():
    us = list(LrcSource("s", SUBS / "sample.lrc", "ja", translations={"zh-Hant": "file"}).utterances())
    tr = [u.translations.get("zh-Hant") for u in us]
    # 1.0 exact, 4.5 ~ 4.55, 8.25 ~ 8.2, 14.0 exact, 20.0 ~ 20.1
    assert tr == ["今天從早上就在下雨。", "走路去車站，搭上了電車。", "窗外的街道還很安靜。",
                  "好久沒見到朋友了。", "窗外的街道還很安靜。"]


def test_translation_sidecar_missing_is_fine():
    us = list(VttSource("s", SUBS / "sample.vtt", "ja", translations={"en": "file"}).utterances())
    assert all(not u.translations for u in us)


def test_translation_layout_validated():
    with pytest.raises(ValueError):
        SrtSource("s", SUBS, "ja", translations={"zh-Hant": "below"})


def test_clean_unescapes_html_entities():
    assert clean("aren&#x27;t &amp; won&#39;t") == "aren't & won't"


# ---------- lines merged in the web app ----------

def test_merge_lrc_joins_lines_and_skips_repeats_and_done():
    from vocab_miner.sources.subtitle import merge_lrc
    text = (SUBS / "sample.lrc").read_text(encoding="utf-8")
    new, n = merge_lrc(text, [[1.0, 4.5], [8.25, 14.0], [99.0, 100.0]])
    assert n == 1                                    # 8.25 sits on a repeated line; 99 is not there
    cues = [c for c in parse_lrc(new) if c.text]
    assert [c.start for c in cues][:2] == [1.0, 8.25]
    assert cues[0].text == "今日は朝から雨が降っている。 駅まで歩いて、電車に乗った。"
    assert merge_lrc(new, [[1.0, 4.5]])[1] == 0     # already merged


def test_merge_lrc_bilingual_same_time():
    from vocab_miner.sources.subtitle import merge_lrc
    new, n = merge_lrc((SUBS / "bilingual.lrc").read_text(encoding="utf-8"), [[1.0, 5.0]])
    assert n == 1
    assert [c.text for c in parse_lrc(new)][:2] == ["窓の外の街はまだ静かだった。 友達に会うのは久しぶりだ。",
                                                    "窗外的街道還很安靜。 好久沒見到朋友了。"]


def test_source_merge_lines_edits_lrc_and_translation_file(tmp_path):
    for name in ("sample.lrc", "sample.zh-Hant.lrc"):
        (tmp_path / name).write_text((SUBS / name).read_text(encoding="utf-8"), encoding="utf-8")
    src = LrcSource("s", tmp_path, "ja", translations={"zh-Hant": "file"})
    assert src.merge_lines("sample", [[1.0, 4.5]]) == 1
    us = list(src.utterances())
    assert us[0].text == "今日は朝から雨が降っている。駅まで歩いて、電車に乗った。"     # cleaning drops the space
    assert us[0].translations == {"zh-Hant": "今天從早上就在下雨。走路去車站，搭上了電車。"}
    assert (tmp_path / "sample.lrc.bak").read_text(encoding="utf-8") == (SUBS / "sample.lrc").read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        src.merge_lines("nope", [[1.0, 4.5]])


def test_read_merges_from_exported_data(tmp_path):
    import json

    from vocab_miner.edits import read_merges
    m = [{"id": "s:sample:1", "start": 1.0, "text": "a"}, {"id": "s:sample:2", "start": 4.5, "text": "b"}]
    data = {"docs": [{"source": "s", "doc": "sample", "title": "T", "lines": [{"start": 1.0, "merged": m}, {"start": 9}]},
                     {"source": "s", "doc": "other", "lines": [{"start": 1.0}]}]}
    (tmp_path / "e.json").write_text(json.dumps(data), encoding="utf-8")
    edits = read_merges(tmp_path / "e.json")
    assert [(e.source_id, e.doc_id, e.title, len(e.groups)) for e in edits] == [("s", "sample", "T", 1)]
