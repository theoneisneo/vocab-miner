from vocab_miner.transcribe import Word
from vocab_miner.wordtimes import add_piece_times, read_words, write_words


def test_pieces_get_the_time_they_were_heard():
    lines = [
        {"start": 1.0, "end": 4.0, "seg": [["朝", "あさ", 0, 0], ["の", None, 1, 1], ["雨", "あめ", 2, 2]]},
        {"start": 5.0, "end": 8.0, "seg": [["傘", "かさ", 3, 0], ["を", None, 4, 1], ["持つ", None, 5, 2]]},
    ]
    words = [("朝", 1.1, 1.4), ("の", 1.4, 1.6), ("雨", 2.2, 2.9),          # line 1, every piece heard
             ("傘", 5.1, 5.5), ("お", 5.5, 5.8), ("持", 6.4, 6.8), ("つ", 6.8, 7.0)]  # line 2: を misheard
    assert add_piece_times(lines, words) == 5
    assert [p[4] for p in lines[0]["seg"]] == [1.1, 1.4, 2.2]
    assert [p[4] if len(p) > 4 else None for p in lines[1]["seg"]] == [5.1, None, 6.4]


def test_words_round_trip(tmp_path):
    path = tmp_path / ".words" / "vid.words.json"
    write_words(path, [Word("朝", 1.234, 1.5), Word("雨", 2.0, 2.5)])
    assert read_words(path) == [("朝", 1.23, 1.5), ("雨", 2.0, 2.5)]
