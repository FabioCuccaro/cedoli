"""Estrazione di parole con coordinate e metadati da un PDF, senza interpretarle."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

# Parole la cui distanza verticale è entro questa soglia (in punti) stanno sulla stessa riga.
ROW_TOLERANCE = 2.0
# Soglia più stretta per comporre le parole: righe vicine con colonne sovrapposte
# (es. intestazione "GG INPS" e valori sotto) altrimenti mescolano i caratteri.
WORD_Y_TOLERANCE = 1.5


class ReadError(ValueError):
    """Un cedolino che non si riesce a leggere, con un messaggio comprensibile da chi usa l'app.

    `new_format`: il PDF sembra una busta paga che Busta chiara non sa ancora leggere, quindi ha senso
    proporre di salvarne la struttura anonima.
    """

    def __init__(self, message: str, new_format: bool = False):
        super().__init__(message)
        self.new_format = new_format


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    page: int
    font: str = ""  # alcuni layout stampano il modulo e i dati con font diversi

    def overlap(self, x0: float, x1: float) -> float:
        return max(0.0, min(self.x1, x1) - max(self.x0, x0))


@dataclass
class Row:
    words: list[Word]

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def page(self) -> int:
        return self.words[0].page

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Document:
    path: Path
    sha256: str
    metadata: dict[str, str]
    keywords: dict[str, str]
    pages: list[list[Row]]


def group_rows(words: list[Word]) -> list[Row]:
    rows: list[Row] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and w.top - rows[-1].top <= ROW_TOLERANCE:
            rows[-1].words.append(w)
        else:
            rows.append(Row([w]))
    for r in rows:
        r.words.sort(key=lambda w: w.x0)
    return rows


def parse_keywords(raw: str) -> dict[str, str]:
    """I metadati Keywords hanno la forma `CHIAVE=valore;CHIAVE=valore;...`."""
    out: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load(path: str | Path) -> Document:
    path = Path(path)
    data = path.read_bytes()
    try:
        with pdfplumber.open(path) as pdf:
            meta = {k: str(v) for k, v in (pdf.metadata or {}).items()}
            pages = []
            for n, page in enumerate(pdf.pages):
                words = [
                    Word(w["text"], w["x0"], w["x1"], w["top"], n, w["fontname"])
                    for w in page.extract_words(y_tolerance=WORD_Y_TOLERANCE, extra_attrs=["fontname"])
                ]
                pages.append(group_rows(words))
    except PdfminerException as e:
        if e.args and isinstance(e.args[0], (PDFPasswordIncorrect, PDFEncryptionError)):
            raise ReadError("il PDF è protetto da password: aprilo, salvalo senza password e caricalo di nuovo") from e
        raise ReadError("il PDF è rovinato o incompleto: prova a scaricarlo di nuovo") from e
    except Exception as e:  # pdfminer non solleva solo le sue eccezioni su file malformati
        raise ReadError("il PDF è rovinato o incompleto: prova a scaricarlo di nuovo") from e
    if not any(pages):
        raise ReadError("il PDF non contiene testo, forse è una scansione o una foto: "
                        "serve il PDF originale scaricato dal portale delle buste paga")
    return Document(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        metadata=meta,
        keywords=parse_keywords(meta.get("Keywords", "")),
        pages=pages,
    )
