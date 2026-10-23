from vocab_miner.links import add_links, read_links


def test_table_links_win_over_search_links(tmp_path):
    (tmp_path / "links.tsv").write_text("title\tStream\tShop\nMorning Rain\thttps://s.example/t/1\t\n"
                                        "ARTIST / Night Bus (English Version)\t\thttps://shop.example/2\n",
                                        encoding="utf-8")
    table = read_links(tmp_path / "links.tsv")
    docs = [{"id": "a", "title": "Morning Rain"}, {"id": "b", "title": "Night Bus"}, {"id": "c", "title": "朝の雨"}]
    n = add_links(docs, table, {"Stream": "https://s.example/search/{artist}%20{title}"}, artist="Some Band")
    assert n == 2
    assert docs[0]["links"] == [{"label": "Stream", "url": "https://s.example/t/1"}]
    assert docs[1]["links"] == [{"label": "Shop", "url": "https://shop.example/2"},
                                {"label": "Stream", "url": "https://s.example/search/Some%20Band%20Night%20Bus"}]
    assert docs[2]["links"][0]["url"] == "https://s.example/search/Some%20Band%20%E6%9C%9D%E3%81%AE%E9%9B%A8"


def test_no_links_configured():
    docs = [{"id": "a", "title": "Morning Rain"}]
    assert add_links(docs) == 0 and "links" not in docs[0]
