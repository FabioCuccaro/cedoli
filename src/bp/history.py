"""Storico: ordina i cedolini e spiega la differenza di netto tra un mese e il precedente."""

from dataclasses import dataclass
from decimal import Decimal

from bp.knowledge import glossary
from bp.models import Line, Payslip, Section

ZERO = Decimal("0")
NORMALE = "Mensilita'normale"
TREDICESIMA = "Tredicesima"
QUATTORDICESIMA = "Quattordicesima"


@dataclass
class Change:
    label: str
    before: Decimal
    after: Decimal
    note: str = ""

    @property
    def effect(self) -> Decimal:
        return self.after - self.before


def sort_key(p: Payslip) -> tuple[int, int, int, str]:
    # Nello stesso mese la mensilità ordinaria viene prima delle mensilità aggiuntive e dei
    # cedolini aggiuntivi (premi pagati a parte).
    order = {NORMALE: 0, TREDICESIMA: 1, QUATTORDICESIMA: 1}.get(p.period.kind, 2)
    return (p.period.year, p.period.month, order, p.period.kind)


def ordered(payslips: list[Payslip]) -> list[Payslip]:
    """Ordina per periodo ed elimina i doppioni dello stesso file."""
    seen, out = set(), []
    for p in sorted(payslips, key=sort_key):
        if p.file_sha256 not in seen:
            seen.add(p.file_sha256)
            out.append(p)
    return out


def previous(payslips: list[Payslip], index: int) -> Payslip | None:
    """Il cedolino con cui confrontare: lo stesso tipo di mensilità della stessa azienda, il più
    recente prima di questo. Dopo un cambio di lavoro il primo cedolino non ha un precedente."""
    current = payslips[index]
    for p in reversed(payslips[:index]):
        if p.period.kind == current.period.kind and p.contract.employer == current.contract.employer:
            return p
    return None


def _net_effects(p: Payslip) -> dict[tuple[str, str], tuple[str, Decimal]]:
    """Effetto sul netto di ogni componente del cedolino: positivo se lo aumenta.

    La somma degli effetti è il netto, quando la quadratura dell'estrazione è riuscita.
    """
    g = glossary(p.parser)
    effects: dict[tuple[str, str], tuple[str, Decimal]] = {}

    def add(key, label, amount):
        prev = effects.get(key, (label, ZERO))[1]
        effects[key] = (label, prev + amount)

    for line in p.lines:
        amount = (line.earning or ZERO) - (line.deduction or ZERO)
        if amount:
            label = g.get(line).nome if g.known(line) else line.description
            if line.section == Section.ADDIZIONALI and line.year:
                label = f"{label} {line.year}"
            add(_key(line), label, amount)
    s = p.summary
    add(("irpef", "netta"), "IRPEF del mese", -s.get("irpef.imposta_netta", ZERO))
    conguaglio = s.get("progr.conguaglio_credito", ZERO) - s.get("progr.conguaglio_debito", ZERO)
    if conguaglio:
        add(("irpef", "conguaglio"), "Conguaglio IRPEF", conguaglio)
    return effects


def _key(line: Line) -> tuple[str, str]:
    # Le addizionali dello stesso codice di anni diversi (saldo e acconto) restano separate.
    year = f"/{line.year}" if line.section == Section.ADDIZIONALI and line.year else ""
    return (line.section.value, line.code + year)


def changes(before: Payslip, after: Payslip, limit: int = 8, minor: Decimal = Decimal("1")) -> list[Change]:
    """Le componenti che spiegano la differenza di netto, dalla più rilevante.

    Oltre le prime `limit`, e sotto `minor` euro, le variazioni finiscono in un'unica riga.
    """
    a, b = _net_effects(before), _net_effects(after)
    out = []
    for key in a.keys() | b.keys():
        label = (b.get(key) or a.get(key))[0]
        old, new = a.get(key, ("", ZERO))[1], b.get(key, ("", ZERO))[1]
        if old != new:
            note = "" if key in a and key in b else ("nuova" if key in b else "assente questo mese")
            out.append(Change(label, old, new, note))
    out.sort(key=lambda c: abs(c.effect), reverse=True)
    keep = [c for c in out[:limit] if abs(c.effect) >= minor]
    rest = out[len(keep):]
    if rest:
        if not keep:
            label = "Variazioni minori"
        else:
            label = "Un'altra variazione minore" if len(rest) == 1 else f"Altre {len(rest)} variazioni minori"
        out = keep + [Change(label, sum((c.before for c in rest), ZERO), sum((c.after for c in rest), ZERO))]
    return out


def taxed_fringe(p: Payslip) -> Decimal:
    """Fringe benefit entrati negli imponibili: non sono pagati ma spiegano IRPEF e contributi più alti."""
    g = glossary(p.parser)
    return sum((l.figurative or ZERO for l in p.lines
                if l.section == Section.VOCI and g.get(l).has("fringe_tassato")), ZERO)
