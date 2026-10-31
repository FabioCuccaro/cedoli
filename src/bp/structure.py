"""Dalla struttura anonima di un formato nuovo alla bozza del suo parser.

Chi mantiene Busta chiara riceve `struttura_anonima.json` (vedi anonymize.py) e con `bp struttura`:
- ottiene un riepilogo del layout: gestionale, pagine, font, etichette dei totali, colonne degli importi;
- rigenera un PDF sintetico con le stesse parole nelle stesse posizioni, da usare come base per i test;
- scrive lo scheletro del modulo parser, con riconoscimento e costanti già compilati.

Il parser vero va poi scritto a mano, provandolo sul PDF sintetico e, se possibile, su un cedolino
reale di chi ha mandato la struttura.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from bp import partial
from bp.anonymize import CODE, FORMAT, vocabulary
from bp.extract import Document, Row, Word, parse_keywords
from bp.money import is_amount

FONT, SIZE = "Helvetica", 7.0
# Bordi destri degli importi entro questa distanza appartengono alla stessa colonna.
COLUMN_TOLERANCE = 6.0
# Margine tolto alla larghezza di ogni parola nel PDF sintetico.
GAP = 1.5


def load(path: str | Path) -> Document:
    """Ricostruisce un Document dalla struttura anonima, così i lettori lo trattano come un PDF."""
    path = Path(path)
    return from_dump(json.loads(path.read_text(encoding="utf-8")), path)


def from_dump(dump: dict, path: Path | None = None) -> Document:
    name = path.name if path else "il file"
    if not isinstance(dump, dict) or dump.get("formato") != FORMAT:
        raise ValueError(f"{name} non è una struttura anonima di Busta chiara")
    pages = []
    for n, rows in enumerate(dump["pagine"]):
        pages.append([Row([Word(t, x0, x1, r["top"], n, font) for t, x0, x1, font in r["parole"]])
                      for r in rows if r["parole"]])
    meta = dump.get("metadati", {})
    return Document(path=path or Path("struttura_anonima.json"), sha256="", metadata=meta,
                    keywords=parse_keywords(meta.get("Keywords", "")), pages=pages)


@dataclass
class Layout:
    producer: str
    model: str | None
    pages: int
    fonts: list[tuple[str, int]]
    totals: dict[str, tuple[int, float, float]]  # chiave → (pagina, top, x1 dell'etichetta)
    partial: partial.Partial
    code_x0: float | None  # bordo sinistro dei codici delle voci
    columns: list[float]  # bordi destri delle colonne degli importi, da sinistra
    headers: list[str]  # righe fatte solo di parole del vocabolario, senza cifre


def _model(doc: Document) -> str | None:
    return next((v for k, v in doc.keywords.items() if k.endswith("_MODEL")), None)


def _clusters(values: list[float], min_count: int) -> list[float]:
    groups: list[list[float]] = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= COLUMN_TOLERANCE:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [round(max(g), 1) for g in groups if len(g) >= min_count]


def analyze(doc: Document) -> Layout:
    rows = [r for page in doc.pages for r in page]
    words = [w for r in rows for w in r.words]
    fonts = Counter(w.font for w in words).most_common()
    totals = {}
    for page in doc.pages:
        for row in page:
            for key, rx in partial.LABELS.items():
                if key not in totals and (span := partial._label_span(row, rx)):
                    totals[key] = (row.page, round(row.top, 1), round(span[1], 1))
    codes = [r.words[0].x0 for r in rows if CODE.fullmatch(r.words[0].text)]
    amounts = [w.x1 for w in words if is_amount(w.text)]
    vocab = vocabulary()
    seen: set[str] = set()  # le intestazioni ripetute su ogni pagina contano una volta
    headers = [r.text for r in rows
               if r.text not in seen and not seen.add(r.text) and len(r.words) >= 3 and not re.search(r"\d", r.text)
               and all(t.upper() in vocab for t in re.findall(r"[^\W\d_]+", r.text))]
    return Layout(
        producer=doc.metadata.get("Producer") or doc.metadata.get("Creator") or "sconosciuto",
        model=_model(doc),
        pages=len(doc.pages),
        fonts=fonts,
        totals=totals,
        partial=partial.read(doc),
        code_x0=round(Counter(round(x) for x in codes).most_common(1)[0][0], 1) if len(codes) >= 3 else None,
        columns=_clusters(amounts, min_count=3),
        headers=headers,
    )


def describe(layout: Layout) -> str:
    lines = [
        f"Gestionale: {layout.producer}" + (f", modello {layout.model}" if layout.model else ""),
        f"Pagine: {layout.pages}",
        "Font: " + ", ".join(f"{f or '?'} ({n})" for f, n in layout.fonts[:4]),
        "Etichette dei totali: " + (", ".join(f"{k} a pagina {p + 1}, riga {t}" for k, (p, t, _) in
                                              layout.totals.items()) or "nessuna trovata"),
        "Lettura parziale: " + ("funziona" if len(layout.partial.values) == 3 else
                                f"trova {len(layout.partial.values)} totali su 3"),
        f"Codici delle voci: colonna a x={layout.code_x0}" if layout.code_x0 is not None
        else "Codici delle voci: non riconosciuti",
        "Colonne degli importi (bordo destro): " + (", ".join(map(str, layout.columns)) or "nessuna"),
        f"Intestazioni ({len(layout.headers)}):",
        *(f"  {h}" for h in layout.headers[:15]),
    ]
    return "\n".join(lines)


def synthesize(doc: Document, out: Path) -> Path:
    """PDF con le stesse parole nelle stesse posizioni (testo mascherato: cifre 9, nomi X).

    Usa reportlab, che è solo tra le dipendenze di sviluppo: serve a chi mantiene l'app, non all'app.
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen.canvas import Canvas

    width = max((w.x1 for page in doc.pages for r in page for w in r.words), default=0)
    size = landscape(A4) if width > A4[0] else A4
    c = Canvas(str(out), pagesize=size)
    keep = {k: v for k, v in doc.metadata.items() if k in ("Producer", "Creator")}
    if doc.keywords:
        c.setKeywords(";".join(f"{k}={v}" for k, v in doc.keywords.items()) + ";")
    if "Creator" in keep:
        c.setCreator(keep["Creator"])
    for page in doc.pages:
        for row in page:
            for w in row.words:
                natural = stringWidth(w.text, FONT, SIZE) or 1
                t = c.beginText(w.x0, size[1] - w.top - SIZE)
                t.setFont(FONT, SIZE)
                # Larghezza dell'originale meno un margine, perché parole vicine non si fondano in una.
                t.setHorizScale(100 * max(w.x1 - w.x0 - GAP, 1) / natural)
                t.textOut(w.text)
                c.drawText(t)
        c.showPage()
    c.save()
    return out


def name(layout: Layout) -> str:
    """Nome del formato: il modello del gestionale se c'è, altrimenti nuovo_formato."""
    return re.sub(r"\W", "", (layout.model or "nuovo_formato").lower()) or "nuovo_formato"


def skeleton(layout: Layout) -> str:
    """Sorgente del modulo parser da completare: riconoscimento e costanti presi dalla struttura."""
    name_ = name(layout)
    if layout.model:
        detect = f'    return any(k.endswith("_MODEL") and v == {layout.model!r} for k, v in doc.keywords.items())'
    else:
        signs = layout.headers[:3] or ["DA COMPLETARE"]
        detect = (f"    text = \" \".join(r.text for page in doc.pages for r in page)\n"
                  f"    return all(s in text for s in {signs!r})")
    return f'''"""Parser per il layout `{name_}` ({layout.producer}).

Bozza generata da `bp struttura` a partire da una struttura anonima: riconoscimento e costanti
vengono dalla struttura, la lettura delle voci va scritta. Poi registrare il modulo in
parsers/__init__.py, aggiungere un generatore sintetico in tests/ e i test.
"""

from bp.extract import Document
from bp.models import Payslip

NAME = {name_!r}
VERSION = "0.0.1"

# Dalla struttura anonima: pagine {layout.pages}, font principali {[f for f, _ in layout.fonts[:2]]!r}.
CODE_X0 = {layout.code_x0!r}  # bordo sinistro dei codici delle voci
COLUMNS = {layout.columns!r}  # bordi destri delle colonne degli importi, da sinistra
TOTALS = {layout.totals!r}  # etichetta → (pagina, top, x1)


def detect(doc: Document) -> bool:
{detect}


def parse(doc: Document) -> Payslip:
    raise NotImplementedError("da scrivere: voci, totali e riepilogo, come in paylul01.py e hr1luldip.py")
'''
