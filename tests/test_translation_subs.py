from pathlib import Path

from vocab_miner import translation_subs as ts
from vocab_miner.sources.subtitle import Cue, parse_lrc
from vocab_miner.transcribe import MADE_UP


def test_pick_track_prefers_the_wanted_script():
    assert ts.pick_track(["zh-Hans", "zh-Hant", "en"], "zh-Hant") == "zh-Hant"
    assert ts.pick_track(["zh", "en"], "zh-Hant") == "zh"
    assert ts.pick_track(["zh-Hans"], "zh-Hant") == "zh-Hans"
    assert ts.pick_track(["en-US", "ja"], "en") == "en-US"
    assert ts.pick_track(["ja"], "zh-Hant") is None


def test_converter_simplified_to_traditional():
    assert ts.converter("zh-Hant", "zh-Hant")("后来") == "后来"           # already the wanted track: unchanged
    assert ts.converter("zh-Hans", "zh-Hant")("后来的头发") == "後來的頭髮"
    assert ts.converter("en", "en")("hello") == "hello"


def test_align_joins_split_cues_and_places_cues_in_gaps():
    lines = parse_lrc("[00:01.00]line one\n[00:05.00]line two\n[00:09.00]\n[00:20.00]line three\n")
    subs = [Cue(1.0, 3.0, "first half"), Cue(3.0, 4.9, "second half"), Cue(5.2, 8.5, "two"),
            Cue(17.0, 19.0, "three, a little early")]
    assert ts.align(lines, subs) == [(1.0, "first half second half"), (5.0, "two"),
                                     (20.0, "three, a little early")]


def test_squeezed_and_retime(tmp_path: Path):
    lrc = tmp_path / "song.lrc"
    body = "\n".join(f"[00:{50 + i // 4:02d}.{(i % 4) * 25:02d}]line {i}" for i in range(6))
    lrc.write_text("[ti:Song]\n[re:vocab-miner: lyrics timed with Whisper]\n" + body + "\n", encoding="utf-8")
    assert ts.squeezed([c.start for c in ts.sung(parse_lrc(lrc.read_text(encoding="utf-8")))]) >= ts.SQUEEZED_RUN
    subs = [Cue(10.0 * (i + 1), 10.0 * (i + 1) + 5, f"t{i}") for i in range(6)]
    assert ts.retime(lrc, subs)
    cues = ts.sung(parse_lrc(lrc.read_text(encoding="utf-8")))
    assert [c.start for c in cues] == [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    assert [c.text for c in cues] == [f"line {i}" for i in range(6)]
    assert (tmp_path / "song.lrc.bak").exists()
    assert not ts.retime(lrc, subs[:5])                  # counts differ: left alone


def test_retime_leaves_lyrics_from_elsewhere(tmp_path: Path):
    lrc = tmp_path / "song.lrc"
    lrc.write_text("[re:LRCLIB 1]\n" + "\n".join(f"[00:01.{i:02d}]x{i}" for i in range(6)) + "\n", encoding="utf-8")
    assert not ts.retime(lrc, [Cue(float(i), i + 1.0, "t") for i in range(6)])


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: one video with a Simplified Chinese track."""
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        return {"subtitles": {"zh-Hans": [{}]} if url.endswith("vid1") else {}}

    def download(self, urls):
        Path(self.opts["outtmpl"].replace("%(ext)s", "zh-Hans.vtt")).write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n头发\n\n00:00:05.000 --> 00:00:07.000\n后来\n",
            encoding="utf-8")


def test_fetch_writes_translation_files_and_remembers_videos_without(tmp_path: Path):
    for vid in ("vid1", "vid2"):
        (tmp_path / f"{vid}.lrc").write_text("[00:01.00]one\n[00:05.00]two\n[00:08.00]\n", encoding="utf-8")
    rows = [{"id": "vid1", "title": "A"}, {"id": "vid2", "title": "B"}]
    lyrics_of = lambda vid: tmp_path / f"{vid}.lrc"
    res = ts.fetch(rows, tmp_path, ["zh-Hant"], lyrics_of, pause=0, ydl_factory=FakeYDL, log=lambda m: None)
    assert [(r.id, r.status) for r in res] == [("vid1", "written"), ("vid2", "none")]
    assert "[00:01.00]頭髮" in (tmp_path / "vid1.zh-Hant.lrc").read_text(encoding="utf-8")
    assert "[00:05.00]後來" in (tmp_path / "vid1.zh-Hant.lrc").read_text(encoding="utf-8")
    again = ts.fetch(rows, tmp_path, ["zh-Hant"], lyrics_of, pause=0, ydl_factory=FakeYDL, log=lambda m: None)
    assert again == []                                   # file there / remembered as having none


def test_made_up_credit_lines():
    assert MADE_UP.match("作詞・作曲・編曲 誰か")
    assert MADE_UP.match("作曲：誰か")
    assert not MADE_UP.match("作りかけの歌")
