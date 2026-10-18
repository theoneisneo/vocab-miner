from vocab_miner.sources.subtitle import parse_lrc
from vocab_miner.transcribe import MARK_ALIGNED, MARK_TRANSCRIBED, Line, Word, align, to_lrc


def words(spec: str, start: float = 0.0, step: float = 0.5) -> list[Word]:
    """'a b c' -> words half a second apart."""
    return [Word(w, start + i * step, start + i * step + 0.4) for i, w in enumerate(spec.split())]


def test_align_uses_heard_timing_and_keeps_given_text():
    heard = words("the quick brawn fox jumps") + words("over the lazy dog", start=10)
    lines = align(["The quick brown fox jumps,", "", "Over the lazy dog!"], heard)
    assert [ln.text for ln in lines] == ["The quick brown fox jumps,", "Over the lazy dog!"]
    assert lines[0].start == 0.0 and abs(lines[0].end - 2.4) < 1e-9
    assert lines[1].start == 10.0 and abs(lines[1].end - 11.9) < 1e-9


def test_align_spreads_unheard_lines_between_neighbours():
    heard = words("one two three") + words("seven eight nine", start=12)
    lines = align(["One two three", "four five", "six", "Seven eight nine"], heard)
    first, a, b, last = lines
    assert first.end <= a.start < a.end <= b.start < b.end <= last.start
    assert abs((a.end - a.start) - 2 * (b.end - b.start)) < 1e-9     # weighted by word count


def test_align_stays_in_order_with_repeated_lines():
    heard = words("la la la") + words("hello there", start=5) + words("la la la", start=9)
    lines = align(["La la la", "Hello there", "La la la"], heard)
    assert [round(ln.start) for ln in lines] == [0, 5, 9]


def test_align_japanese_character_by_character():
    # Whisper splits Japanese into pieces that do not follow the lyric lines; kana vs kanji may differ
    heard = [Word("きょうは", 1.0, 2.0), Word("雨が", 2.0, 3.0), Word("ふる", 3.0, 3.5),
             Word("あしたは", 8.0, 9.0), Word("晴れ", 9.0, 10.0)]
    lines = align(["今日は雨が降る", "明日は晴れ"], heard)
    assert (lines[0].start, lines[0].end) == (1.0, 3.5)       # matched on は・雨・が・る
    assert (lines[1].start, lines[1].end) == (8.0, 10.0)      # matched on は・晴・れ


def test_lrc_closes_lines_before_long_pauses_and_round_trips():
    lines = [Line("first", 1.0, 3.0), Line("second", 3.5, 5.0), Line("third", 20.0, 22.5)]
    text = to_lrc(lines, title="Demo")
    assert text.splitlines()[:2] == ["[ti:Demo]", MARK_ALIGNED]
    cues = [c for c in parse_lrc(text) if c.text]
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 3.5, "first"), (3.5, 5.0, "second"), (20.0, 22.5, "third")]
    assert MARK_TRANSCRIBED in to_lrc(lines, transcribed=True)
