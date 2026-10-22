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


def clean_title(title: str) -> str:
    """The song title without the usual decorations: "ARTIST / Title (English Version) Official Music Video"."""
    t = title
    for rx in DECORATIONS:
        t = rx.sub(" ", t)
    m = BRACKETED.search(t)
    if m:
        t = m.group(1)
    t = re.sub(r"[(\[]\s*[)\]]", " ", t)          # brackets emptied by the removals above
    return re.sub(r"\s+", " ", t).strip()


def title_key(title: str, aliases: Mapping[str, str] | None = None) -> str:
    key = re.sub(r"\W+", "", clean_title(title)).casefold()
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


# ---------- versions of one song in several languages ----------

def read_versions(path: Path) -> list[dict[str, str]]:
    """A tab-separated table whose header is language codes (e.g. "ja  en"); each row is one song, giving its
    title in each language that has a version of it."""
    import csv
    rows = csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines(), delimiter="\t")
    return [{lang.strip(): (t or "").strip() for lang, t in r.items() if lang and (t or "").strip()} for r in rows]


def add_versions(docs: Sequence[dict], versions: Sequence[dict[str, str]], lang: str,
                 aliases: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Give each doc an "alt" list: the same song in the other languages ([{lang, title}]). Returns
    {doc id: row} for the docs that were found in the table."""
    base = lang.split("-")[0]
    by_key = {title_key(v[k], aliases): v for v in versions for k in v if k.split("-")[0] == base}
    found = {}
    for d in docs:
        row = by_key.get(title_key(d["title"], aliases))
        if row is None:
            continue
        found[d["id"]] = row
        alt = [{"lang": k, "title": t} for k, t in row.items() if k.split("-")[0] != base]
        if alt:
            d["alt"] = alt
    return found


def albums_in(docs: Sequence[dict], playlists: Sequence[Playlist], album_lang: str, lang: str, list_dir: Path,
              versions: Sequence[dict[str, str]], aliases: Mapping[str, str] | None = None) -> list[dict]:
    """Albums of another language's playlists (e.g. group English versions by the Japanese originals' albums),
    in that order. A doc joins the album of its version in `album_lang`; docs without one are left out."""
    rows = add_versions([dict(d) for d in docs], versions, lang, aliases)
    base = album_lang.split("-")[0]
    proxies = []
    for d in docs:
        row = rows.get(d["id"], {})
        title = next((t for k, t in row.items() if k.split("-")[0] == base), None)
        if title:
            proxies.append({"id": d["id"], "title": title, "media": None})
    return build_albums(playlists, album_lang, list_dir, proxies, aliases)
