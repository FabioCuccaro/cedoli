"""Lettura parziale di una busta paga di un formato non supportato.

Cerca solo le etichette che ogni cedolino stampa (totale competenze, totale trattenute, netto) e
l'importo accanto o subito sotto. Non legge le voci e non fa controlli: serve a dare almeno i numeri
principali, con l'avviso che vanno confrontati con il PDF.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from bp.extract import Document, Row, Word
from bp.money import is_amount, parse_amount

# Chiave → espressioni dell'etichetta, sul testo della riga in maiuscolo.
LABELS = {
    "competenze": re.compile(r"TOT(?:ALE|\.)?[\sS]*COMPETENZE"),
    "trattenute": re.compile(r"TOT(?:ALE|\.)?[\sS]*TRATTENUTE"),
    "netto": re.compile(r"NETTO(?:\s+(?:IN\s+BUSTA|DEL\s+MESE|A\s+PAGARE|DA\s+PAGARE|PAGATO))?"),
}
NAMES = {"competenze": "competenze", "trattenute": "trattenute", "netto": "netto"}


@dataclass
class Partial:
    values: dict[str, Decimal]

    @property
    def adds_up(self) -> bool | None:
        v = self.values
        if not all(k in v for k in LABELS):
            return None
        return v["competenze"] - v["trattenute"] == v["netto"]

    def summary(self) -> str:
        parts = [f"{NAMES[k]} {_euro(v)} €" for k, v in self.values.items()]
        check = {True: "i tre numeri tornano tra loro", False: "i tre numeri non tornano tra loro, controllali sul PDF",
                 None: "confrontali con il PDF"}[self.adds_up]
        return f"lettura parziale: {', '.join(parts)} ({check})"


def _euro(d: Decimal) -> str:
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _label_span(row: Row, rx: re.Pattern) -> tuple[float, float] | None:
    """Posizione orizzontale dell'etichetta nella riga, ricostruita dalle parole che la compongono."""
    text, starts = "", []
    for w in row.words:
        starts.append(len(text))
        text += w.text.upper() + " "
    m = rx.search(text)
    if not m:
        return None
    words = [w for w, s in zip(row.words, starts) if m.start() <= s < m.end()]
    return (words[0].x0, words[-1].x1) if words else None


def _clean(text: str) -> str:
    """Toglie il simbolo dell'euro attaccato all'importo (es. "1.788,19€")."""
    return text.replace("€", "").removesuffix("EUR").strip()


def _amounts(row: Row) -> list[tuple[Word, Decimal]]:
    return [(w, parse_amount(_clean(w.text))) for w in row.words if is_amount(_clean(w.text))]


def _amount_after(row: Row, x1: float) -> Decimal | None:
    for w, amount in _amounts(row):
        if w.x0 >= x1 - 1:
            return amount
    return None


def _amount_below(rows: list[Row], i: int, span: tuple[float, float]) -> Decimal | None:
    """Layout a intestazioni: il valore sta nelle righe sotto, nella stessa colonna dell'etichetta."""
    x0, x1 = span
    for row in rows[i + 1:i + 4]:
        amounts = _amounts(row)
        # Prima la colonna esatta dell'etichetta, poi con un po' di margine (importi allineati a destra).
        for margin in (0, 10):
            hits = [(w, a) for w, a in amounts if w.overlap(x0 - margin, x1 + margin) > 0]
            if hits:
                return max(hits, key=lambda h: h[0].overlap(x0, x1))[1]
    # Valore a capo, spostato a destra dell'etichetta: solo se la riga sotto contiene solo quell'importo.
    if i + 1 < len(rows) and len(rows[i + 1].words) == 1:
        return _amount_after(rows[i + 1], x1)
    return None


def read(doc: Document) -> Partial:
    values: dict[str, Decimal] = {}
    for page in reversed(doc.pages):  # i totali stanno in fondo, sull'ultima pagina
        for i, row in enumerate(page):
            for key, rx in LABELS.items():
                if key in values or not (span := _label_span(row, rx)):
                    continue
                amount = _amount_after(row, span[1])
                if amount is None:
                    amount = _amount_below(page, i, span)
                if amount is not None:
                    values[key] = abs(amount)
        if values:
            break
    return Partial({k: values[k] for k in LABELS if k in values})


def note(doc: Document) -> str:
    """Frase da aggiungere al messaggio di errore di un formato nuovo, vuota se non trova nulla."""
    try:
        found = read(doc)
    except Exception:  # la lettura parziale è un di più: non deve mai peggiorare il messaggio
        return ""
    return f". Intanto, {found.summary()}" if found.values else ""
