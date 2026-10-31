"""Prova di regressione: confronta la lettura di oggi con un'istantanea salvata in precedenza.

Serve in sviluppo, prima di ogni rilascio: si rileggono i cedolini veri e si vede subito se una
modifica al codice ha cambiato un totale, l'esito di un controllo o il numero di voci sconosciute.
L'istantanea contiene importi reali, quindi va tenuta in data/, fuori dal repository.
"""

from pathlib import Path

from bp.knowledge import glossary
from bp.models import Payslip

TOTALS = ("totali.competenze", "totali.trattenute", "totali.netto", "totali.imponibile_fiscale", "irpef.imposta_netta")


def snapshot(p: Payslip, name: str) -> dict:
    g = glossary(p.parser)
    return {
        "file": name,
        "periodo": f"{p.period.year}-{p.period.month:02d} {p.period.kind}",
        "parser": p.parser,
        "quadra": p.extraction_ok,
        "totali": {k: str(p.summary[k]) for k in TOTALS if p.summary.get(k) is not None},
        "voci": len(p.lines),
        "voci_sconosciute": sorted({l.code for l in p.lines if not g.known(l)}),
        "controlli": {c.check_id: str(c.status) for c in p.coherence},
    }


def compare(old: dict[str, dict], new: dict[str, dict]) -> list[str]:
    """Le differenze tra due istantanee, una riga per cambiamento. Lista vuota: nessuna regressione."""
    out = []
    for sha in sorted(old.keys() | new.keys(), key=lambda s: (new.get(s) or old[s])["periodo"]):
        a, b = old.get(sha), new.get(sha)
        if a is None:
            out.append(f"+ {b['periodo']} ({b['file']}): cedolino nuovo, non era nell'istantanea")
            continue
        if b is None:
            out.append(f"- {a['periodo']} ({a['file']}): era nell'istantanea, ora manca o non si legge")
            continue
        for key in ("periodo", "parser", "quadra", "voci", "voci_sconosciute"):
            if a[key] != b[key]:
                out.append(f"~ {b['periodo']} ({b['file']}): {key} {a[key]} → {b[key]}")
        for group in ("totali", "controlli"):
            for k in sorted(a[group].keys() | b[group].keys()):
                if a[group].get(k) != b[group].get(k):
                    out.append(f"~ {b['periodo']} ({b['file']}): {k} {a[group].get(k, '—')} → {b[group].get(k, '—')}")
    return out


def collect(paths: list[Path]) -> list[Path]:
    """I PDF indicati, cercando anche nelle sottocartelle di quelle passate."""
    out = []
    for p in paths:
        out.extend(sorted(p.rglob("*.pdf")) if p.is_dir() else [p])
    return out
