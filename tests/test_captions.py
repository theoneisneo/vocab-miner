from pathlib import Path

from vocab_miner import captions
from vocab_miner.model import UNTIMED_TAG
from vocab_miner.sources.subtitle import SubtitleSource

# the shape of an automatic-caption track: each cue repeats the line before and adds a new last line with
# a start time for each word after the first; 10 ms cues only repeat text
VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:04.000 align:start position:0%

morning<00:00:01.500><c> rain</c><00:00:02.000><c> falls</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
morning rain falls


00:00:04.010 --> 00:00:08.000 align:start position:0%
morning rain falls
on<00:00:05.000><c> the</c><00:00:05.400><c> quiet</c><00:00:06.000><c> town</c>
"""


def test_caption_words():
    words = captions.caption_words(VTT)
    assert [w.text for w in words] == ["morning", "rain", "falls", "on", "the", "quiet", "town"]
    assert [w.start for w in words] == [1.0, 1.5, 2.0, 4.01, 5.0, 5.4, 6.0]
    assert words[2].end == 4.0 and words[-1].end == 8.0


def test_pick_track_only_original_recognition():
    assert captions.pick_track({"automatic_captions": {"ja-orig": [], "ja": [], "en": []}}, "ja") == "ja-orig"
    assert captions.pick_track({"automatic_captions": {"ja": []}, "language": "ja"}, "ja") == "ja"
    assert captions.pick_track({"automatic_captions": {"ja": [], "es-orig": []}, "language": "es"}, "ja") is None


def test_time_lyrics_from_cached_captions(tmp_path: Path):
    (tmp_path / "vid.vtt").write_text(VTT, encoding="utf-8")
    lines, note = captions.time_lyrics("vid", ["Morning rain falls", "On the quiet town"], "en", tmp_path)
    assert [(ln.text, round(ln.start, 2)) for ln in lines] == [("Morning rain falls", 1.0 - captions.LEAD),
                                                               ("On the quiet town", round(4.01 - captions.LEAD, 2))]
    assert "100%" in note
    lines, note = captions.time_lyrics("vid", ["Something else entirely", "Nothing like it"], "en", tmp_path)
    assert lines is None and "match" in note


def test_untimed_lyrics_are_read_for_listed_videos(tmp_path: Path):
    (tmp_path / "videos.tsv").write_text("index\tid\ttitle\n1\tvid1\tSong One\n2\tvid2\tSong Two\n",
                                         encoding="utf-8")
    (tmp_path / "vid1.txt").write_text("first line\n\nsecond line\n", encoding="utf-8")
    (tmp_path / "vid2.txt").write_text("not used\n", encoding="utf-8")
    (tmp_path / "vid2.lrc").write_text("[00:01.00]timed line\n", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("vid3\n", encoding="utf-8")            # not a song
    (tmp_path / ".captions").mkdir()
    (tmp_path / ".captions" / "vid1.vtt").write_text(VTT, encoding="utf-8")   # cache: not a song either
    src = SubtitleSource("songs/x", tmp_path, "en", video_list=tmp_path / "videos.tsv")
    us = list(src.utterances())
    assert sorted({u.doc_id for u in us}) == ["vid1", "vid2"]
    untimed = [u for u in us if u.doc_id == "vid1"]
    assert [u.text for u in untimed] == ["first line", "second line"]
    assert all(UNTIMED_TAG in u.tags and u.media.uri == "vid1" and u.media.start is None for u in untimed)
    assert [u.text for u in us if u.doc_id == "vid2"] == ["timed line"]
