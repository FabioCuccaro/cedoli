"""Parser per il layout di cedolino con modello `PAYLUL01` (Libro Unico del Lavoro).

Il layout è a colonne con importi allineati a destra: ogni importo viene assegnato
alla colonna la cui intestazione finisce più vicino al suo bordo destro.
"""

import re
from decimal import Decimal

from bp.extract import Document, Row, Word
from bp.models import Contract, LeaveBalance, Line, Payslip, Period, Section
from bp.money import is_amount, is_year, parse_amount

NAME = "paylul01"
VERSION = "0.1.0"

_CODE = re.compile(r"^[A-Z0-9]{3,8}$")
CODE_MAX_X0 = 57  # i codici voce stanno nella prima colonna a sinistra
COLUMN_TOLERANCE = 25.0
SUMMARY_TOLERANCE = 40.0
COLUMNS_MIN_X0 = 200  # le intestazioni di colonna numeriche stanno a destra della descrizione

# Intestazioni delle tabelle: prima parola dell'intestazione -> sezione,
# e parola di intestazione di colonna -> campo di Line.
SECTIONS: dict[str, tuple[Section, list[tuple[str, str]]]] = {
    "VOCI": (Section.VOCI, [
        ("ORE/GIORNI", "qty"), ("UNITARIO", "unit_amount"), ("FIGURATI", "figurative"),
        ("TRATTENUTE", "deduction"), ("COMPETENZE", "earning"),
    ]),
    "TRATTENUTE": (Section.CONTRIBUTI, [
        ("IMPONIBILI", "base"), ("ALIQUOTE", "rate"),
        ("TRATTENUTE", "deduction"), ("COMPETENZE", "earning"),
    ]),
    "CTB.": (Section.DEDUCIBILI, [("DED.", "deductible"), ("DED.", "non_deductible")]),
    # In colonna ANNO le righe "Altri Sog." del conguaglio stampano i giorni di detrazione.
    "IMPOSTA": (Section.IMPOSTA, [("ANNO", "qty"), ("IMPONIBILI", "base"), ("FIGURATIVE", "figurative")]),
    "ADDIZIONALI": (Section.ADDIZIONALI, [
        ("IMPON/RATA", "base"), ("FIGURATIVE", "figurative"),
        ("TRATTENUTE", "deduction"), ("COMPETENZE", "earning"),
    ]),
}
SUMMARY_START = "Descrizione Imponibile Fiscale"

# Blocchi riassuntivi: (prefisso chiave, [(etichetta stampata, chiave)]).
SUMMARY_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("totali", [
        ("Imponibili", "imponibile_fiscale"), ("Lordo", "imposta_lorda"),
        ("Totale Trattenute", "trattenute"), ("Totale Competenze", "competenze"),
    ]),
    ("totali", [("NETTO", "netto")]),
    ("tfr", [
        ("Acc.TFR 31/12 AP", "accantonato_ap"), ("TFR F. C. 31/12AP", "fondo_ap"),
        ("Accant. TFR AC", "accantonato_ac"), ("TFR F. Compl. AC", "fondo_ac"),
        ("Anticipazioni AC", "anticipazioni_ac"), ("TFR a Tesoreria AC", "tesoreria_ac"),
    ]),
    ("irpef", [
        ("Imposta Lorda", "imposta_lorda"), ("Detr. Lav. Dip.", "detr_lavoro_dipendente"),
        ("Detr. Coniuge", "detr_coniuge"), ("Detr. Figli", "detr_figli"),
        ("Detr. Altri Fam.", "detr_altri_familiari"), ("Ulteriori Detr.", "ulteriori_detrazioni"),
        ("Totale Detrazioni", "totale_detrazioni"), ("Imposta Netta", "imposta_netta"),
    ]),
    ("annuo", [
        ("Retr. Utile TFR", "retribuzione_utile_tfr"), ("Ctr Az. F di Compl.", "ctr_azienda_fondo"),
        ("TFR F. di Compl.", "tfr_fondo"), ("Imponibile Fiscale Annuo", "imponibile_fiscale"),
        ("Imposta Lorda", "imposta_lorda"), ("Detrazioni Effettive", "detrazioni_effettive"),
        ("Imposta Dovuta", "imposta_dovuta"), ("Imposta Pagata", "imposta_pagata"),
    ]),
    ("progr", [
        ("Imp. INPS Progr.", "imponibile_inps"), ("Ctr. INPS Progr.", "contributi_inps"),
        ("Ctr. Dip. INPS", "contributi_inps_mese"), ("Cong. Credito", "conguaglio_credito"),
        ("Cong. Debito", "conguaglio_debito"), ("Detr. Lavoro Dipend.", "detr_lavoro_dipendente"),
        ("D. Coniuge", "detr_coniuge"), ("D. Figli", "detr_figli"),
        ("D. Altri Fam.", "detr_altri_familiari"), ("Detraz. Altre", "detr_altre"),
    ]),
    ("ratei", [
        ("Maturate", "maturate"), ("Godute", "godute"), ("Residue AP", "residue_ap"),
        ("Residue AP2", "residue_ap2"), ("Saldo", "saldo"), ("Arrot. Precedente", "arrot_precedente"),
    ]),
]
LEAVE_ROWS = ("FERIE", "R.O.L.")
DAYS_GROUP = [("GG INPS", "gg_inps"), ("GG.Detr.", "gg_detrazioni"), ("GG.Anf.", "gg_anf"), ("Settim.", "settimane")]

MONTHS = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}


class LayoutError(ValueError):
    pass


def detect(doc: Document) -> bool:
    if doc.keywords.get("HRZ_MODEL") == "PAYLUL01":
        return True
    text = " ".join(r.text for page in doc.pages for r in page)
    return all(s in text for s in ("LIBRO UNICO DEL LAVORO", "VOCI RETRIBUTIVE", "Imponibile Fiscale Annuo"))


def _label_spans(row: Row, labels: list[tuple[str, str]]) -> dict[str, tuple[float, float]] | None:
    """Trova le etichette in ordine nella riga e restituisce chiave -> (x0, x1)."""
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


def _assign_by_overlap(value: Word, headers: list[tuple[float, str, dict]]) -> str | None:
    """Etichetta a cui appartiene un valore del blocco riassuntivo.

    Prima cerca, salendo per al massimo tre righe di intestazione, un'etichetta che si
    sovrapponga orizzontalmente al valore. Se non c'è, usa l'etichetta della riga di
    intestazione più vicina il cui bordo destro è più vicino a quello del valore
    (gli importi sono allineati a destra e possono sporgere oltre l'etichetta).
    """
    above = sorted((h for h in headers if h[0] < value.top), key=lambda h: -h[0])
    for _, prefix, spans in above[:3]:
        best = max(spans.items(), key=lambda kv: value.overlap(*kv[1]))
        if value.overlap(*best[1]) > 0:
            return f"{prefix}.{best[0]}"
    if above:
        _, prefix, spans = above[0]
        key, (_, x1) = min(spans.items(), key=lambda kv: abs(kv[1][1] - value.x1))
        if abs(x1 - value.x1) <= SUMMARY_TOLERANCE:
            return f"{prefix}.{key}"
    return None


def _period(doc: Document) -> Period:
    kw = doc.keywords
    if kw.get("ANNO") and kw.get("QTMONTH"):
        return Period(year=int(kw["ANNO"]), month=int(kw["QTMONTH"]), kind=kw.get("DSMTSAL", ""))
    for row in doc.pages[0]:
        words = [w.text for w in row.words]
        for i, w in enumerate(words[:-1]):
            if w.lower() in MONTHS and is_year(words[i + 1]):
                kind = "Tredicesima" if "Tredicesima" in words else "Mensilita'normale"
                return Period(year=int(words[i + 1]), month=MONTHS[w.lower()], kind=kind)
    raise LayoutError("periodo di competenza non trovato")


def _salary_elements(rows: list[Row]) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    elements: dict[str, Decimal] = {}
    days: dict[str, Decimal] = {}
    days_header = None
    for row in rows:
        if days_header is None:
            spans = _label_spans(row, DAYS_GROUP)
            if spans:
                days_header = spans
            continue
        amounts = [w for w in row.words if is_amount(w.text)]
        name = " ".join(w.text for w in row.words if w.x1 < 220 and not is_amount(w.text))
        left = [w for w in amounts if w.x1 < 270]
        if name and left:
            elements[name] = parse_amount(left[0].text)
        for w in amounts:
            if w.x0 > 400:
                key = max(days_header.items(), key=lambda kv: w.overlap(*kv[1]))
                if w.overlap(*key[1]) > 0:
                    days[key[0]] = parse_amount(w.text)
        if name == "TOTALE":
            break
    return elements, days


def _lines(doc: Document) -> list[Line]:
    lines: list[Line] = []
    section, anchors = None, []
    money_columns: list[tuple[float, str]] = []
    for page in doc.pages:
        for row in page:
            first = row.words[0]
            if SUMMARY_START in row.text:
                section = None
                continue
            header = SECTIONS.get(first.text) if first.x0 > CODE_MAX_X0 else None
            if header and (first.text != "TRATTENUTE" or "PREVIDENZIALI" in row.text):
                section, columns = header
                anchors, used = [], set()
                for label, field in columns:
                    w = next((w for w in row.words
                              if w.text == label and w.x0 > COLUMNS_MIN_X0 and id(w) not in used), None)
                    if w is None:
                        raise LayoutError(f"intestazione di colonna {label!r} mancante in {row.text!r}")
                    used.add(id(w))
                    anchors.append((w.x1, field))
                # Alcune tabelle non stampano le intestazioni Trattenute/Competenze ma ne usano le colonne.
                fields = {f for _, f in anchors}
                anchors += [a for a in money_columns if a[1] not in fields]
                if section == Section.VOCI:
                    money_columns = [a for a in anchors if a[1] in ("deduction", "earning")]
                continue
            if section is None:
                continue
            if first.x0 < CODE_MAX_X0 and _CODE.match(first.text):
                line = Line(section=section, code=first.text, description="")
                desc = []
                for w in row.words[1:]:
                    if is_amount(w.text):
                        x1, field = min(anchors, key=lambda a: abs(a[0] - w.x1))
                        if abs(x1 - w.x1) > COLUMN_TOLERANCE:
                            raise LayoutError(f"importo fuori colonna in {first.text}: {w.text}")
                        setattr(line, field, parse_amount(w.text))
                    elif is_year(w.text) and w.x0 > 240:
                        line.year = int(w.text)
                    elif w.text != "c/DIP" and w.x1 < 250:
                        desc.append(w.text)
                line.description = " ".join(desc)
                lines.append(line)
            elif lines and any(c.isalpha() for c in row.text) and not any(is_amount(w.text) for w in row.words):
                # Riga di continuazione (es. regione o comune sotto un'addizionale).
                lines[-1].note = row.text
    return lines


def _summary(rows: list[Row]) -> tuple[dict[str, Decimal], list[LeaveBalance]]:
    start = next((i for i, r in enumerate(rows) if SUMMARY_START in r.text), None)
    if start is None:
        raise LayoutError("blocco riassuntivo non trovato")
    rows = rows[start:]
    headers: list[tuple[float, str, dict]] = []
    header_rows = set()
    for i, row in enumerate(rows):
        for prefix, labels in SUMMARY_GROUPS:
            spans = _label_spans(row, labels)
            if spans:
                headers.append((row.top, prefix, spans))
                header_rows.add(i)
                break
    summary: dict[str, Decimal] = {}
    leave: dict[str, dict[str, Decimal]] = {}
    for i, row in enumerate(rows):
        if i in header_rows:
            continue
        row_label = row.words[0].text if row.words[0].text in LEAVE_ROWS else None
        for w in row.words:
            if not is_amount(w.text):
                continue
            key = _assign_by_overlap(w, headers)
            if key is None:
                continue
            if row_label:
                leave.setdefault(row_label, {})[key.split(".", 1)[1]] = parse_amount(w.text)
            else:
                summary[key] = parse_amount(w.text)
    balances = [LeaveBalance(kind=k, **{f: v for f, v in vals.items() if f in LeaveBalance.model_fields})
                for k, vals in leave.items()]
    return summary, balances


def _summaries(doc: Document) -> tuple[dict[str, Decimal], list[LeaveBalance]]:
    """Nei cedolini su più pagine il blocco riassuntivo si ripete: i totali sono valorizzati
    solo nell'ultima pagina, ferie e ROL possono esserlo solo nella prima. Si uniscono i valori
    trovati, con precedenza alle pagine successive."""
    summary: dict[str, Decimal] = {}
    leave: dict[str, LeaveBalance] = {}
    found = False
    for page in doc.pages:
        if not any(SUMMARY_START in r.text for r in page):
            continue
        found = True
        page_summary, page_leave = _summary(page)
        summary.update(page_summary)
        leave.update({b.kind: b for b in page_leave})
    if not found:
        raise LayoutError("blocco riassuntivo non trovato")
    return summary, list(leave.values())


def parse(doc: Document) -> Payslip:
    kw = doc.keywords
    elements, days = _salary_elements(doc.pages[0])
    summary, leave = _summaries(doc)
    return Payslip(
        file_sha256=doc.sha256,
        parser=NAME,
        parser_version=VERSION,
        pages=len(doc.pages),
        period=_period(doc),
        contract=Contract(
            employer=kw.get("DSCOMPANY") or None,
            ccnl=kw.get("DSAGRMNT") or None,
            qualifica=kw.get("DSQUAGRMNT") or None,
        ),
        salary_elements=elements,
        days=days,
        lines=_lines(doc),
        summary=summary,
        leave=leave,
    )
