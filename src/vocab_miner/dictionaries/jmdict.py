"""JMdict (EDRDG, CC BY-SA 4.0) English glosses for Japanese.

The dictionary file is not shipped. Download it once:
    uv run vm setup-dict        (fetches JMdict_e.gz into .cache/dict/)
On first use it is converted into .cache/dict/jmdict.sqlite.
"""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path

JMDICT_URL = "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"
DEFAULT_GZ = Path(".cache/dict/JMdict_e.gz")
DB_VERSION = "1"
KANA_ONLY = re.compile(r"[ぁ-ゖァ-ヺー]+")

# UPOS -> words that appear in JMdict's expanded part-of-speech descriptions
POS_HINTS = {
    "NOUN": ("noun",), "PROPN": ("noun",), "PRON": ("pronoun",), "VERB": ("verb",), "AUX": ("auxiliary",),
    "ADJ": ("adjective", "adjectival"), "ADV": ("adverb",), "ADP": ("particle",), "PART": ("particle",),
    "SCONJ": ("particle", "conjunction"), "CCONJ": ("conjunction",), "INTJ": ("interjection",),
    "DET": ("pre-noun", "adnominal"), "NUM": ("numeric",),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS entries (seq INTEGER PRIMARY KEY, common INTEGER, kanji TEXT, readings TEXT,
                                    senses TEXT);
CREATE TABLE IF NOT EXISTS forms (form TEXT, kind TEXT, seq INTEGER);
"""


def _texts(el: ET.Element, tag: str) -> list[str]:
    return [e.text or "" for e in el.findall(tag)]


def build_db(gz_path: Path, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    rows, forms = [], []
    with gzip.open(gz_path, "rb") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag != "entry":
                continue
            seq = int(el.findtext("ent_seq"))
            kanji = _texts(el, "k_ele/keb")
            readings = [{"r": r.findtext("reb"), "restr": _texts(r, "re_restr"), "nokanji": r.find("re_nokanji") is not None}
                        for r in el.findall("r_ele")]
            common = int(el.find("k_ele/ke_pri") is not None or el.find("r_ele/re_pri") is not None)
            senses, last_pos = [], []
            for s in el.findall("sense"):
                pos = _texts(s, "pos") or last_pos      # pos carries over to following senses
                last_pos = pos
                senses.append({"pos": pos, "misc": _texts(s, "misc"), "gloss": _texts(s, "gloss"),
                               "stagk": _texts(s, "stagk"), "stagr": _texts(s, "stagr")})
            rows.append((seq, common, json.dumps(kanji, ensure_ascii=False),
                         json.dumps(readings, ensure_ascii=False), json.dumps(senses, ensure_ascii=False)))
            forms += [(k, "k", seq) for k in kanji] + [(r["r"], "r", seq) for r in readings]
            el.clear()
            if len(rows) >= 5000:
                db.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?)", rows)
                db.executemany("INSERT INTO forms VALUES (?, ?, ?)", forms)
                rows, forms = [], []
    db.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?)", rows)
    db.executemany("INSERT INTO forms VALUES (?, ?, ?)", forms)
    db.execute("CREATE INDEX forms_form ON forms(form)")
    st = gz_path.stat()
    db.executemany("INSERT INTO meta VALUES (?, ?)",
                   [("version", DB_VERSION), ("source", f"{st.st_size}:{int(st.st_mtime)}")])
    db.commit()
    db.close()
    tmp.replace(db_path)


def _kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


class JMdictDictionary:
    """Dictionary plugin. Options: path (JMdict_e.gz), max_senses, max_glosses."""

    lang = "ja"

    def __init__(self, path: str | Path = DEFAULT_GZ, max_senses: int = 2, max_glosses: int = 3):
        self.gz_path = Path(path)
        self.db_path = self.gz_path.with_name("jmdict.sqlite")
        self.max_senses = max_senses
        self.max_glosses = max_glosses
        self._db: sqlite3.Connection | None = None

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            if not self.gz_path.is_file():
                raise FileNotFoundError(f"{self.gz_path} missing; run `uv run vm setup-dict`")
            if not self._db_current():
                print(f"building {self.db_path} from {self.gz_path} (one time, ~1 min) ...")
                build_db(self.gz_path, self.db_path)
            self._db = sqlite3.connect(self.db_path)
        return self._db

    def _db_current(self) -> bool:
        if not self.db_path.is_file():
            return False
        st = self.gz_path.stat()
        try:
            with sqlite3.connect(self.db_path) as db:
                meta = dict(db.execute("SELECT key, value FROM meta"))
        except sqlite3.Error:
            return False
        return meta.get("version") == DB_VERSION and meta.get("source") == f"{st.st_size}:{int(st.st_mtime)}"

    def _candidates(self, forms: list[str]) -> list[tuple]:
        forms = [f for f in dict.fromkeys(forms) if f]
        if not forms:
            return []
        q = ",".join("?" * len(forms))
        return self.db.execute(
            f"SELECT DISTINCT e.seq, e.common, e.kanji, e.readings, e.senses FROM forms f "
            f"JOIN entries e ON e.seq = f.seq WHERE f.form IN ({q})", forms).fetchall()

    def lookup(self, lemma: str, reading: str | None = None, pos: str | None = None,
               base: str | None = None) -> Mapping[str, str]:
        reading = _kata_to_hira(reading) if reading else None
        written = [w for w in (base, lemma) if w]
        best, best_score = None, -1.0
        for seq, common, kanji_j, readings_j, senses_j in self._candidates(written + ([reading] if reading else [])):
            kanji, readings = json.loads(kanji_j), json.loads(readings_j)
            rds = {_kata_to_hira(r["r"]) for r in readings}
            senses = json.loads(senses_j)
            kanji_hit = any(w in kanji for w in written)
            kana_written = any(KANA_ONLY.fullmatch(w) and _kata_to_hira(w) in rds for w in written)
            reading_hit = reading is not None and reading in rds
            if not (kanji_hit or kana_written):
                continue                       # matched by reading alone: homophone, not this word
            score = 4 * kanji_hit + 2 * reading_hit + 1.5 * common + 2 * kana_written * (not kanji or self._uk(senses))
            if pos and self._pos_match(senses, pos):
                score += 4                     # outweighs homophones that are usually written in kana
            score -= seq / 1e8                 # stable tie-break: older (lower seq) entries first
            if score > best_score:
                best, best_score = senses, score
        if best is None:
            return {}
        return {"en": self._format(best, pos)}

    @staticmethod
    def _uk(senses: list[dict]) -> bool:
        return any("usually written using kana alone" in m for s in senses for m in s["misc"])

    @staticmethod
    def _pos_match(senses: list[dict], upos: str) -> bool:
        hints = POS_HINTS.get(upos, ())
        return any(h in p.lower() for s in senses for p in s["pos"] for h in hints)

    def _format(self, senses: list[dict], upos: str | None) -> str:
        hints = POS_HINTS.get(upos or "", ())
        chosen = [s for s in senses if any(h in p.lower() for p in s["pos"] for h in hints)] or senses
        parts = ["; ".join(s["gloss"][: self.max_glosses]) for s in chosen[: self.max_senses] if s["gloss"]]
        return " / ".join(parts)


def download(dest: Path = DEFAULT_GZ, url: str = JMDICT_URL) -> Path:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    tmp.replace(dest)
    return dest
