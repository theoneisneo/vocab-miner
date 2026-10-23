"""Links from each song to other places (a streaming service, a lyrics page...), shown as buttons in the web app.

Two sources, combined per song:
  - a table you fill in: tab-separated, first column the song title, other columns named by the link label
        title       Spotify                              Apple Music
        Song A      https://open.spotify.com/track/...
  - search links made from a template for every song without one in the table:
        [web] search_links = { Spotify = "https://open.spotify.com/search/{artist} {title}" }
    ({title}, {artist}; both URL-encoded)
"""
from __future__ import annotations

import csv
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path

from .albums import title_key


def read_links(path: Path) -> dict[str, dict[str, str]]:
    """{title key: {label: url}} from the table."""
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines(), delimiter="\t"))
    if not rows:
        return {}
    labels = [h.strip() for h in rows[0][1:]]
    out: dict[str, dict[str, str]] = {}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        links = {lab: url.strip() for lab, url in zip(labels, r[1:], strict=False) if lab and url.strip()}
        if links:
            out[title_key(r[0])] = links
    return out


def add_links(docs: Sequence[dict], table: Mapping[str, Mapping[str, str]] | None = None,
              templates: Mapping[str, str] | None = None, artist: str = "",
              aliases: Mapping[str, str] | None = None) -> int:
    """Give docs a "links" list ([{label, url}]): table links first, then template links for the labels the
    table does not give. Returns how many docs got a link from the table."""
    from_table = 0
    for d in docs:
        given = dict((table or {}).get(title_key(d["title"], aliases), {}))
        from_table += bool(given)
        for label, tpl in (templates or {}).items():
            if label not in given:
                given[label] = tpl.format(title=urllib.parse.quote(d["title"]), artist=urllib.parse.quote(artist))
        if given:
            d["links"] = [{"label": k, "url": v} for k, v in given.items()]
    return from_table
