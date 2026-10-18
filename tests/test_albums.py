from vocab_miner.albums import build_albums, title_key
from vocab_miner.fetch.youtube import list_file, read_playlists, write_list


def test_title_key_removes_decorations():
    assert title_key("Morning Rain") == "morningrain"
    assert title_key("ARTIST / Morning Rain (「朝の雨」English Ver.)") == "morningrain"
    assert title_key("ARTIST  - Morning Rain (朝の雨English Version) Lyrics Video") == "morningrain"
    assert title_key("ARTIST feat. Friends - Morning Rain (English Version) Lyrics Video") == "morningrain"
    assert title_key("ARTIST「朝の雨」 Official Music Video") == "朝の雨"
    assert title_key("朝の雨 (feat. 友達)") == "朝の雨"
    assert title_key("Two-Step") == "twostep"                       # a hyphen inside a title stays a title
    assert title_key("アサ", {"アサ": "Asa"}) == "asa"


def test_build_albums(tmp_path):
    pl = tmp_path / "playlists.txt"
    pl.write_text(
        "# comment\n"
        "en | First EP  | https://www.youtube.com/playlist?list=PLaaa\n"
        "en | -         | https://www.youtube.com/playlist?list=PLsrc\n"
        "en | Second EP | https://www.youtube.com/playlist?list=PLbbb\n"
        "ja | 一枚目     | https://www.youtube.com/playlist?list=PLccc\n", encoding="utf-8")
    playlists = read_playlists(pl)
    assert [p.album for p in playlists] == ["First EP", "", "Second EP", "一枚目"]
    lists = {"PLaaa": [("v1", "ARTIST / Morning Rain (English Version)"), ("x9", "Prologue")],
             "PLsrc": [("v1", "Morning Rain"), ("v2", "Night Bus"), ("v3", "Old Song")],
             "PLbbb": [("y2", "Night Bus"), ("y1", "Morning Rain")]}
    for p in playlists:
        if p.list_id in lists:
            write_list(list_file(tmp_path, p),
                       [{"id": i, "title": t, "channel": "", "duration": ""} for i, t in lists[p.list_id]])
    docs = [{"id": "s/v1", "title": "Morning Rain", "media": {"kind": "youtube", "uri": "v1"}},
            {"id": "s/v2", "title": "Night Bus", "media": {"kind": "youtube", "uri": "v2"}},
            {"id": "s/v3", "title": "Old Song", "media": None}]
    albums = build_albums(playlists, "en", tmp_path, docs)
    assert albums == [{"id": "first-ep", "title": "First EP", "docs": ["s/v1"]},       # matched by video id
                      {"id": "second-ep", "title": "Second EP", "docs": ["s/v2"]}]     # by title; v1 only once
    assert build_albums(playlists, "ja", tmp_path, docs) == []                         # list file missing
