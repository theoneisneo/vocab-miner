"""`vm apply-edits` for lines edited in the web app (beyond joining): whole songs written back."""
import json
from pathlib import Path

from vocab_miner.config import load_config
from vocab_miner.edits import apply_rewrites, read_line_edits, read_merges
from vocab_miner.sources.subtitle import SubtitleSource

LRC = "[ti:Morning Song]\n[re:LRCLIB 1]\n[00:01.00]朝の雨が降る\n[00:05.00]傘を持って行く\n[00:09.00]\n[00:12.00]空が晴れた\n"
SIDE = "[00:01.00]早上下雨\n[00:05.00]帶傘出門\n[00:12.00]天晴了\n"


def seg(text, ruby=None):
    return [[text, ruby, None, 0]]


def project(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "song.lrc").write_text(LRC, encoding="utf-8")
    (raw / "song.zh-Hant.lrc").write_text(SIDE, encoding="utf-8")
    (tmp_path / "config.local.toml").write_text(
        'data_dir = "."\n[[sources]]\nid = "songs/x"\nplugin = "vocab_miner.sources.subtitle:SubtitleSource"\n'
        'path = "raw"\nlang = "ja"\ntranslations = { "zh-Hant" = "file" }\n', encoding="utf-8")
    return raw


def export(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "export.json"
    p.write_text(json.dumps({"docs": [{"source": "songs/x", "doc": "song", "title": "Morning Song", "lines": lines}]},
                            ensure_ascii=False), encoding="utf-8")
    return p


def orig(n, start, text):
    return {"id": f"songs/x:song:{n}", "start": start, "text": text}


def edited_lines():
    """Line 1 split in two (with a new translation), line 2 kept, line 3 joined... and its time moved."""
    o1 = orig(1, 1.0, "朝の雨が降る")
    return [
        {"seg": seg("朝の雨が"), "start": 1.0, "end": 2.5, "tr": "早上的雨", "edited": True, "orig": [o1]},
        {"seg": seg("降る"), "start": 2.5, "end": 4.0, "tr": "下著", "edited": True, "orig": [o1]},
        {"id": "songs/x:song:2", "seg": seg("傘を持って行く"), "start": 5.0, "end": 9.0, "tr": "帶傘出門"},
        {"seg": seg("空が晴れた！"), "start": 12.2, "end": 15.0, "tr": "天晴了", "edited": True,
         "orig": [orig(3, 12.0, "空が晴れた")]},
    ]


def test_read_line_edits_and_merges_apart(tmp_path):
    p = export(tmp_path, edited_lines())
    [r] = read_line_edits(p)
    assert (r.source_id, r.doc_id, len(r.lines)) == ("songs/x", "song", 4)
    assert [c[1] for c in r.changes] == ["朝の雨が", "降る", "空が晴れた！  [start 0:12.00 -> 0:12.20]"]
    assert len(r.refs) == 3                                  # the split line's original is listed once
    assert read_merges(p, skip={("songs/x", "song")}) == []


def test_rewrite_lrc_and_translation_file(tmp_path):
    raw = project(tmp_path)
    cfg = load_config(tmp_path)
    changed = apply_rewrites(cfg, read_line_edits(export(tmp_path, edited_lines())), log=lambda m: None)
    assert changed == ["songs/x"]
    lrc = (raw / "song.lrc").read_text(encoding="utf-8")
    assert lrc.startswith("[ti:Morning Song]\n[re:LRCLIB 1]\n[00:01.00]朝の雨が\n[00:02.50]降る\n[00:04.00]\n")
    assert "[00:12.20]空が晴れた！" in lrc
    assert (raw / "song.lrc.bak").read_text(encoding="utf-8") == LRC
    side = (raw / "song.zh-Hant.lrc").read_text(encoding="utf-8")
    assert "[00:01.00]早上的雨" in side and "[00:02.50]下著" in side
    src = SubtitleSource("songs/x", raw, "ja", translations={"zh-Hant": "file"})
    us = list(src.utterances())
    assert [(u.text, u.translations.get("zh-Hant")) for u in us] == [
        ("朝の雨が", "早上的雨"), ("降る", "下著"), ("傘を持って行く", "帶傘出門"), ("空が晴れた！", "天晴了")]


def test_material_changed_since_the_export_is_skipped(tmp_path):
    raw = project(tmp_path)
    (raw / "song.lrc").write_text(LRC.replace("朝の雨が降る", "朝の雪が降る"), encoding="utf-8")
    logs = []
    changed = apply_rewrites(load_config(tmp_path), read_line_edits(export(tmp_path, edited_lines())), log=logs.append)
    assert changed == [] and any("material changed" in m for m in logs)
    assert "朝の雪が降る" in (raw / "song.lrc").read_text(encoding="utf-8")


def test_subtitles_become_an_lrc(tmp_path):
    raw = project(tmp_path)
    (raw / "song.lrc").unlink()
    (raw / "song.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n朝の雨が降る\n\n"
                                  "00:00:05.000 --> 00:00:09.000\n傘を持って行く\n\n"
                                  "00:00:12.000 --> 00:00:15.000\n空が晴れた\n", encoding="utf-8")
    apply_rewrites(load_config(tmp_path), read_line_edits(export(tmp_path, edited_lines())), log=lambda m: None)
    assert not (raw / "song.vtt").exists() and (raw / "song.vtt.bak").exists()
    assert "[00:02.50]降る" in (raw / "song.lrc").read_text(encoding="utf-8")


def test_retimed_line_shows_its_time(tmp_path):
    """A line only moved in time (對時) says how, since its text is the same before and after."""
    lines = [{"seg": seg("朝の雨が降る"), "start": 0.7, "end": 5.0, "tr": "早上下雨", "edited": True,
              "orig": [orig(1, 1.0, "朝の雨が降る")]}]
    [r] = read_line_edits(export(tmp_path, lines))
    assert r.changes == [(["朝の雨が降る"], "朝の雨が降る  [start 0:01.00 -> 0:00.70]")]
