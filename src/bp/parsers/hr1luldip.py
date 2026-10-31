"""Parser per il layout di cedolino con modello `HR1LULDIP` (Libro Unico del Lavoro, Zucchetti).

Il modulo prestampato (etichette, intestazioni, scritte verticali) usa un font diverso dai
dati: il parser legge solo le parole nel font dei dati, il più usato nel documento (DejaVu
nei cedolini reali, Arial il modulo), tranne le etichette dei totali.
Le voci stanno in un'unica tabella; gli importi si assegnano alla colonna per bordo destro.
Imponibile, IRPEF lorda, detrazioni e ritenuta IRPEF del mese finiscono nel riepilogo, come
nel layout PAYLUL01, così i controlli di coerenza li trovano con le stesse chiavi.
"""

import re
from collections import Counter
from decimal import Decimal

from bp.extract import Document, Row, Word
from bp.models import Contract, LeaveBalance, Line, Payslip, Period, Section
from bp.money import is_amount, is_year, parse_amount

NAME = "hr1luldip"
VERSION = "0.1.0"

# Parole a meno di questa distanza verticale formano una riga: descrizione e importi di una
# voce sono a volte stampati su due righe sfalsate di un punto.
ROW_MERGE = 3.5
# Una riga vuota più alta di così separa la tabella delle voci da quella dei contributi.
BLOCK_GAP = 15.0
# Fasce verticali della pagina: intestazione ripetuta su ogni pagina, tabella, riquadri in fondo.
TABLE_TOP = 280
BOXES_TOP = 600
CODE_X0 = (36, 43)
DESC_MAX_X1 = 270
COLUMN_TOLERANCE = 12.0
# Bordo destro delle colonne della tabella.
COL_UNIT = 315  # importo unitario (voci) o imponibile (contributi, imposte)
COL_REF = 421  # ore/giorni (voci), aliquota (contributi), residuo da trattenere (addizionali)
COL_DEDUCTION = 493
COL_EARNING = 569  # gli importi figurativi, tra parentesi, finiscono poco più a destra

_CODE = re.compile(r"^([A-Z0-9]{6})(.*)$")
_QTY = re.compile(r"^(-?[\d.,]+)(ORE|GG)$")

# Righe di imposta che sono totali del mese, non trattenute a sé.
IRPEF_SUMMARY = {
    "F02000": ("totali.imponibile_fiscale", "base"),
    "F02010": ("irpef.imposta_lorda", "base"),
    "F02500": ("irpef.totale_detrazioni", "base"),
    "F03020": ("irpef.imposta_netta", "deduction"),
}
# Righe senza codice sotto la tabella.
TABLE_SUMMARY = {
    "Retribuzione utile T.F.R.": "tfr.retribuzione_utile_mese",
    "Quota T.F.R.": "tfr.quota_mese",
    "Imp. INAIL": "imponibili.inail",
}
# Riquadri in fondo: intestazione -> chiave, valori allineati a destra sotto l'intestazione.
SUMMARY_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("annuo", [
        ("OneriDed", "oneri_deducibili"), ("Imponibile", "imponibile_fiscale"), ("IRPEF lorda", "imposta_lorda"),
        ("Detrazioni", "detrazioni_effettive"), ("IRPEF trattenuta", "imposta_trattenuta"),
        ("Add.regionale", "addizionale_regionale"), ("Add.comunale", "addizionale_comunale"),
    ]),
    ("progr", [
        ("Imp. INPS", "imponibile_inps"), ("Imp. INAIL", "imponibile_inail"),
        ("Imp. IRPEF", "imponibile_fiscale"), ("IRPEF pagata", "irpef_pagata"),
    ]),
    ("tfr", [
        # Stesse chiavi del layout PAYLUL01 dove il significato coincide.
        ("F.do 31/12", "accantonato_ap"), ("Rivalutaz.", "rivalutazione"), ("Imp.rival.", "imposta_rivalutazione"),
        ("Quota anno", "accantonato_ac"), ("TFR a fondi", "fondo_ac"), ("Anticipi", "anticipazioni_ac"),
    ]),
]
LEAVE_HEADER = [("Residuo AP", "residue_ap"), ("Maturato", "maturate"), ("Goduto", "godute"), ("Saldo", "saldo")]
LEAVE_ROWS = {"Ferie": "FERIE", "Permessi": "R.O.L.", "R.O.L.": "R.O.L."}
# Etichette dei totali, nel font del modulo, con la "s" al posto degli spazi.
TOTALS = {"TOTALEsCOMPETENZE": "totali.competenze", "TOTALEsTRATTENUTE": "totali.trattenute"}

# Tipo cedolino nei metadati (TIPCED) -> tipo di mensilità.
KIND_NORMAL = "Mensilita'normale"


class LayoutError(ValueError):
    pass


def detect(doc: Document) -> bool:
    return doc.keywords.get("HRZ_MODEL") == "HR1LULDIP"


def _font(w: Word) -> str:
    return w.font.split("+")[-1]  # senza il prefisso del sottoinsieme incorporato, "SJJVJN+DejaVuSerif"


def _data_font(doc: Document) -> str:
    fonts = Counter(_font(w).split("-")[0] for page in doc.pages for r in page for w in r.words)
    if not fonts:
        raise LayoutError("nessun testo nel cedolino")
    return fonts.most_common(1)[0][0]


def _rows(page: list[Row], font: str, data: bool = True) -> list[Row]:
    """Le righe con le sole parole nel font dei dati (o, con data=False, del modulo),
    unendo quelle sfalsate di poco."""
    out: list[Row] = []
    for row in page:
        words = [w for w in row.words if (_font(w).split("-")[0] == font) == data]
        if not words:
            continue
        if out and min(w.top for w in words) - out[-1].top <= ROW_MERGE:
            out[-1].words = sorted(out[-1].words + words, key=lambda w: w.x0)
        else:
            out.append(Row(words))
    return out


def _period(doc: Document) -> Period:
    kw = doc.keywords
    try:
        year, month = int(kw["ANNO"]), int(kw["MESE"])
    except (KeyError, ValueError):
        raise LayoutError("periodo di competenza non trovato nei metadati") from None
    kind, label = kw.get("TIPCED", ""), kw.get("DTIPCED", "")
    if kind == "50":
        kind = KIND_NORMAL
    elif kind == "40":  # mensilità aggiuntive automatiche: la quattordicesima a giugno, la tredicesima a dicembre
        kind = "Tredicesima" if month == 12 else "Quattordicesima"
    else:
        kind = label or f"Cedolino {kind}"
    return Period(year=year, month=month, kind=kind)


def _contract(doc: Document, rows: list[Row]) -> Contract:
    qualifica = ccnl = None
    for i, row in enumerate(rows):
        if "Livello" in [w.text for w in row.words]:
            qualifica = row.text
            for below in rows[i + 1:i + 4]:
                words = [w.text for w in below.words if w.x0 > 250 and any(c.isalpha() for c in w.text)]
                if words:
                    ccnl = " ".join(words)
                    break
            break
    return Contract(employer=doc.keywords.get("DENAZI") or None, ccnl=ccnl, qualifica=qualifica)


def _salary_elements(rows: list[Row]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Elementi della retribuzione, con il loro totale, e giorni del mese."""
    days: dict[str, Decimal] = {}
    elements: dict[str, Decimal] = {}
    for i, row in enumerate(rows):
        texts = [w.text for w in row.words]
        if "PAGA" in texts and "BASE" in texts:
            labels: list[tuple[float, list[tuple[str, float]]]] = []  # x0 e parole di ogni etichetta
            for w in row.words:
                if labels and w.x0 - labels[-1][1][-1][1] < 4:
                    labels[-1][1].append((w.text, w.x1))
                else:
                    labels.append((w.x0, [(w.text, w.x1)]))
            for v in rows[i + 1].words:
                if is_amount(v.text):
                    _, parts = max((l for l in labels if l[0] <= v.x0), key=lambda l: l[0], default=labels[0])
                    elements[" ".join(t for t, _ in parts)] = parse_amount(v.text)
            for j in range(i + 2, min(i + 5, len(rows))):
                total = [w for w in rows[j].words if is_amount(w.text) and w.x0 > 450]
                if total:
                    elements["TOTALE"] = parse_amount(total[-1].text)
                    break
            return elements, days
        # Riga dei giorni: settimane, giorni INPS, ..., giorni per le detrazioni.
        numbers = [w for w in row.words if w.text.isdigit() or is_amount(w.text)]
        if numbers and len(numbers) == len(row.words) and len(numbers) >= 4:
            for w in numbers:
                value = parse_amount(w.text) if is_amount(w.text) else Decimal(w.text)
                if w.x0 < 50:
                    days["settimane"] = value
                elif w.x0 < 90:
                    days["gg_inps"] = value
                elif 250 < w.x0 < 300:
                    days["gg_detrazioni"] = value
    raise LayoutError("elementi della retribuzione non trovati")


def _column(w: Word) -> str | None:
    if COL_UNIT - 2 * COLUMN_TOLERANCE < w.x1 <= COL_UNIT + 2:
        return "unit"
    if abs(w.x1 - COL_REF) <= 2 * COLUMN_TOLERANCE:  # "0,10000 %" ha il simbolo staccato
        return "ref"
    if abs(w.x1 - COL_DEDUCTION) <= COLUMN_TOLERANCE:
        return "deduction"
    if abs(w.x1 - COL_EARNING) <= 4:
        return "earning"
    return None


def _line(code: str, rest: str, words: list[Word], section: Section) -> Line:
    line = Line(section=section, code=code, description="")
    desc = [rest] if rest else []
    notes: list[str] = []
    figurative = False
    for w in words:
        t = w.text
        if t == "(":
            figurative = True
            continue
        if t.endswith(")") and is_amount(t[:-1]):
            line.figurative = parse_amount(t[:-1])
            continue
        if (m := _QTY.match(t)) and is_amount(m.group(1)):
            line.qty = parse_amount(m.group(1))
            continue
        if t == "%":
            continue
        rate = t[:-1] if t.endswith("%") else t
        if is_amount(rate):
            column = _column(w)
            value = parse_amount(rate)
            if column == "unit":
                if section == Section.VOCI:
                    line.unit_amount = value
                else:
                    line.base = value
            elif column == "ref":
                if section == Section.ADDIZIONALI:  # come in PAYLUL01, il residuo è un importo figurativo
                    line.figurative = value
                else:
                    line.rate = value
            elif column == "deduction":
                line.deduction = value
            elif column == "earning":
                line.earning = value
            else:
                raise LayoutError(f"importo fuori colonna in {code}: {t}")
        elif is_year(t) and 200 < w.x0 < 232:
            line.year = int(t)
        elif section == Section.ADDIZIONALI and (w.x0 >= 230 or notes):
            if t != "Residuo":  # etichetta dell'importo ancora da trattenere
                notes.append(t)
        elif w.x1 <= DESC_MAX_X1 and not notes:
            desc.append(t)
        else:
            notes.append(t)
    if figurative and line.figurative is None:
        raise LayoutError(f"importo figurativo non letto in {code}")
    line.description = " ".join(desc)
    line.note = " ".join(notes) or None
    return line


def _table(pages: list[list[Row]]) -> tuple[list[Line], dict[str, Decimal]]:
    lines: list[Line] = []
    summary: dict[str, Decimal] = {}
    for rows in pages:
        section = Section.VOCI if not lines else lines[-1].section
        last_top = None
        for row in rows:
            if row.top < TABLE_TOP:
                continue
            if row.top > BOXES_TOP:
                break
            if last_top is not None and row.top - last_top > BLOCK_GAP and section == Section.VOCI and lines:
                section = Section.CONTRIBUTI
            last_top = row.top
            words = [w for w in row.words if w.text != "*"]
            first = next((w for w in words if CODE_X0[0] <= w.x0 <= CODE_X0[1]), None)
            m = _CODE.match(first.text) if first else None
            if m is None:
                label = " ".join(w.text for w in words if not is_amount(w.text) and w.x1 < 270)
                value = next((w for w in words if is_amount(w.text)), None)
                if label in TABLE_SUMMARY and value is not None:
                    summary[TABLE_SUMMARY[label]] = parse_amount(value.text)
                continue
            code, rest = m.groups()
            others = [w for w in words if w is not first]
            line_section = section
            if code.startswith("F"):
                text = (rest + " " + " ".join(w.text for w in others)).lower()
                line_section = Section.ADDIZIONALI if "add" in text else Section.IMPOSTA
            line = _line(code, rest, others, line_section)
            if code in IRPEF_SUMMARY:
                key, field = IRPEF_SUMMARY[code]
                value = getattr(line, field)
                if value is not None:
                    summary[key] = value
                continue
            lines.append(line)
    return lines, summary


def _spans(row: Row, labels: list[tuple[str, str]]) -> dict[str, tuple[float, float]] | None:
    words, i, spans = row.words, 0, {}
    for label, key in labels:
        tokens = label.split()
        while i <= len(words) - len(tokens) and [w.text for w in words[i:i + len(tokens)]] != tokens:
            i += 1
        if i > len(words) - len(tokens):
            return None
        spans[key] = (words[i].x0, words[i + len(tokens) - 1].x1)
        i += len(tokens)
    return spans


def _boxes(rows: list[Row], form_rows: list[Row]) -> tuple[dict[str, Decimal], list[LeaveBalance]]:
    summary: dict[str, Decimal] = {}
    leave: list[LeaveBalance] = []
    bottom = [r for r in rows if r.top > BOXES_TOP]
    headers: list[tuple[int, str, dict]] = []
    leave_header = None
    for i, row in enumerate(bottom):
        for prefix, labels in SUMMARY_GROUPS:
            spans = _spans(row, labels)
            if spans:
                headers.append((i, prefix, spans))
                break
        else:
            if _spans(row, LEAVE_HEADER[:3]):
                leave_header = _spans(row, LEAVE_HEADER) or _spans(row, LEAVE_HEADER[:3])
    for i, prefix, spans in headers:
        if i + 1 >= len(bottom):
            continue
        # Il riepilogo IRPEF dell'anno è "Annuale" nel conguaglio di dicembre e "Licenz." in quello
        # di cessazione, che vale solo per i mesi lavorati: va tenuto separato.
        if prefix == "annuo" and bottom[i + 1].words[0].text.startswith("Licenz"):
            prefix = "cessazione"
        for w in bottom[i + 1].words:
            if not is_amount(w.text):
                continue
            key, (_, x1) = min(spans.items(), key=lambda kv: abs(kv[1][1] - w.x1))
            if abs(x1 - w.x1) <= 8:
                summary[f"{prefix}.{key}"] = parse_amount(w.text)
    if leave_header:
        for row in bottom:
            kind = next((LEAVE_ROWS[w.text] for w in row.words if w.text in LEAVE_ROWS and w.x0 < 60), None)
            if kind is None:
                continue
            values = {}
            for w in row.words:
                if is_amount(w.text):
                    key, (x0, _) = min(leave_header.items(), key=lambda kv: abs(kv[1][0] - w.x0))
                    if abs(x0 - w.x0) <= 6:
                        values[key] = parse_amount(w.text)
            leave.append(LeaveBalance(kind=kind, unit="ore", **values))
    # Totali: l'etichetta è nel font del modulo, l'importo nel font dei dati sulla stessa riga.
    amounts = [w for r in bottom for w in r.words if is_amount(w.text) and w.x0 > 500]
    for r in form_rows:
        for w in r.words:
            if w.text in TOTALS:
                value = min(amounts, key=lambda a: abs(a.top - w.top), default=None)
                if value is not None and abs(value.top - w.top) <= 4:
                    summary[TOTALS[w.text]] = parse_amount(value.text)
    net = next((w for r in bottom for w in r.words if w.text.endswith("€") and is_amount(w.text[:-1])), None)
    if net is None:
        raise LayoutError("netto del mese non trovato")
    summary["totali.netto"] = parse_amount(net.text[:-1])
    return summary, leave


def parse(doc: Document) -> Payslip:
    font = _data_font(doc)
    pages = [rows for rows in (_rows(page, font) for page in doc.pages) if rows]  # la seconda pagina è spesso vuota
    first = pages[0]
    elements, days = _salary_elements(first)
    lines, summary = _table(pages)
    last = next(page for page in reversed(doc.pages) if _rows(page, font))  # i totali sono sull'ultima con dati
    boxes, leave = _boxes(_rows(last, font), _rows(last, font, data=False))
    summary.update(boxes)
    # Il progressivo comprende il mese: è l'imponibile dell'anno fino a qui, come "annuo" in PAYLUL01.
    if "progr.imponibile_fiscale" in summary:
        summary.setdefault("annuo.imponibile_fiscale", summary["progr.imponibile_fiscale"])
    return Payslip(
        file_sha256=doc.sha256,
        parser=NAME,
        parser_version=VERSION,
        pages=len(doc.pages),
        period=_period(doc),
        contract=_contract(doc, first),
        salary_elements=elements,
        days=days,
        lines=lines,
        summary=summary,
        leave=leave,
    )

