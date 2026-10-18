"""English tokenizer: spaCy (en_core_web_sm). Install with  uv sync --extra en.

spaCy already gives Universal POS tags and lemmas (sang -> sing, 'm -> be, n't -> not); Token.pos_native is the
Penn Treebank tag. Lemmas are lowercased except proper nouns and "I". Sung syllables (la-la-la, oh, na na)
become INTJ so they can be left out of the vocabulary.
"""
from __future__ import annotations

import re

from ..model import Token

WORD = re.compile(r"[A-Za-z]")
VOCABLE = re.compile(r"^(?:la|na|pa|ra|da|du|doo|oh|ooh|ah|aah|uh|woah|whoa|wo|yeah|hey|mm|hmm|ha|ya|yo)+$", re.IGNORECASE)

POS_LABELS_ZH = {
    "NOUN": "名詞", "PROPN": "專有名詞", "VERB": "動詞", "ADJ": "形容詞", "ADV": "副詞", "PRON": "代名詞",
    "DET": "限定詞", "ADP": "介系詞", "AUX": "助動詞", "CCONJ": "連接詞", "SCONJ": "從屬連接詞",
    "PART": "小品詞", "INTJ": "感嘆詞", "NUM": "數詞", "SYM": "符號", "PUNCT": "標點", "X": "其他",
}


class EnglishTokenizer:
    lang = "en"
    version = "1"
    word_pattern = WORD

    def __init__(self, model: str = "en_core_web_sm"):
        try:
            import spacy
        except ImportError as e:
            raise ImportError("English needs spaCy: uv sync --extra en") from e
        self.nlp = spacy.load(model, disable=["ner", "parser"])

    def tokenize(self, text: str) -> list[Token]:
        out: list[Token] = []
        for t in self.nlp(text):
            if t.is_space:
                continue
            pos = "INTJ" if VOCABLE.match(t.text) else t.pos_
            proper = pos == "PROPN"
            lemma = t.lemma_ or t.text
            if not proper and lemma != "I":
                lemma = lemma.lower()
            out.append(Token(surface=t.text, lemma=lemma, reading=None, pos=pos, pos_native=t.tag_,
                             start=t.idx, end=t.idx + len(t.text), is_proper=proper, base=lemma))
        return out

    @staticmethod
    def pos_label(token_or_pos: Token | str) -> str:
        """Learner-facing POS name (Traditional Chinese). collect() passes Token.pos_native (a PTB tag)."""
        tag = token_or_pos if isinstance(token_or_pos, str) else token_or_pos.pos
        return POS_LABELS_ZH.get(tag) or POS_LABELS_ZH.get(PTB_TO_UPOS.get(tag, ""), tag)


# Penn Treebank tag -> UPOS, for labelling from pos_native
PTB_TO_UPOS = {
    "NN": "NOUN", "NNS": "NOUN", "NNP": "PROPN", "NNPS": "PROPN", "VB": "VERB", "VBD": "VERB", "VBG": "VERB",
    "VBN": "VERB", "VBP": "VERB", "VBZ": "VERB", "MD": "AUX", "JJ": "ADJ", "JJR": "ADJ", "JJS": "ADJ",
    "RB": "ADV", "RBR": "ADV", "RBS": "ADV", "WRB": "ADV", "PRP": "PRON", "PRP$": "PRON", "WP": "PRON",
    "WP$": "PRON", "EX": "PRON", "DT": "DET", "PDT": "DET", "WDT": "DET", "IN": "ADP", "TO": "PART",
    "RP": "ADP", "CC": "CCONJ", "UH": "INTJ", "CD": "NUM", "POS": "PART",
}
