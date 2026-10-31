"""Generatore di cedolini sintetici nel layout HR1LULDIP.

Riproduce posizioni, colonne e i due font del layout reale (dati e modulo prestampato),
con importi e anagrafica inventati.
"""

from dataclasses import dataclass, field
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from tests.synthetic import FAKE_CF, FAKE_IBAN, FAKE_NAME

W, H = 595, 842
DATA, FORM, SIZE = "Helvetica", "Times-Roman", 7


@dataclass
class Spec:
    year: int = 2024
    month: int = 3
    tipced: str = "50"
    dtipced: str = "Mensilità normale"
    voci: list[tuple] = field(default_factory=list)
    contributi: list[tuple] = field(default_factory=list)
    imposte: list[tuple] = field(default_factory=list)
    tfr: tuple[str, str, str] = ("2.550,00", "176,14", "2.550,00")
    annual: list[str] | None = None  # riquadro del conguaglio: "Annuale" e sette importi
    progr: tuple[str, str, str, str] = ("7.650,00", "7.650,00", "7.439,19", "1.631,73")
    totals: tuple[str, str, str] = ("2.728,50", "825,73", "1.902,77")
    two_pages: bool = False


class _Page:
    def __init__(self, c: Canvas):
        self.c = c

    def text(self, top: float, x0: float, s: str, font: str = DATA) -> None:
        self.c.setFont(font, SIZE)
        self.c.drawString(x0, H - top - SIZE, s)

    def right(self, top: float, x1: float, s: str, font: str = DATA) -> None:
        self.c.setFont(font, SIZE)
        self.c.drawRightString(x1, H - top - SIZE, s)


def _x1(label: str, x0: float) -> float:
    return x0 + stringWidth(label, DATA, SIZE)


def _header(p: _Page) -> None:
    # Modulo prestampato, con la "s" al posto degli spazi e una scritta verticale come nel reale.
    p.text(20, 25, "CodicesAzienda RagionesSociale", FORM)
    p.text(130, 25, "Codicesdipendente COGNOMEsEsNOME", FORM)
    p.c.saveState()
    p.c.translate(20, 300)
    p.c.rotate(90)
    p.c.setFont(FORM, 4)
    p.c.drawString(0, 0, "ELEMENTIsDELLAsRETRIBUZIONE")
    p.c.restoreState()
    p.text(32, 25, "000099 AZIENDA DI ESEMPIO SPA")
    p.text(142, 29, "0000123")
    p.text(142, 99, FAKE_NAME)
    p.text(142, 449, FAKE_CF)
    p.text(162, 168, "IMP")
    p.text(162, 259, "Livello 2")
    p.text(168, 29, "01-01-1980")
    p.text(184, 291, "Terziario EMI")
    for x0, v in ((36, "4"), (60, "26"), (107, "26"), (149, "9"), (183, "72,00"), (273, "31")):
        p.text(194, x0, v)
    for x0, label, value in ((75, "PAGA BASE", "1.500,00000"), (240, "CONTING.", "530,00000"),
                             (491, "SUP.ASS.", "370,00000")):
        p.text(208, x0, label)
        p.text(218, x0 + 30, value)
    p.text(264, 39, "12-2027")
    p.right(264, 569, "2.400,00000")


def _row(p: _Page, top: float, r: tuple) -> None:
    code_desc, cols = r[0], r[1]
    p.text(top, 25, "*")
    p.text(top, 39, code_desc)
    for key, value in cols.items():
        if key == "note":
            p.text(top, 270, value)
        elif key == "year":
            p.text(top, 210, value)
        elif key == "place":
            p.text(top, 233, value)
            p.text(top, 322, "Residuo")
        elif key == "fig":
            p.text(top, 502, "(")
            p.right(top, 574, value + ")")
        else:
            p.right(top, {"unit": 315, "ref": 420, "rate": 411, "res": 427, "trat": 493, "comp": 569}[key], value)


def _table(p: _Page, spec: Spec, rows: list[list[tuple]]) -> None:
    top = 291
    for block in rows:
        for r in block:
            _row(p, top, r)
            top += 10
        top += 10  # riga vuota tra i blocchi
    for label, value in zip(("Retribuzione utile T.F.R.", "Quota T.F.R.", "Imp. INAIL"), spec.tfr):
        p.text(top, 69, label)
        p.right(top, 314, value)
        top += 10


def _boxes(p: _Page, spec: Spec) -> None:
    if spec.annual:
        labels = [("OneriDed", 95), ("Imponibile", 156), ("IRPEF lorda", 215), ("Detrazioni", 286),
                  ("IRPEF trattenuta", 327), ("Add.regionale", 404), ("Add.comunale", 466)]
        for label, x0 in labels:
            p.text(615, x0, label)
        p.text(626, 30, spec.annual[0])
        for (label, x0), value in zip(labels, spec.annual[1:]):
            p.right(626, _x1(label, x0), value)
    groups = [
        (650, 663, [("Imp. INPS", 92), ("Imp. INAIL", 165), ("Imp. IRPEF", 240), ("IRPEF pagata", 308)], spec.progr),
        (675, 687, [("F.do 31/12", 67), ("Rivalutaz.", 166), ("Imp.rival.", 253), ("Quota anno", 341),
                    ("TFR a fondi", 408), ("Anticipi", 547)],
         ("12.000,00", "150,00", "25,50", "528,42")),
    ]
    for top, value_top, labels, values in groups:
        for label, x0 in labels:
            p.text(top, x0, label)
        for (label, x0), value in zip(labels, values):
            p.right(value_top, _x1(label, x0), value)
    p.text(700, 470, "TOTALEsCOMPETENZE", FORM)
    p.right(700, 578, spec.totals[0])
    for label, x0 in (("Residuo AP", 122), ("Maturato", 188), ("Goduto", 252), ("Saldo", 317)):
        p.text(705, x0, label)
    p.text(713, 470, "TOTALEsTRATTENUTE", FORM)
    p.right(713, 578, spec.totals[1])
    for top, label, values in ((715, "Ferie", ("10,00000", "43,33333", "8,00000", "45,33333")),
                               (726, "Permessi", ("5,00000", "26,00000", "4,00000", "27,00000"))):
        p.text(top + 1, 30, label)
        for x0, v in zip((122, 188, 252, 317), values):
            p.text(top, x0, v)
        p.text(top, 374, "ORE")
    p.text(742, 510, spec.totals[2] + "€")
    p.text(791, 424, "C/C")
    p.text(791, 445, FAKE_IBAN)


def build(spec: Spec, path: Path) -> Path:
    c = Canvas(str(path), pagesize=(W, H))
    c.setKeywords(
        f"HRZ_MODEL=HR1LULDIP;IDCOMPANY=000099;DENAZI=AZIENDA DI ESEMPIO SPA;ANNO={spec.year};"
        f"MESE={spec.month:02d};TIPCED={spec.tipced};DTIPCED={spec.dtipced};CONODIP={FAKE_NAME};"
        f"COFISCD={FAKE_CF};DTIPELEM=Libro unico;IMPNETTO={spec.totals[2]}")
    p = _Page(c)
    _header(p)
    blocks = [spec.voci, spec.contributi, spec.imposte]
    if spec.two_pages:
        # Le righe di imposta continuano sulla seconda pagina, che ripete l'intestazione.
        _table(p, spec, blocks[:2])
        c.showPage()
        p = _Page(c)
        _header(p)
        top = 291
        for r in spec.imposte:
            _row(p, top, r)
            top += 10
        p.text(top + 10, 69, "Retribuzione utile T.F.R.")
        p.right(top + 10, 314, spec.tfr[0])
        p.text(top + 20, 69, "Quota T.F.R.")
        p.right(top + 20, 314, spec.tfr[1])
    else:
        _table(p, spec, blocks)
    _boxes(p, spec)
    c.showPage()
    c.save()
    return path


def normal_month() -> Spec:
    """Marzo 2024: retribuzione, indennità, buoni pasto, esonero contributivo, un'addizionale."""
    return Spec(
        voci=[
            ("Z00001Retribuzione", {"unit": "14,28571", "ref": "168,00000ORE", "comp": "2.400,00"}),
            ("000541 Inden. no limite orario", {"comp": "150,00"}),
            ("004574 Ticket Mensa Elettronico", {"unit": "8,00000", "ref": "20,00000GG", "fig": "160,00"}),
        ],
        contributi=[
            ("Z31000Contributo Fondo EST", {"trat": "2,00"}),
            ("Z31000Contributo Fondo EST", {"note": "C/Ditta", "fig": "10,00"}),
            ("Z00000Contributo IVS", {"unit": "2.550,00", "rate": "9,19000%", "trat": "234,35"}),
            ("Z00055FIS D.Lgs.148/2015 oltre 15dip", {"unit": "2.550,00", "rate": "0,26667%", "trat": "6,80"}),
            ("Z00087Contributo CIGS", {"unit": "2.550,00", "rate": "0,30000%", "trat": "7,65"}),
            ("Z00346Esonero IVS L. 197/2022", {"unit": "2.550,00", "rate": "7,00000%", "comp": "178,50"}),
            ("003041 Ente Bilaterale Commercio", {"unit": "2.030,00", "rate": "0,05000%", "trat": "1,02"}),
            ("003041 Ente Bilaterale Commercio", {"note": "C/Ditta", "rate": "0,10000%", "fig": "2,03"}),
        ],
        imposte=[
            ("F02000Imponibile IRPEF", {"unit": "2.479,73"}),
            ("F02010IRPEF lorda", {"unit": "643,91"}),
            ("F02500Detrazioni lav.dip.", {"unit": "100,00"}),
            ("F03020Ritenute IRPEF", {"trat": "543,91"}),
            ("F09110Addizionale regionale", {"year": "2023", "place": "REGIONE ESEMPIO", "res": "300,00",
                                             "trat": "30,00"}),
        ],
    )
