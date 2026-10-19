import urllib.error

from vocab_miner import quality, songs
from vocab_miner.fetch import lrclib, youtube

EN = "The quick brown fox jumps over the lazy dog\nAnd runs into the morning light\n" * 3
ROMAJI = "Kimi no koe ga kikoeru\nBokura wa mada aruku\nSora ni te wo nobasu\n"
JA = "朝の光の中で\n君の声が聞こえる\n"


def synced(text: str, step: float = 4.0) -> str:
    return "\n".join(f"[{int(i * step) // 60:02d}:{int(i * step) % 60:02d}.00] {ln}"
                     for i, ln in enumerate(text.splitlines()))


def test_in_lang_and_artist():
    assert lrclib.in_lang(EN, "en") and not lrclib.in_lang(ROMAJI, "en") and not lrclib.in_lang(JA, "en")
    assert lrclib.in_lang(JA, "ja") and not lrclib.in_lang(EN, "ja")
    assert lrclib.artist_from_channel("Some Band - Topic") == "Some Band"
    assert lrclib.artist_from_channel("Some Band Official") == "Some Band"


def test_pick_prefers_language_and_matching_length():
    base = {"trackName": "Morning Fox", "artistName": "Some Band"}
    results = [
        {**base, "id": 1, "duration": 200, "syncedLyrics": synced(ROMAJI)},              # romanized: not English
        {**base, "id": 2, "duration": 200, "syncedLyrics": synced(JA)},                  # Japanese version
        {**base, "id": 3, "duration": 250, "syncedLyrics": synced(EN)},                  # wrong length
        {**base, "id": 4, "duration": 201, "syncedLyrics": synced(EN)},                  # this one
        {**base, "trackName": "Other Song", "id": 5, "duration": 200, "syncedLyrics": synced(EN)},
    ]
    best = lrclib.pick(results, "Morning Fox", "Some Band", 200, "en")
    assert best["id"] == 4 and best["_synced"]
    plain_only = [{**base, "id": 6, "duration": 300, "plainLyrics": EN}]
    best = lrclib.pick(plain_only, "Morning Fox", "Some Band", 200, "en")
    assert best["id"] == 6 and not best["_synced"]


def test_fetch_lyrics_writes_files_and_survives_server_errors(tmp_path):
    answers = {
        "Morning Fox": [{"id": 9, "trackName": "Morning Fox", "artistName": "Some Band", "duration": 180,
                         "syncedLyrics": synced(EN)}],
        "Plain Song": [{"id": 8, "trackName": "Plain Song", "artistName": "Some Band", "duration": 1,
                        "plainLyrics": EN}],
        "Nowhere": [],
    }

    def get(url):
        if "Broken" in url:
            raise urllib.error.URLError("down")
        return next((v for k, v in answers.items() if k.replace(" ", "+") in url), [])

    rows = [{"id": "aaaaaaaaaaa", "title": "Some Band / Morning Fox (Official Music Video)", "channel": "Some Band - Topic",
             "duration": "180"},
            {"id": "bbbbbbbbbbb", "title": "Plain Song", "channel": "Some Band", "duration": "200"},
            {"id": "ccccccccccc", "title": "Nowhere", "channel": "Some Band", "duration": ""},
            {"id": "ddddddddddd", "title": "Broken", "channel": "Some Band", "duration": ""}]
    res = lrclib.fetch_lyrics(rows, tmp_path, "en", get=get, pause=0)
    assert [r.status for r in res] == ["synced", "plain", "missing", "error"]
    lrc = (tmp_path / "aaaaaaaaaaa.lrc").read_text(encoding="utf-8")
    assert lrc.startswith("[ti:Morning Fox]\n[ar:Some Band]\n[re:LRCLIB 9]")
    assert (tmp_path / "bbbbbbbbbbb.txt").is_file()
    assert lrclib.fetch_lyrics(rows[:2], tmp_path, "en", get=get, pause=0) == []        # already there


def test_quality_grades(tmp_path):
    (tmp_path / "good.lrc").write_text("[ti:Good]\n[re:LRCLIB 1]\n" + synced(EN, 30), encoding="utf-8")
    (tmp_path / "heard.lrc").write_text(
        "[re:vocab-miner: Whisper transcription, may contain mistakes]\n" + synced(EN + "Thanks for watching!\n", 30),
        encoding="utf-8")
    (tmp_path / "other.lrc").write_text(synced(JA * 3, 30), encoding="utf-8")
    (tmp_path / "long.lrc").write_text(synced(EN, 50), encoding="utf-8")
    (tmp_path / "tiny.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello there\n", encoding="utf-8")
    (tmp_path / "good.zh-Hant.lrc").write_text("[00:01.00] 翻譯\n", encoding="utf-8")     # a translation: skipped
    lst = tmp_path / "videos.tsv"
    youtube.write_list(lst, [{"id": i, "title": i.title(), "channel": "", "duration": 200}
                             for i in ("good", "heard", "other", "long", "tiny")])
    reps = {r.id: r for r in quality.check_folder(tmp_path, "en", [lst])}
    assert set(reps) == {"good", "heard", "other", "long", "tiny"}
    assert reps["good"].grade == "ok" and reps["good"].origin == "LRCLIB"
    assert reps["heard"].grade == "check" and any("sign-off" in n for n in reps["heard"].notes)
    assert reps["other"].grade == "problem" and any("not in en" in n for n in reps["other"].notes)
    assert reps["long"].grade == "problem" and any("after the video ends" in n for n in reps["long"].notes)
    assert reps["tiny"].grade == "problem" and reps["tiny"].origin == "subtitles"
    quality.write_report(tmp_path / "quality.tsv", list(reps.values()))
    assert (tmp_path / "quality.tsv").read_text(encoding="utf-8").splitlines()[1].startswith("problem")


def test_collect_skips_non_songs_and_duplicates(tmp_path):
    pl = tmp_path / "playlists.txt"
    pl.write_text("en | EP | https://www.youtube.com/playlist?list=PLa\n"
                  "en | -  | https://www.youtube.com/playlist?list=PLb\n"
                  "ja | EP | https://www.youtube.com/playlist?list=PLc\n", encoding="utf-8")
    playlists = youtube.read_playlists(pl)
    youtube.write_list(tmp_path / "PLa.tsv", [
        {"id": "v1", "title": "Some Band / Morning Fox (Official Music Video)", "channel": "", "duration": ""},
        {"id": "v2", "title": "Prologue", "channel": "", "duration": ""},
        {"id": "v3", "title": "EP Cross Fade Movie", "channel": "", "duration": ""}])
    youtube.write_list(tmp_path / "PLb.tsv", [
        {"id": "t1", "title": "Morning Fox", "channel": "", "duration": ""},          # same song, other upload
        {"id": "t2", "title": "Night Bus", "channel": "", "duration": ""}])
    rows = songs.collect(playlists, "en", tmp_path, log=lambda m: None)
    assert [(r["id"], r["title"]) for r in rows] == [("v1", "Morning Fox"), ("t2", "Night Bus")]


def test_read_skip(tmp_path):
    (tmp_path / "skip.txt").write_text("# comment\nv1   # other language\nNight Bus\n\n", encoding="utf-8")
    skip = songs.read_skip(tmp_path / "skip.txt")
    assert "v1" in skip and "nightbus" in skip and songs.read_skip(tmp_path / "none.txt") == set()
