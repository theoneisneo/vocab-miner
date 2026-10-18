from pathlib import Path
from typing import ClassVar

import pytest

from vocab_miner.fetch import youtube

VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nThe quick brown fox\n"


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: answers extract_info from a table and 'downloads' a vtt file."""

    videos: ClassVar[dict] = {
        "aaaaaaaaaaa": {"title": "With subtitles", "subtitles": {"en-US": [{}]}, "automatic_captions": {"en": [{}]}},
        "bbbbbbbbbbb": {"title": "Auto only", "subtitles": {}, "automatic_captions": {"en": [{}], "en-orig": [{}]}},
        "ccccccccccc": {"title": "Nothing", "subtitles": {"ja": [{}]}, "automatic_captions": {}},
    }
    calls: ClassVar[list[dict]] = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.calls.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if "list=" in url:
            return {"title": "My list", "entries": [
                {"id": "aaaaaaaaaaa", "title": "One", "channel": "Ch", "duration": 61},
                None,
                {"id": "bbbbbbbbbbb", "title": "Two", "uploader": "Up"}]}
        vid = youtube.video_id(url)
        if vid not in self.videos:
            raise RuntimeError("Video unavailable\nmore detail")
        return self.videos[vid]

    def download(self, urls):
        lang = self.opts["subtitleslangs"][0]
        Path(self.opts["outtmpl"].replace("%(ext)s", f"{lang}.vtt")).write_text(VTT, encoding="utf-8")


@pytest.mark.parametrize("s, vid", [
    ("https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLx", "aaaaaaaaaaa"),
    ("https://youtu.be/b-b_bbbbbbb?t=3", "b-b_bbbbbbb"),
    ("https://www.youtube.com/shorts/ccccccccccc", "ccccccccccc"),
    ("ddddddddddd", "ddddddddddd"),
    ("not a video", None),
])
def test_video_id(s, vid):
    assert youtube.video_id(s) == vid


def test_pick_lang():
    assert youtube.pick_lang({"en": 1, "en-US": 1}, "en") == "en"
    assert youtube.pick_lang({"en-orig": 1, "en-GB": 1}, "en") == "en-GB"
    assert youtube.pick_lang({"ja": 1}, "en") is None


def test_playlist_to_list_and_back(tmp_path):
    title, entries = youtube.playlist_entries("https://www.youtube.com/playlist?list=PLx", ydl_factory=FakeYDL)
    assert title == "My list"
    assert [e["id"] for e in entries] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert entries[1]["channel"] == "Up"
    lst = tmp_path / "list.tsv"
    youtube.write_list(lst, entries)
    urls = tmp_path / "urls.txt"
    urls.write_text("https://youtu.be/ccccccccccc\n\nhttps://www.youtube.com/watch?v=aaaaaaaaaaa\n", encoding="utf-8")
    targets = youtube.read_targets([str(lst), str(urls), "ddddddddddd"])
    assert targets == [("aaaaaaaaaaa", "One"), ("bbbbbbbbbbb", "Two"), ("ccccccccccc", ""), ("ddddddddddd", "")]
    with pytest.raises(ValueError):
        youtube.read_targets(["nope"])


def test_download_subtitles(tmp_path):
    targets = [("aaaaaaaaaaa", ""), ("bbbbbbbbbbb", "Two"), ("ccccccccccc", ""), ("ddddddddddd", "")]
    res = youtube.download_subtitles(targets, tmp_path, pause=0, ydl_factory=FakeYDL)
    assert [r.status for r in res] == ["subtitles", "auto-available", "none", "error"]
    assert res[0].title == "With subtitles" and res[3].detail == "Video unavailable"
    assert (tmp_path / "aaaaaaaaaaa.vtt").read_text(encoding="utf-8") == VTT
    assert not list(tmp_path.glob("*.*.vtt"))          # renamed to <id>.vtt

    again = youtube.download_subtitles(targets, tmp_path, auto=True, pause=0, ydl_factory=FakeYDL)
    assert [r.status for r in again] == ["cached", "auto", "none", "error"]
    assert FakeYDL.calls[-1]["writeautomaticsub"] and FakeYDL.calls[-1]["subtitleslangs"] == ["en"]
    youtube.write_report(tmp_path / "report.tsv", again)
    assert (tmp_path / "report.tsv").read_text(encoding="utf-8").startswith("id\ttitle\tstatus\tdetail\n")
