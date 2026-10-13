from vocab_miner.model import MediaRef, Utterance, read_jsonl, write_jsonl


def test_jsonl_roundtrip(tmp_path):
    u = Utterance(
        id="demo:1", source_id="demo", doc_id="d1", seq=1, lang="ja",
        text="雨が降っている。", translations={"zh-Hant": "正在下雨。"},
        media=MediaRef(kind="youtube", uri="VIDEO_ID", start=12.5, end=15.0), tags=["ch01"],
    )
    path = tmp_path / "c.jsonl"
    assert write_jsonl(path, [u]) == 1
    (back,) = list(read_jsonl(path))
    assert back == u


def test_fixture_is_readable():
    from pathlib import Path
    lines = Path(__file__).parent.joinpath("fixtures/ja_sample.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 5
