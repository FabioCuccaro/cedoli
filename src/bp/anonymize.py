"""Struttura anonima di un cedolino: la forma del PDF senza i dati della persona.

Serve a far supportare un formato nuovo senza condividere il cedolino. Restano posizioni, font,
intestazioni, codici delle voci e le parole comuni delle buste paga (knowledge/vocabolario.txt);
ogni cifra diventa 9 e ogni altra parola diventa X (nomi, indirizzi, aziende, IBAN, codice fiscale).
"""

import re
from functools import cache
from importlib.resources import files

from bp import __version__
from bp.extract import Document

FORMAT = "busta-chiara-struttura-anonima"
# Metadati che dicono quale gestionale ha prodotto il PDF: utili per riconoscerlo, senza dati personali.
KEEP_METADATA = ("Producer", "Creator")
KEEP_KEYWORDS = re.compile(r"_MODEL$")


@cache
def vocabulary() -> frozenset[str]:
    text = files("bp.knowledge").joinpath("vocabolario.txt").read_text(encoding="utf-8")
    return frozenset(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#"))


# Codici delle voci (Z00087, AA245, WFB01, R4100): poche lettere e poi cifre. Codice fiscale, IBAN e
# targhe (AB123CD) hanno un'altra forma, quindi vengono mascherati come tutto il resto.
CODE = re.compile(r"[A-Za-z]{1,3}\d{1,6}[A-Za-z]?")


def mask(text: str) -> str:
    """Cifre → 9; parole fuori dal vocabolario → X della stessa lunghezza (le maiuscole restano maiuscole).

    Le lettere dei codici delle voci restano: dicono di che voce si tratta, non di chi è il cedolino.
    """
    def word(m: re.Match) -> str:
        w = m.group()
        return w if w.upper() in vocabulary() else "".join("X" if c.isupper() else "x" for c in w)

    def token(t: str) -> str:
        if CODE.fullmatch(t):
            return re.sub(r"\d", "9", t)
        return re.sub(r"[^\W\d_]+", word, re.sub(r"\d", "9", t))

    return re.sub(r"\S+", lambda m: token(m.group()), text)


def _keywords(raw: str) -> str:
    parts = []
    for part in raw.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            parts.append(f"{key}={value if KEEP_KEYWORDS.search(key.strip()) else mask(value)}")
    return ";".join(parts)


def anonymize(doc: Document) -> dict:
    meta = {}
    for k, v in doc.metadata.items():
        meta[k] = v if k in KEEP_METADATA else _keywords(v) if k == "Keywords" else mask(v)
    return {
        "formato": FORMAT,
        "versione_app": __version__,
        "metadati": meta,
        "pagine": [
            [{"top": round(r.top, 1), "testo": mask(r.text),
              "parole": [[mask(w.text), round(w.x0, 1), round(w.x1, 1), w.font.split("+")[-1]] for w in r.words]}
             for r in page]
            for page in doc.pages
        ],
    }
