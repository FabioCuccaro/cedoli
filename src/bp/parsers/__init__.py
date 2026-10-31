"""Registro dei parser: uno per ogni layout di cedolino supportato."""

from types import ModuleType

from bp import partial
from bp.extract import Document, ReadError
from bp.parsers import hr1luldip, paylul01

PARSERS: list[ModuleType] = [paylul01, hr1luldip]


# Parole presenti in qualsiasi busta paga italiana, qualunque sia il gestionale che la stampa.
PAYSLIP_WORDS = ("NETTO", "COMPETENZE", "TRATTENUTE", "IRPEF", "INPS", "IMPONIBILE", "RETRIBUZIONE", "CEDOLINO")


class UnsupportedLayout(ReadError):
    pass


def looks_like_payslip(doc: Document) -> bool:
    text = " ".join(r.text for page in doc.pages for r in page).upper()
    return sum(w in text for w in PAYSLIP_WORDS) >= 3


def find_parser(doc: Document) -> ModuleType:
    for parser in PARSERS:
        if parser.detect(doc):
            return parser
    if looks_like_payslip(doc):
        raise UnsupportedLayout(
            "sembra una busta paga, ma di un formato che Busta chiara non sa ancora leggere "
            f"(formati supportati: {', '.join(p.NAME for p in PARSERS)}){partial.note(doc)}",
            new_format=True,
        )
    raise UnsupportedLayout("non sembra una busta paga")
