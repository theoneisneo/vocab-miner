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
    us = list(LrcSource("songs/demo", SUBS, "ja").utterances())
    assert len(us) == 5                                         # the empty [00:12.00] line is dropped
    assert {u.doc_id for u in us} == {"sample"}
    assert all(u.media is None for u in us)


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
    for f in SUBS.iterdir():
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "sample.mp3").write_bytes(b"")
    us = list(SubtitleSource("s", tmp_path, "ja").utterances())
    assert len(us) == 5 + 2 + 2
    lrc = [u for u in us if u.media and u.media.kind == "file"]
    assert lrc and all(Path(u.media.uri).name == "sample.mp3" for u in lrc)
