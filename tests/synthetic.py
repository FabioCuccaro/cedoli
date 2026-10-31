"""Generatore di cedolini sintetici nel layout PAYLUL01.

Riproduce le posizioni delle intestazioni e l'allineamento a destra delle colonne del
layout reale, con importi e anagrafica inventati. Serve per testare il parser senza
mai mettere un cedolino vero nel repository.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

W, H = 595.27, 841.88
FONT, SIZE = "Helvetica", 7

# Anagrafica finta: i test verificano che non finisca nell'output.
FAKE_NAME = "ROSSI MARIO"
FAKE_CF = "RSSMRA80A01H501U"
FAKE_IBAN = "IT60X0542811101000000123456"

# Bordo destro delle colonne numeriche delle tabelle.
X1 = {"qty": 273, "unit": 344, "fig": 424, "trat": 500, "comp": 568, "year": 273, "base": 344, "rate": 424}

# Righe di intestazione del blocco riassuntivo: (top, [(etichetta, x0)]).
SUMMARY_HEADERS = {
    "totali": (588, [("Imponibili", 264), ("Lordo", 372), ("Totale Trattenute", 440), ("Totale Competenze", 506)]),
    "netto": (642, [("NETTO", 484)]),
    "tfr": (655, [("Acc.TFR 31/12 AP", 26), ("TFR F. C. 31/12AP", 93), ("Accant. TFR AC", 167),
                  ("TFR F. Compl. AC", 233), ("Anticipazioni AC", 304), ("TFR a Tesoreria AC", 367)]),
    "irpef": (685, [("Imposta Lorda", 30), ("Detr. Lav. Dip.", 92), ("Detr. Coniuge", 155), ("Detr. Figli", 224),
                    ("Detr. Altri Fam.", 278), ("Ulteriori Detr.", 343), ("Totale Detrazioni", 442),
                    ("Imposta Netta", 515)]),
    "annuo": (708, [("Retr. Utile TFR", 29), ("Ctr Az. F di Compl.", 85), ("TFR F. di Compl.", 149),
                    ("Imponibile Fiscale Annuo", 215), ("Imposta Lorda", 304), ("Detrazioni Effettive", 364),
                    ("Imposta Dovuta", 444), ("Imposta Pagata", 513)]),
    "progr": (727, [("Imp. INPS Progr.", 26), ("Ctr. INPS Progr.", 89), ("Ctr. Dip. INPS", 154),
                    ("Cong. Credito", 212), ("Cong. Debito", 262), ("Detr. Lavoro Dipend.", 314),
                    ("D. Coniuge", 391), ("D. Figli", 443), ("D. Altri Fam.", 480), ("Detraz. Altre", 526)]),
    "ratei": (750, [("Maturate", 144), ("Godute", 223), ("Residue AP", 291), ("Residue AP2", 366),
                    ("Saldo", 452), ("Arrot. Precedente", 507)]),
}
# Riga dei valori sotto ciascuna intestazione (il netto sta nella riga del TFR).
VALUE_TOP = {"totali": 617, "netto": 667, "tfr": 666, "irpef": 691, "annuo": 714, "progr": 735}
LEAVE_TOP = {"FERIE": 758, "R.O.L.": 767}
# Il riquadro "Imponibili / Lordo" sta su una riga sua, sopra i totali.
IMPONIBILI_TOP = 593


def fmt(value: Decimal | str | int) -> str:
    """Formato italiano: 1.234,56 (le aliquote e gli unitari mantengono i loro decimali)."""
    d = Decimal(str(value))
    sign = "-" if d < 0 else ""
    integer, _, frac = f"{abs(d):f}".partition(".")
    groups = []
    while len(integer) > 3:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    groups.insert(0, integer)
    return f"{sign}{'.'.join(groups)},{frac or '00'}"


@dataclass
class Spec:
    year: int = 2026
    month: int = 3
    kind: str = "Mensilita'normale"
    elements: dict[str, str] = field(default_factory=dict)
    days: tuple[str, str, str] | None = ("26,00", "31,00", "26,00")
    voci: list[dict] = field(default_factory=list)
    contributi: list[dict] = field(default_factory=list)
    deducibili: list[dict] = field(default_factory=list)
    addizionali: list[dict] = field(default_factory=list)
    # Chiave come nel parser (es. "irpef.imposta_netta") -> valore.
    summary: dict[str, str] = field(default_factory=dict)
    leave: dict[str, dict[str, str]] = field(default_factory=dict)
    metadata: bool = True
    two_pages: bool = False


class _Page:
    def __init__(self, canvas: Canvas):
        self.c = canvas
        canvas.setFont(FONT, SIZE)

    def text(self, top: float, x0: float, s: str) -> None:
        self.c.drawString(x0, H - top - SIZE, s)

    def right(self, top: float, x1: float, s: str, size: float = SIZE) -> None:
        self.c.setFont(FONT, size)
        self.c.drawRightString(x1, H - top - SIZE, s)
        self.c.setFont(FONT, SIZE)


def _label_x1(label: str, x0: float) -> float:
    return x0 + stringWidth(label, FONT, SIZE)


def _header(p: _Page, spec: Spec) -> None:
    p.text(81, 21, "LIBRO UNICO DEL LAVORO")
    p.text(93, 22, "AZIENDA DI ESEMPIO S.R.L.")
    p.text(130, 278, "01/01/1980")
    p.text(130, 332, FAKE_CF)
    p.text(216, 325, FAKE_NAME)
    p.text(217, 290, "Nominativo:")
    p.text(167, 411, "GG INPS")
    p.text(167, 458, "GG.Detr.")
    p.text(167, 504, "GG.Anf.")
    p.text(167, 544, "Settim.")
    top = 170
    if spec.days:
        for x1, v in zip((433, 480, 525), spec.days):
            p.right(top + 1, x1, v)
    for name, amount in spec.elements.items():
        p.text(top, 22, name)
        p.right(top, 260, amount)
        top += 7
    p.text(274, 118, "TOTALE")
    total = sum((Decimal(v.replace(".", "").replace(",", ".")) for v in spec.elements.values()), Decimal("0"))
    p.right(272, 260, fmt(total))
    months = "Gennaio Febbraio Marzo Aprile Maggio Giugno Luglio Agosto Settembre Ottobre Novembre Dicembre".split()
    p.text(260, 385, "Periodo Competenza")
    p.text(272, 337, f"{months[spec.month - 1]} {spec.year}")


def _table(p: _Page, top: float, title: str, columns: list[tuple[str, float]], rows: list[dict]) -> float:
    p.text(top, 58, title)
    for label, x1 in columns:
        p.right(top, x1, label, size=6)  # come nel layout reale, intestazioni più piccole
    top += 9
    for r in rows:
        p.text(top, 21, r["code"])
        p.text(top, 58, r["desc"])
        if "year" in r:
            p.right(top, X1["year"], str(r["year"]))
        for key in ("qty", "unit", "base", "rate", "fig", "trat", "comp", "ded", "nonded"):
            if key in r:
                x1 = {"ded": 344, "nonded": 424}.get(key) or X1[key]
                p.right(top, x1, r[key])
        top += 10
        if "note" in r:
            p.text(top, 58, r["note"])
            top += 10
    return top


def _tables(p: _Page, spec: Spec) -> None:
    top = 312
    top = _table(p, top, "VOCI RETRIBUTIVE", [
        ("ORE/GIORNI", 273), ("IMPORTO UNITARIO", 344), ("IMPORTI FIGURATI", 424),
        ("TRATTENUTE", 500), ("COMPETENZE", 568)], spec.voci)
    top = _table(p, top, "TRATTENUTE PREVIDENZIALI", [
        ("IMPONIBILI", 344), ("ALIQUOTE", 424), ("TRATTENUTE", 500), ("COMPETENZE", 568)], spec.contributi)
    if spec.deducibili:
        top = _table(p, top, "", [("CTB. DED.", 344), ("CTB.NON DED.", 424)], spec.deducibili)
    if spec.addizionali:
        _table(p, top, "ADDIZIONALI", [
            ("ANNO", 273), ("IMPON/RATA", 344), ("FIGURATIVE", 424),
            ("TRATTENUTE", 500), ("COMPETENZE", 568)], spec.addizionali)


def _summary(p: _Page, spec: Spec, with_totals: bool, with_leave: bool) -> None:
    p.text(588, 77, "Descrizione Imponibile Fiscale")
    p.text(593, 23, "Emolumenti correnti")
    p.text(637, 26, "IBAN")
    p.text(635, 56, FAKE_IBAN)
    for group, (top, labels) in SUMMARY_HEADERS.items():
        for label, x0 in labels:
            p.text(top, x0, label)
    p.text(758, 31, "FERIE")
    p.text(767, 31, "R.O.L.")
    for key, value in spec.summary.items():
        group, name = key.split(".", 1)
        if not with_totals and group == "totali":
            continue
        if key == "totali.netto":
            label, x0 = SUMMARY_HEADERS["netto"][1][0]
            p.right(VALUE_TOP["netto"], _label_x1(label, x0) + 15, value)
            continue
        if key in ("totali.imponibile_fiscale", "totali.imposta_lorda"):
            # Come nel layout reale, questi importi sporgono oltre il bordo destro dell'etichetta.
            x1 = {"totali.imponibile_fiscale": 326, "totali.imposta_lorda": 427}[key]
            p.right(IMPONIBILI_TOP, x1, value)
            continue
        label, x0 = SUMMARY_HEADERS[group][1][_index(group, name)]
        p.right(VALUE_TOP[group], _label_x1(label, x0), value)
    if with_leave:
        for kind, values in spec.leave.items():
            for name, value in values.items():
                label, x0 = SUMMARY_HEADERS["ratei"][1][_index("ratei", name)]
                p.right(LEAVE_TOP[kind], _label_x1(label, x0), value)


_KEYS = {
    "totali": ["imponibile_fiscale", "imposta_lorda", "trattenute", "competenze"],
    "tfr": ["accantonato_ap", "fondo_ap", "accantonato_ac", "fondo_ac", "anticipazioni_ac", "tesoreria_ac"],
    "irpef": ["imposta_lorda", "detr_lavoro_dipendente", "detr_coniuge", "detr_figli", "detr_altri_familiari",
              "ulteriori_detrazioni", "totale_detrazioni", "imposta_netta"],
    "annuo": ["retribuzione_utile_tfr", "ctr_azienda_fondo", "tfr_fondo", "imponibile_fiscale", "imposta_lorda",
              "detrazioni_effettive", "imposta_dovuta", "imposta_pagata"],
    "progr": ["imponibile_inps", "contributi_inps", "contributi_inps_mese", "conguaglio_credito",
              "conguaglio_debito", "detr_lavoro_dipendente", "detr_coniuge", "detr_figli",
              "detr_altri_familiari", "detr_altre"],
    "ratei": ["maturate", "godute", "residue_ap", "residue_ap2", "saldo", "arrot_precedente"],
}


def _index(group: str, name: str) -> int:
    return _KEYS[group].index(name)


def build(spec: Spec, path: Path) -> Path:
    c = Canvas(str(path), pagesize=(W, H))
    if spec.metadata:
        c.setKeywords(
            f"ANNO={spec.year};QTMONTH={spec.month:02d};DSMTSAL={spec.kind};COFISCD={FAKE_CF};"
            f"ANNAMESUR={FAKE_NAME};DSCOMPANY=AZIENDA DI ESEMPIO S.R.L.;DSAGRMNT=Terziario Confcommercio;"
            f"DSQUAGRMNT=Quadro;HRZ_MODEL=PAYLUL01;"
        )
    page = _Page(c)
    _header(page, spec)
    _tables(page, spec)
    if spec.two_pages:
        # Prima pagina: voci, ferie e ROL, totali vuoti. Seconda: totali.
        _summary(page, spec, with_totals=False, with_leave=True)
        c.showPage()
        page = _Page(c)
        _header(page, spec)
        _summary(page, spec, with_totals=True, with_leave=False)
    else:
        _summary(page, spec, with_totals=True, with_leave=True)
    c.showPage()
    c.save()
    return path


def normal_month() -> Spec:
    """Mese ordinario coerente: tornano tutte le quadrature e tutti i controlli con le regole 2026."""
    return Spec(
        elements={"Stipendio base": "2.000,00", "Contingenza": "500,00", "SUPERMINIMO": "300,00"},
        voci=[
            {"code": "AA245", "desc": "Retribuzione", "qty": "26,00", "unit": "107,69231", "comp": "2.800,00"},
            {"code": "B0016", "desc": "Retr.in Natura piano Auto", "fig": "150,00"},
            {"code": "TN4172", "desc": "Buoni pasto elettronici*", "qty": "20,00", "unit": "7,00000",
             "fig": "140,00"},
            {"code": "TN0211", "desc": "Addeb.multa piano Auto", "trat": "50,00"},
        ],
        contributi=[
            {"code": "005", "desc": "INPS-FPLD/IVS c/DIP", "base": "2.800,00", "rate": "9,190", "trat": "257,32"},
            {"code": "V05", "desc": "ENTE BILATERALE c/DIP", "base": "2.500,00", "rate": "0,050", "trat": "1,25"},
        ],
        deducibili=[{"code": "F00065", "desc": "FONDO PENSIONE", "ded": "60,00"}],
        addizionali=[
            {"code": "001", "desc": "Addizionale regionale", "year": 2025, "base": "40,00", "fig": "320,00",
             "trat": "40,00", "note": "REGIONE DI ESEMPIO"},
        ],
        summary={
            "totali.imponibile_fiscale": "2.545,18",
            "totali.imposta_lorda": "606,58",
            "totali.trattenute": "893,15",
            "totali.competenze": "2.800,00",
            "totali.netto": "1.906,85",
            "tfr.accantonato_ap": "1.000,00",
            "tfr.fondo_ap": "3207.4",
            "irpef.imposta_lorda": "606,58",
            "irpef.detr_lavoro_dipendente": "62,00",
            "irpef.totale_detrazioni": "62,00",
            "irpef.imposta_netta": "544,58",
            "progr.imponibile_inps": "8.400,00",
            # Scelto perché la stima del gestionale dia la detrazione stampata: 13.594,64 + 2.545,18 × 11
            # mensilità ancora da pagare = 41.591,62 €, detrazione annua 730,00 €, × 31 / 365 = 62,00 €.
            "annuo.imponibile_fiscale": "13.594,64",
            "annuo.detrazioni_effettive": "186,00",
        },
        leave={"FERIE": {"maturate": "2,17", "godute": "1,00", "residue_ap": "3,00", "saldo": "4,17"},
               "R.O.L.": {"maturate": "2,67", "residue_ap": "10,00", "saldo": "12,67"}},
    )


def december_with_conguaglio() -> Spec:
    """Dicembre: bonus, rimborso contributivo in colonna competenze e conguaglio IRPEF a debito."""
    s = normal_month()
    s.month = 12
    s.voci = [
        {"code": "AA245", "desc": "Retribuzione", "qty": "26,00", "unit": "107,69231", "comp": "2.800,00"},
        {"code": "I3036", "desc": "STI Bonus", "comp": "1.000,00"},
    ]
    s.contributi = [
        {"code": "005", "desc": "INPS-FPLD/IVS c/DIP", "base": "3.800,00", "rate": "9,190", "trat": "349,22"},
        {"code": "006CNG", "desc": "INPS-IVS Aggiuntivo c/DIP", "year": 2026, "base": "-2.000,00",
         "comp": "20,00"},
    ]
    s.addizionali = []
    s.summary = {
        "totali.imponibile_fiscale": "3.470,78",
        "totali.imposta_lorda": "912,02",
        "totali.trattenute": "1.391,24",
        "totali.competenze": "3.800,00",
        "totali.netto": "2.408,76",
        "irpef.imposta_lorda": "912,02",
        "irpef.imposta_netta": "912,02",
        "annuo.imponibile_fiscale": "40.000,00",
        "annuo.imposta_lorda": "10.400,00",
        "annuo.detrazioni_effettive": "868,18",
        "annuo.imposta_dovuta": "9.531,82",
        "annuo.imposta_pagata": "9.381,82",
        "progr.conguaglio_debito": "150,00",
    }
    return s
