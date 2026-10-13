"""Data file for the sing-along web app (web/): every line of every doc with ruby, romaji, translation and timing,
plus the vocabulary (content and grammar words) the lines link to.

The file contains your material, so it is written to out/ and never published with the app; the app imports it
from a local file and keeps it on the device.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from ..model import NO_STATS_TAG, Token, Utterance, VocabEntry
from ..render import segments

FORMAT_VERSION = 1


def _word(e: VocabEntry, grammar: bool) -> dict:
    return {
        "key": e.key, "lemma": e.lemma, "reading": e.reading or "", "romaji": e.romaji or "",
        "pos": e.pos_label or e.pos, "zh": e.gloss.get("zh-Hant", ""), "en": e.gloss.get("en", ""),
        "ff": e.false_friend or "", "rank": e.rank, "count": e.count, "docFreq": e.doc_freq,
        "grammar": grammar, "status": e.status,
    }


def build_web_data(entries: Sequence[VocabEntry], grammar: Sequence[VocabEntry], utterances: Sequence[Utterance],
                   tokens: Mapping[str, list[Token]], titles: Mapping[tuple[str, str], str], lang: str,
                   romanize_tokens: Callable[[Sequence[Token]], str] | None = None,
                   translation_lang: str = "zh-Hant") -> dict:
    words = [_word(e, False) for e in entries] + [_word(e, True) for e in grammar]
    index_of = {w["key"]: i for i, w in enumerate(words)}

    docs: dict[tuple[str, str], dict] = {}
    for u in utterances:
        k = (u.source_id, u.doc_id)
        doc = docs.get(k)
        if doc is None:
            doc = docs[k] = {"id": f"{u.source_id}/{u.doc_id}", "source": u.source_id, "doc": u.doc_id,
                             "title": titles.get(k, u.doc_id), "media": None, "noStats": False, "lines": []}
        if u.media is not None and doc["media"] is None:
            doc["media"] = {"kind": u.media.kind, "uri": u.media.uri}
        doc["noStats"] = doc["noStats"] or NO_STATS_TAG in u.tags
        toks = tokens.get(u.id, [])
        seg = [[s.text, s.ruby, index_of.get(toks[s.token].key) if s.token is not None else None]
               for s in segments(u.text, toks)] if toks else [[u.text, None, None]]
        doc["lines"].append({
            "id": u.id, "start": u.media.start if u.media else None, "end": u.media.end if u.media else None,
            "seg": seg, "romaji": romanize_tokens(toks) if romanize_tokens and toks else "",
            "tr": u.translations.get(translation_lang, ""),
        })
    return {
        "format": "vocab-miner-web", "version": FORMAT_VERSION, "lang": lang,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "words": words, "docs": list(docs.values()),
    }


def write_web_data(data: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
