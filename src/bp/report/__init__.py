"""Report HTML del cedolino e dello storico: file autonomi, senza risorse esterne."""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from jinja2 import Environment, PackageLoader, select_autoescape

from bp import __version__, contribute, history
from bp.knowledge import glossary
from bp.models import CheckStatus, Line, Payslip, Section
from bp.rules import DAYS_IN_YEAR, monthly_deduction

ZERO = Decimal("0")
MONTHS = ("gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre").split()
KINDS = {"Mensilita'normale": "Mensilità ordinaria", "Tredicesima": "Tredicesima", "Quattordicesima": "Quattordicesima"}
# Mensilità aggiuntive: suffisso nell'URL ed etichetta breve nel grafico dello storico.
EXTRA = {history.TREDICESIMA: ("-13", "13ª"), history.QUATTORDICESIMA: ("-14", "14ª")}
SECTION_TITLES = {
    Section.VOCI: "Voci del mese",
    Section.CONTRIBUTI: "Contributi a carico del dipendente",
    Section.DEDUCIBILI: "Contributi deducibili (informativi)",
    Section.IMPOSTA: "Imposta",
    Section.ADDIZIONALI: "Addizionali IRPEF",
}
# Icona, etichetta, classe CSS, etichetta al plurale per il riepilogo.
STATUS = {
    CheckStatus.OK: ("✅", "coerente", "ok", "coerenti"),
    CheckStatus.EXPLAINED: ("⚠️", "differenza spiegabile", "warn", "con differenza spiegabile"),
    CheckStatus.ANOMALOUS: ("❌", "differenza non spiegata", "bad", "con differenza non spiegata"),
    CheckStatus.FAILED: ("❌", "non quadra", "bad", "non quadrano"),
    CheckStatus.NOT_VERIFIABLE: ("❔", "non verificabile", "muted", "non verificabili"),
}


def euro(d: Decimal | None, sign: bool = False) -> str:
    if d is None:
        return ""
    s = f"{abs(d):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if d < 0:
        return f"−{s}"
    return f"+{s}" if sign else s


def number(d: Decimal | None) -> str:
    if d is None:
        return ""
    s = f"{d.normalize():f}" if d == d.to_integral() else f"{d}"
    return s.replace(".", ",")


def percent(d: Decimal | None) -> str:
    """Percentuale con un decimale, alla italiana: 42,3%."""
    if d is None:
        return ""
    return f"{d:.1f}%".replace(".", ",")


def share(part: Decimal | None, whole: Decimal | None) -> Decimal | None:
    """Quanto pesa `part` su `whole`, in percentuale; None se non calcolabile."""
    if part is None or not whole:
        return None
    return abs(part) / whole * 100


def rispetto_a(label: str) -> str:
    """La preposizione davanti al nome di un mese: "a marzo", "ad agosto", "alla tredicesima"."""
    low = label.lower()
    if low.startswith(("tredicesima", "quattordicesima")):
        return f"alla {low}"
    if low.startswith("cedolino"):
        return f"al {low}"
    return f"{'ad' if low.startswith('a') else 'a'} {low}"


@dataclass
class Step:
    label: str
    amount: Decimal
    note: str = ""


def _sum(values) -> Decimal:
    return sum((v for v in values if v is not None), ZERO)


def waterfall(p: Payslip) -> list[Step]:
    """Dal totale competenze al netto, per gruppi di trattenute."""
    g = glossary(p.parser)
    contrib = [l for l in p.lines if l.section == Section.CONTRIBUTI]
    inps = _sum(l.deduction for l in contrib if g.get(l).has("contributo_inps")) \
        - _sum(l.earning for l in contrib if g.get(l).has("contributo_inps"))
    other_contrib = _sum(l.deduction for l in contrib if not g.get(l).has("contributo_inps"))
    s = p.summary
    irpef = (s.get("irpef.imposta_netta", ZERO) + s.get("progr.conguaglio_debito", ZERO)
             - s.get("progr.conguaglio_credito", ZERO)
             + _sum(l.deduction for l in p.lines if l.section == Section.IMPOSTA))
    addizionali = _sum(l.deduction for l in p.lines if l.section == Section.ADDIZIONALI)
    other = _sum(l.deduction for l in p.lines if l.section == Section.VOCI)
    steps = [Step("Competenze", s.get("totali.competenze", ZERO), "retribuzione e altri importi pagati")]
    for label, amount, note in (
        ("Contributi INPS", inps, "pensione, cassa integrazione, fondo di integrazione"),
        ("Previdenza e assistenza", other_contrib, "fondo pensione, cassa sanitaria, enti bilaterali"),
        ("IRPEF", irpef, "imposta del mese, più l'eventuale conguaglio"),
        ("Addizionali", addizionali, "regionale e comunale"),
        ("Altre trattenute", other, "assenze, addebiti, sospesi"),
    ):
        if amount:
            steps.append(Step(label, -amount, note))
    steps.append(Step("Netto", s.get("totali.netto", ZERO), "accreditato in banca"))
    return steps


def _row(line: Line, g) -> dict:
    e = g.get(line)
    amounts = [
        ("competenza", line.earning),
        ("trattenuta", line.deduction),
        ("figurativo", line.figurative),
        ("deducibile", line.deductible),
    ]
    kind, amount = next(((k, a) for k, a in amounts if a is not None), ("", None))
    if line.section == Section.CONTRIBUTI and line.earning is not None:
        kind = "rimborso"
    details = []
    if line.qty is not None:
        details.append(f"quantità {number(line.qty)}")
    if line.unit_amount is not None:
        details.append(f"unitario {number(line.unit_amount)}")
    if line.base is not None:
        details.append(f"{'rata' if line.section == Section.ADDIZIONALI else 'imponibile'} {euro(line.base)}")
    if line.rate is not None:
        details.append(f"aliquota {number(line.rate)}%")
    if line.year is not None:
        details.append(f"anno {line.year}")
    if line.section == Section.ADDIZIONALI and line.figurative is not None:
        amount, kind = line.deduction, "trattenuta"
        details.append(f"residuo {euro(line.figurative)}")
    return {
        "code": line.code, "printed": line.description, "note": line.note, "name": e.nome,
        "explain": e.spiega, "known": g.known(line), "kind": kind, "amount": amount,
        "details": ", ".join(details),
    }


def context(p: Payslip) -> dict:
    g = glossary(p.parser)
    sections = []
    for section, title in SECTION_TITLES.items():
        rows = [_row(l, g) for l in p.lines if l.section == section]
        if rows:
            sections.append({"title": title, "rows": rows})
    highlights = [_row(l, g) for l in p.lines if g.get(l).has("evidenzia")]
    checks = [{"c": c, "icon": STATUS[c.status][0], "label": STATUS[c.status][1], "cls": STATUS[c.status][2],
               "diff": c.actual - c.expected if c.expected is not None and c.actual is not None else None}
              for c in p.coherence]
    counts = {}
    for status, (_, singular, _, plural) in STATUS.items():
        n = sum(1 for c in p.coherence if c.status == status)
        if n:
            counts[singular if n == 1 else plural] = n
    steps = waterfall(p)
    scale = max((abs(s.amount) for s in steps), default=Decimal(1)) or Decimal(1)
    s = p.summary
    gross = s.get("totali.competenze")
    return {
        "p": p,
        "title": f"{MONTHS[p.period.month - 1].capitalize()} {p.period.year}",
        "kind": KINDS.get(p.period.kind, p.period.kind),
        "tiles": [
            ("Competenze", gross, "il lordo del mese"),
            ("Trattenute", s.get("totali.trattenute"), f"{percent(share(s.get('totali.trattenute'), gross))} del lordo"),
            ("Netto", s.get("totali.netto"), f"{percent(share(s.get('totali.netto'), gross))} del lordo"),
        ],
        "facts": [
            ("Imponibile fiscale", s.get("totali.imponibile_fiscale")),
            ("IRPEF lorda", s.get("irpef.imposta_lorda")),
            ("Detrazioni", s.get("irpef.totale_detrazioni")),
            ("IRPEF netta", s.get("irpef.imposta_netta")),
            ("Conguaglio IRPEF a debito", s.get("progr.conguaglio_debito")),
            ("Conguaglio IRPEF a credito", s.get("progr.conguaglio_credito")),
        ],
        "tfr": [
            ("TFR maturato nell'anno", s.get("tfr.accantonato_ac")),
            ("di cui al fondo pensione", s.get("tfr.fondo_ac")),
            ("TFR in azienda al 31/12 dell'anno precedente", s.get("tfr.accantonato_ap")),
        ],
        "steps": [{"s": st, "pct": float(abs(st.amount) / scale * 100), "of_gross": share(st.amount, gross)}
                  for st in steps],
        "sections": sections,
        "highlights": highlights,
        "deduction": monthly_deduction(p),
        "days_in_year": DAYS_IN_YEAR,
        "checks": checks,
        "to_review": [row for row in checks if row["c"].status == CheckStatus.ANOMALOUS],
        "counts": counts,
        "extraction_ok": p.extraction_ok,
        "today": date.today().strftime("%d/%m/%Y"),
    }


_env = Environment(loader=PackageLoader("bp.report", "templates"), autoescape=select_autoescape())
_env.globals["version"] = __version__
_env.filters["euro"] = euro
_env.filters["number"] = number
_env.filters["percent"] = percent
_env.filters["rispetto_a"] = rispetto_a


def render(p: Payslip) -> str:
    return _env.get_template("mese.html").render(m=context(p))


SHORT_MONTHS = [m[:3] for m in MONTHS]


def month_id(p: Payslip) -> str:
    """Identificativo stabile nell'URL: 2025-12, 2025-12-13 per la tredicesima, 2023-04-agg per un
    cedolino aggiuntivo."""
    kind = p.period.kind
    suffix = "" if kind == history.NORMALE else EXTRA.get(kind, ("-agg",))[0]
    return f"{p.period.year}-{p.period.month:02d}{suffix}"


def month_label(p: Payslip) -> str:
    kind = p.period.kind
    if kind in EXTRA:
        return f"{kind} {p.period.year}"
    month = f"{MONTHS[p.period.month - 1]} {p.period.year}"
    if kind != history.NORMALE:
        return f"Cedolino aggiuntivo di {month}"
    return month.capitalize()


def _ticks(top: Decimal) -> tuple[Decimal, list[Decimal]]:
    """Scala dell'asse: un passo tondo e un massimo che sia un suo multiplo."""
    for step in (Decimal(n) for n in (100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000)):
        if top / step <= 5:
            break
    n = max(math.ceil(top / step), 1)  # con Decimal, -(-a // b) tronca invece di arrotondare per eccesso
    return step * n, [step * i for i in range(n + 1)]


def names(ps: list[Payslip]) -> dict[str, tuple[str, str]]:
    """Identificativo e etichetta di ogni cedolino, per hash del file. Se nello stesso mese ci sono
    cedolini dello stesso tipo di aziende diverse (cambio di lavoro), si distinguono con l'azienda."""
    by_id: dict[str, list[Payslip]] = {}
    for p in ps:
        by_id.setdefault(month_id(p), []).append(p)
    out = {}
    for base, group in by_id.items():
        for n, p in enumerate(group):
            if len(group) == 1:
                out[p.file_sha256] = (base, month_label(p))
                continue
            employer = p.contract.employer or f"cedolino {n + 1}"
            slug = "".join(c for c in employer.lower() if c.isalnum())[:12] or str(n + 1)
            out[p.file_sha256] = (f"{base}-{slug}", f"{month_label(p)} · {employer}")
    return out


def _comparison(before: Payslip | None, after: Payslip, ids: dict[str, tuple[str, str]]) -> dict | None:
    if before is None:
        return None
    fringe_before, fringe_after = history.taxed_fringe(before), history.taxed_fringe(after)
    return {
        "label": ids[before.file_sha256][1],
        "id": ids[before.file_sha256][0],
        "delta": after.summary.get("totali.netto", ZERO) - before.summary.get("totali.netto", ZERO),
        "changes": history.changes(before, after),
        "fringe": (fringe_before, fringe_after) if fringe_before != fringe_after else None,
    }


def deduction_years(ps: list[Payslip], ids: dict[str, tuple[str, str]] | None = None) -> list[dict]:
    """Le detrazioni per lavoro dipendente mese per mese, raggruppate per anno, con l'esito del conguaglio.

    Ogni datore di lavoro calcola le detrazioni per conto suo: in un anno con un cambio di lavoro
    ogni azienda ha il suo gruppo."""
    ids = ids or names(ps)
    employers: dict[int, set] = {}
    for p in ps:
        employers.setdefault(p.period.year, set()).add(p.contract.employer)
    years: dict[tuple, dict] = {}
    for p in ps:
        d = monthly_deduction(p)
        if d is None:
            continue
        several = len(employers[p.period.year]) > 1
        title = f"{p.period.year} · {p.contract.employer}" if several and p.contract.employer else str(p.period.year)
        y = years.setdefault((p.period.year, p.contract.employer), {
            "year": p.period.year, "title": title, "several_employers": several,
            "rows": [], "final": None, "received": None})
        received_before = y["rows"][-1]["d"].year_to_date if y["rows"] else ZERO
        y["rows"].append({"id": ids[p.file_sha256][0], "label": ids[p.file_sha256][1], "d": d})
        if p.summary.get("annuo.imposta_dovuta") is not None:
            # A dicembre il progressivo diventa la detrazione definitiva dell'anno: quanto si era
            # ricevuto è il progressivo di novembre più la quota di dicembre.
            y["received"] = (received_before or ZERO) + d.printed
            y["final"] = d.year_to_date
    out = []
    for y in years.values():
        last = y["rows"][-1]["d"]
        y["max"] = max((r["d"].printed for r in y["rows"]), default=ZERO) or Decimal(1)
        y["returned"] = y["received"] - y["final"] if y["final"] is not None else None
        y["last"] = last
        y["last_label"] = y["rows"][-1]["label"]
        y["over_limit"] = y["final"] is None and last.annual == 0
        out.append(y)
    return out


def _short(p: Payslip) -> str:
    if p.period.kind in EXTRA:
        return EXTRA[p.period.kind][1]
    month = SHORT_MONTHS[p.period.month - 1]
    return month if p.period.kind == history.NORMALE else f"{month}+"


def history_context(payslips: list[Payslip]) -> dict:
    ps = history.ordered(payslips)
    ids = names(ps)
    months = []
    for i, p in enumerate(ps):
        s = p.summary
        net, gross = s.get("totali.netto", ZERO), s.get("totali.competenze", ZERO)
        months.append({
            "id": ids[p.file_sha256][0],
            "label": ids[p.file_sha256][1],
            "short": _short(p),
            "year_start": i == 0 or ps[i - 1].period.year != p.period.year,
            "year": p.period.year,
            "net": net,
            "gross": gross,
            "deductions": s.get("totali.trattenute", ZERO),
            "rate": share(s.get("totali.trattenute", ZERO), gross),
            "ok": p.extraction_ok,
            "m": context(p),
            "vs": _comparison(history.previous(ps, i), p, ids),
        })
    top, ticks = _ticks(max((m["net"] + m["deductions"] for m in months), default=Decimal(1000)))
    for m in months:
        m["h_net"] = float(m["net"] / top * 100)
        m["h_ded"] = float(m["deductions"] / top * 100)
    total_gross = sum((m["gross"] for m in months), ZERO)
    total_ded = sum((m["deductions"] for m in months), ZERO)
    # Riepilogo di ogni anno, per il filtro per anno della pagina.
    years = []
    for y in sorted({m["year"] for m in months}):
        ms = [m for m in months if m["year"] == y]
        gross, ded = sum((m["gross"] for m in ms), ZERO), sum((m["deductions"] for m in ms), ZERO)
        years.append({"year": y, "count": len(ms), "first": ms[0]["label"], "last": ms[-1]["label"],
                      "gross": gross, "deductions": ded, "rate": share(ded, gross)})
    return {
        "years": years,
        "months": months,
        "total_gross": total_gross,
        "total_deductions": total_ded,
        "total_rate": share(total_ded, total_gross),
        "deduction_years": deduction_years(ps, ids),
        "ticks": [{"value": t, "pct": float(t / top * 100)} for t in ticks],
        "first": months[0]["label"] if months else "",
        "last": months[-1]["label"] if months else "",
        "today": date.today().strftime("%d/%m/%Y"),
        "parsers": sorted({f"{p.parser} {p.parser_version}" for p in ps}),
        # Solo ciò che serve al tooltip e alla navigazione, con i numeri come float per JavaScript.
        "months_js": [{"id": m["id"], "label": m["label"], "year": m["year"], "net": float(m["net"]), "gross": float(m["gross"]),
                       "deductions": float(m["deductions"]),
                       "rate": percent(m["rate"])} for m in months],
    }


def render_history(payslips: list[Payslip]) -> str:
    return _env.get_template("storico.html").render(**history_context(payslips))


def render_archive(payslips: list[Payslip], data_dir: str, unreadable: dict[str, str] | None = None) -> str:
    """La pagina principale dell'app locale: zona di caricamento ed elenco dei cedolini in archivio."""
    rows = []
    ps = history.ordered(payslips)
    ids = names(ps)
    for p in reversed(ps):
        s = p.summary
        rows.append({
            "sha": p.file_sha256,
            "label": ids[p.file_sha256][1],
            "net": s.get("totali.netto", ZERO),
            "gross": s.get("totali.competenze", ZERO),
            "ok": p.extraction_ok,
            "anomalies": sum(c.status == CheckStatus.ANOMALOUS for c in p.coherence),
        })
    return _env.get_template("app.html").render(rows=rows, data_dir=data_dir, unreadable=unreadable or {},
                                                donate=contribute.donate_url())
