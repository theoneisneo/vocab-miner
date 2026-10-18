"""Albums for the web data: which docs belong to which album, from a playlists file (see fetch.youtube).

Each album is a YouTube playlist whose video list was saved by `vm yt-playlists`. A doc belongs to an album when
its video is in the playlist, or when its title matches a playlist entry's title once the usual decorations are
removed ("ARTIST / ", "(English Version)", "Official Music Video", "(feat. ...)"). A doc is listed only under
the first album (in file order) that has it; docs in no album are left for the app to show as "other".
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from .fetch.youtube import Playlist, list_file, read_list

DECORATIONS = [
    re.compile(r"\([^)]*(?:english|\beng\b)[^)]*\)", re.IGNORECASE),      # (「朝の雨」English Ver.) (朝の雨 English Version)
    re.compile(r"\b(?:official\s+)?(?:music|lyrics?)\s+video\b|\bofficial\s+video\b", re.IGNORECASE),
    re.compile(r"\((?:feat|ft)\.[^)]*\)", re.IGNORECASE),
    re.compile(r"^\s*[^/「]{1,40}?\s+[-/]\s+"),                      # "ARTIST / Title", "ARTIST feat. X - Title"
]
BRACKETED = re.compile(r"「([^」]+)」")                              # ARTIST「朝の雨」 Official Music Video


def title_key(title: str, aliases: Mapping[str, str] | None = None) -> str:
    t = title
    for rx in DECORATIONS:
        t = rx.sub(" ", t)
    m = BRACKETED.search(t)
    if m:
        t = m.group(1)
    key = re.sub(r"\W+", "", t).casefold()
    if aliases:
        key = {title_key(k): title_key(v) for k, v in aliases.items()}.get(key, key)
    return key


def build_albums(playlists: Sequence[Playlist], lang: str, list_dir: Path, docs: Sequence[dict],
                 aliases: Mapping[str, str] | None = None) -> list[dict]:
    """[{id, title, docs: [doc id, ...]}] in playlist order. `docs` are web-data docs (id, title, media)."""
    by_video = {d["media"]["uri"]: d["id"] for d in docs if d.get("media") and d["media"].get("kind") == "youtube"}
    by_title: dict[str, str] = {}
    for d in docs:
        by_title.setdefault(title_key(d["title"], aliases), d["id"])
    placed: set[str] = set()
    albums: list[dict] = []
    for pl in playlists:
        if pl.lang.split("-")[0] != lang.split("-")[0] or not pl.album:
            continue
        path = list_file(list_dir, pl)
        if not path.is_file():
            continue
        members = []
        for row in read_list(path):
            doc = by_video.get(row["id"]) or by_title.get(title_key(row["title"], aliases))
            if doc and doc not in placed:
                placed.add(doc)
                members.append(doc)
        album = next((a for a in albums if a["title"] == pl.album), None)
        if album is None:
            albums.append({"id": re.sub(r"\W+", "-", pl.album.casefold()).strip("-") or pl.list_id,
                           "title": pl.album, "docs": members})
        else:
            album["docs"] += members                     # one album split over several playlists
    return albums
