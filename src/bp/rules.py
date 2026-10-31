"""Controlli di coerenza: ricalcolano i valori del cedolino a partire dalle regole dell'anno.

Sono funzioni pure su un Payslip già estratto e quadrato. Ogni controllo restituisce un
CheckResult con la formula usata, il valore stampato e quello ricalcolato.
"""

import calendar
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from bp.knowledge import DEFAULT_EXTRA_MONTHS, Glossary, contract, glossary, rules
from bp.models import CheckResult, CheckStatus, Line, Payslip, Section

ZERO = Decimal("0")
CENT = Decimal("0.01")
# Il gestionale arrotonda passaggi intermedi: tolleranze per tipo di calcolo.
TOL_EXACT = Decimal("0.01")
TOL_TAX = Decimal("0.05")
TOL_TFR = Decimal("0.02")


def _money(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def _euro(d: Decimal) -> Decimal:
    return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _sum(values) -> Decimal:
    return sum((v for v in values if v is not None), ZERO)


def _fmt(d: Decimal | None) -> str:
    if d is None:
        return "—"
    s = f"{d:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _compare(check_id, title, formula, printed, computed, tol, detail=None) -> CheckResult:
    if printed is None or computed is None:
        return CheckResult(check_id=check_id, status=CheckStatus.NOT_VERIFIABLE, title=title,
                           formula=formula, expected=printed, actual=computed, detail=detail)
    ok = abs(printed - computed) <= tol
    if not ok:
        diff = f"Differenza di {_fmt(printed - computed)} € tra il valore stampato e quello ricalcolato."
        detail = f"{detail} {diff}" if detail else diff
    return CheckResult(check_id=check_id, status=CheckStatus.OK if ok else CheckStatus.ANOMALOUS,
                       title=title, formula=formula, expected=printed, actual=_money(computed), detail=detail)


def irpef_gross(income: Decimal, brackets: list[dict], divisor: int = 1) -> Decimal:
    """Imposta lorda per scaglioni; divisor=12 applica gli scaglioni mensilizzati."""
    tax, lower = ZERO, ZERO
    for b in brackets:
        upper = None if b["fino_a"] is None else b["fino_a"] / divisor
        taxable = (income if upper is None else min(income, upper)) - lower
        if taxable <= 0:
            break
        tax += taxable * b["aliquota"] / 100
        if upper is None:
            break
        lower = upper
    return tax


def employee_deduction(income: Decimal, bands: list[dict], extra: dict | None = None) -> Decimal:
    """Detrazione annua per lavoro dipendente per reddito complessivo `income`.

    `extra` è l'eventuale maggiorazione fissa per una fascia di reddito (65 € tra 25.000 e
    35.000 € fino al 2024)."""
    bonus = extra["importo"] if extra and extra["oltre"] < income <= extra["fino_a"] else ZERO
    for b in bands:
        if b["fino_a"] is None or income <= b["fino_a"]:
            variable = ZERO
            if b["variabile"]:
                variable = b["variabile"] * (b["limite"] - income) / b["ampiezza"]
            return max(ZERO, b["fisso"] + variable) + bonus
    return ZERO


class _Context:
    def __init__(self, p: Payslip, g: Glossary):
        self.p, self.g = p, g

    def lines(self, section: Section | None = None, flag: str | None = None) -> list[Line]:
        return [l for l in self.p.lines
                if (section is None or l.section == section) and (flag is None or self.g.get(l).has(flag))]

    def flagged(self, flag: str, section: Section = Section.CONTRIBUTI) -> Line | None:
        """La prima riga della sezione con l'indicatore del glossario, per esempio il contributo IVS."""
        return next(iter(self.lines(section, flag)), None)

    def taxable_pay(self) -> Decimal:
        """Retribuzione imponibile prima dell'arrotondamento all'euro."""
        voci = self.lines(Section.VOCI)
        return (
            _sum(l.earning for l in voci if not self.g.get(l).has("escluso_imponibili"))
            - _sum(l.deduction for l in voci if self.g.get(l).has("riduce_imponibili"))
            + _sum(l.figurative for l in voci if self.g.get(l).has("fringe_tassato"))
        )


def _inps(ctx: _Context, r: dict | None) -> list[CheckResult]:
    out = []
    rates = r["inps"]["aliquote_dipendente"] if r else {}
    for l in ctx.lines(Section.CONTRIBUTI, "contributo_inps"):
        if l.base is None or l.rate is None or l.deduction is None:
            continue
        rate = rates.get(l.code, l.rate)
        out.append(_compare(
            f"inps_{l.code}", ctx.g.get(l).nome,
            f"imponibile {_fmt(l.base)} × {rate}%", l.deduction, _money(l.base * rate / 100), TOL_EXACT,
            None if rate == l.rate else f"Aliquota effettiva {rate}%, stampata troncata a {l.rate}%."))
    return out


# Il layout HR1LULDIP arrotonda l'imponibile previdenziale sul progressivo dell'anno: il mese
# può scostarsi di un euro dall'arrotondamento del solo mese.
INPS_ROUNDING = {"hr1luldip": Decimal("1")}


def _taxable_inps(ctx: _Context) -> CheckResult | None:
    ivs = ctx.flagged("ivs")
    if ivs is None or ivs.base is None:
        return None
    tol = INPS_ROUNDING.get(ctx.p.parser, Decimal("0"))
    return _compare(
        "imponibile_inps", "Imponibile previdenziale",
        "competenze − importi non retributivi − assenze + fringe benefit tassati, arrotondato all'euro",
        ivs.base, _euro(ctx.taxable_pay()), tol,
        "L'arrotondamento all'euro è fatto sul progressivo dell'anno, quindi nel mese può spostare "
        "l'imponibile di un euro." if tol else None)


def _taxable_irpef(ctx: _Context, r: dict | None) -> CheckResult:
    printed = ctx.p.summary.get("totali.imponibile_fiscale")
    if r is None:
        return _compare("imponibile_fiscale", "Imponibile fiscale", "regole dell'anno non disponibili", printed, None, 0)
    # La quota dell'azienda all'ente bilaterale: stampata come importo figurativo dove il layout la
    # riporta (HR1LULDIP, riga C/Ditta), altrimenti ricavata dall'aliquota delle regole.
    eb_lines = ctx.lines(Section.CONTRIBUTI, "ente_bilaterale")
    printed_eb = next((l.figurative for l in eb_lines if l.figurative is not None), None)
    eb = next((l for l in eb_lines if l.base), None)
    if printed_eb is not None:
        eb_company = printed_eb
    else:
        eb_company = _money(eb.base * r["ente_bilaterale"]["aliquota_azienda"] / 100) if eb else ZERO
    inps = (_sum(l.deduction for l in ctx.lines(Section.CONTRIBUTI, "contributo_inps"))
            - _sum(l.earning for l in ctx.lines(Section.CONTRIBUTI, "contributo_inps")))
    deductible = _sum(l.deduction for l in ctx.lines(Section.CONTRIBUTI, "deducibile"))
    computed = ctx.taxable_pay() + eb_company - inps - deductible
    return _compare(
        "imponibile_fiscale", "Imponibile fiscale",
        f"retribuzione imponibile + ente bilaterale c/azienda {_fmt(eb_company)} − contributi INPS {_fmt(inps)}"
        f" − contributi deducibili {_fmt(deductible)}",
        printed, computed, TOL_EXACT,
        "La quota dell'ente bilaterale a carico dell'azienda non è stampata: è ricavata dall'aliquota "
        "nelle regole e torna su tutti i cedolini analizzati.")


# Divisore degli scaglioni annui per l'IRPEF del mese. Il layout HR1LULDIP li divide per 15:
# torna su tutti i 25 cedolini 2023-2024 analizzati, mensilità aggiuntive e premi compresi.
IRPEF_MONTHLY_DIVISOR = {"hr1luldip": 15}


def _irpef(ctx: _Context, r: dict | None) -> list[CheckResult]:
    s = ctx.p.summary
    out = []
    taxable, gross = s.get("totali.imponibile_fiscale"), s.get("irpef.imposta_lorda")
    if r is None:
        out.append(_compare("irpef_lorda", "IRPEF lorda del mese",
                            f"regole {ctx.p.period.year} non disponibili", gross, None, 0))
    elif taxable is not None:
        divisor = IRPEF_MONTHLY_DIVISOR.get(ctx.p.parser, 12)
        out.append(_compare(
            "irpef_lorda", "IRPEF lorda del mese",
            f"scaglioni {ctx.p.period.year} divisi per {divisor} applicati a {_fmt(taxable)}",
            gross, irpef_gross(taxable, r["irpef"]["scaglioni"], divisor), TOL_TAX,
            f"Nel mese l'imposta si calcola sugli scaglioni annui divisi per {divisor}; il conto definitivo "
            "si fa con il conguaglio di dicembre."))
    if gross is not None:
        deductions = s.get("irpef.totale_detrazioni", ZERO)
        out.append(_compare("irpef_netta", "IRPEF netta del mese", "IRPEF lorda − totale detrazioni",
                            s.get("irpef.imposta_netta"), gross - deductions, TOL_EXACT))
    return out


def _year_end(ctx: _Context, r: dict | None) -> list[CheckResult]:
    s = ctx.p.summary
    due, income = s.get("annuo.imposta_dovuta"), s.get("annuo.imponibile_fiscale")
    # Solo nel cedolino del conguaglio: PAYLUL01 stampa l'imposta dovuta, HR1LULDIP il riquadro
    # annuale con l'IRPEF trattenuta nell'anno.
    if income is None or r is None or (due is None and "annuo.imposta_trattenuta" not in s):
        return []
    gross = irpef_gross(income, r["irpef"]["scaglioni"])
    d = r["detrazione_lavoro_dipendente"]
    deduction = employee_deduction(income, d["fasce"], d.get("maggiorazione"))
    balance = s.get("progr.conguaglio_debito", ZERO) - s.get("progr.conguaglio_credito", ZERO)
    results = [
        _compare("conguaglio_lorda", "IRPEF lorda dell'anno", f"scaglioni {ctx.p.period.year} su {_fmt(income)}",
                 s.get("annuo.imposta_lorda"), gross, TOL_TAX),
        _compare("conguaglio_detrazione", "Detrazione per lavoro dipendente dell'anno",
                 f"formula {ctx.p.period.year} su un reddito di {_fmt(income)}, per l'anno intero",
                 s.get("annuo.detrazioni_effettive"), deduction, TOL_TAX,
                 "Vale per un rapporto di lavoro durato tutto l'anno."),
    ]
    if due is not None:
        results.append(_compare("conguaglio", "Conguaglio IRPEF", "imposta dovuta − imposta già pagata (debito se positivo)",
                                balance, due - s.get("annuo.imposta_pagata", ZERO), TOL_EXACT))
    return results


def _tfr(ctx: _Context, r: dict | None) -> CheckResult | None:
    s = ctx.p.summary
    tfr = next((l.figurative for l in ctx.lines(Section.VOCI, "tfr") if l.figurative is not None),
               s.get("tfr.quota_mese"))
    # PAYLUL01 stampa la retribuzione utile dell'anno nel riquadro, HR1LULDIP quella del mese.
    pay = s.get("tfr.retribuzione_utile_mese", s.get("annuo.retribuzione_utile_tfr"))
    ivs = ctx.flagged("ivs")
    if tfr is None or pay is None or ivs is None or ivs.base is None or r is None:
        return None
    t = r["tfr"]

    def compute(base: Decimal) -> CheckResult:
        return _compare(
            "tfr", "Quota TFR del mese",
            f"retribuzione utile {_fmt(base)} / {t['divisore']} − {t['contributo_rivalsa']}% di {_fmt(ivs.base)}",
            tfr, base / t["divisore"] - ivs.base * t["contributo_rivalsa"] / 100, TOL_TFR)

    result = compute(pay)
    # A dicembre il riquadro "Retr. Utile TFR" somma anche la tredicesima, pagata con un cedolino
    # a parte: la retribuzione utile del solo cedolino è l'imponibile del fondo pensione.
    fund = next((l for l in ctx.lines(Section.CONTRIBUTI, "fondo_pensione") if l.base), None)
    if result.status != CheckStatus.OK and fund is not None:
        alt = compute(fund.base)
        if alt.status == CheckStatus.OK:
            alt.detail = (f"Il riquadro riporta una retribuzione utile di {_fmt(pay)}, che a dicembre comprende "
                          "anche la tredicesima: il calcolo usa quella del solo cedolino, uguale all'imponibile "
                          "del fondo pensione.")
            return alt
    if result.status != CheckStatus.OK and ctx.p.period.month == 12 and fund is None:
        result.status = CheckStatus.NOT_VERIFIABLE
        result.detail = (f"Il riquadro riporta una retribuzione utile di {_fmt(pay)}, che a dicembre comprende "
                         "anche la tredicesima, pagata con un cedolino a parte: senza fondo pensione la "
                         "retribuzione del solo cedolino non è stampata.")
    return result


def _leave(p: Payslip) -> list[CheckResult]:
    out = []
    for b in p.leave:
        if b.saldo is None:
            continue
        unit = b.unit or ("giorni" if b.kind == "FERIE" else "ore")
        computed = (b.residue_ap or ZERO) + (b.residue_ap2 or ZERO) + (b.maturate or ZERO) - (b.godute or ZERO)
        out.append(_compare(f"saldo_{b.kind}", f"Saldo {b.kind.lower().rstrip('.')} ({unit})",
                            "residuo anni precedenti + maturato − goduto", b.saldo, computed, TOL_TFR))
    return out


# Il gestionale stima il reddito dell'anno con l'imponibile già maturato più quello del mese
# ripetuto per le mensilità ancora da pagare. Quali mensilità aggiuntive ci sono, e in che mese,
# dipende dal contratto collettivo (knowledge/contratti). Verificato su 20 cedolini PAYLUL01 del
# 2025 e 2026 (terziario: quattordicesima a giugno, tredicesima a dicembre).
DAYS_IN_YEAR = 365


@dataclass
class MonthlyDeduction:
    """Come nasce la detrazione per lavoro dipendente del mese."""
    income_to_date: Decimal     # imponibile fiscale dell'anno fino a questo mese compreso
    month_income: Decimal       # imponibile fiscale del mese
    remaining: list[str]        # mensilità ancora da pagare, per la stima
    contract: str | None        # contratto collettivo riconosciuto, None se non è tra quelli noti
    projected: Decimal          # reddito dell'anno stimato
    band: str                   # formula della fascia applicata
    annual: Decimal             # detrazione annua per il reddito stimato
    days: int                   # giorni del mese
    computed: Decimal           # detrazione del mese ricalcolata
    printed: Decimal            # detrazione del mese stampata (zero se assente)
    year_to_date: Decimal | None  # detrazioni effettive dell'anno fino a questo mese

    @property
    def months_left(self) -> int:
        return _count(self.remaining)

    @property
    def matches(self) -> bool:
        return abs(self.printed - self.computed) <= TOL_TAX


def remaining_months(month: int, ccnl: str | None) -> list[str]:
    """Le mensilità ancora da pagare dopo `month`: i mesi restanti e le mensilità aggiuntive del contratto."""
    labels = [f"{n} mesi" if n > 1 else "1 mese" for n in [12 - month] if n > 0]
    c = contract(ccnl)
    extra = c["mensilita_aggiuntive"] if c else DEFAULT_EXTRA_MONTHS
    labels += [e["nome"] for e in sorted(extra, key=lambda e: -e["mese"]) if e["mese"] > month]
    return labels


def _count(labels: list[str]) -> int:
    return sum(int(l.split()[0]) if l[0].isdigit() else 1 for l in labels)


def _whole(d: Decimal) -> str:
    """Le costanti delle regole senza decimali inutili: 50.000 e non 50.000,00."""
    s = _fmt(d)
    return s[:-3] if s.endswith(",00") else s


def band_formula(income: Decimal, bands: list[dict]) -> str:
    """La formula della fascia di reddito in cui cade `income`, con i numeri."""
    lower = ZERO
    for b in bands:
        if b["fino_a"] is None or income <= b["fino_a"]:
            if not b["fisso"] and not b["variabile"]:
                return f"oltre {_whole(lower)} € di reddito non spetta"
            if not b["variabile"]:
                return f"fino a {_whole(b['fino_a'])} € spettano {_whole(b['fisso'])} €"
            fixed = f"{_whole(b['fisso'])} + " if b["fisso"] else ""
            return (f"{fixed}{_whole(b['variabile'])} × ({_whole(b['limite'])} − {_fmt(income)}) / "
                    f"{_whole(b['ampiezza'])}")
        lower = b["fino_a"]
    return ""


def monthly_deduction(p: Payslip) -> MonthlyDeduction | None:
    """Ricostruisce la detrazione per lavoro dipendente del mese; None se mancano dati o regole."""
    s = p.summary
    r = rules(p.period.year)
    to_date, month_income = s.get("annuo.imponibile_fiscale"), s.get("totali.imponibile_fiscale")
    if p.period.kind != "Mensilita'normale" or r is None or to_date is None or month_income is None:
        return None
    bands = r["detrazione_lavoro_dipendente"]["fasce"]
    remaining = remaining_months(p.period.month, p.contract.ccnl)
    projected = to_date + month_income * _count(remaining)
    annual = employee_deduction(projected, bands, r["detrazione_lavoro_dipendente"].get("maggiorazione"))
    # I giorni di detrazione stampati: meno di quelli del mese se il rapporto inizia o finisce nel mese.
    days = int(p.days.get("gg_detrazioni") or calendar.monthrange(p.period.year, p.period.month)[1])
    return MonthlyDeduction(
        income_to_date=to_date, month_income=month_income, remaining=remaining,
        contract=(contract(p.contract.ccnl) or {}).get("nome"), projected=_money(projected),
        band=band_formula(projected, bands), annual=_money(annual), days=days,
        computed=_money(annual * days / DAYS_IN_YEAR), printed=s.get("irpef.totale_detrazioni", ZERO),
        year_to_date=s.get("annuo.detrazioni_effettive"))


def _monthly_deduction(p: Payslip) -> CheckResult | None:
    d = monthly_deduction(p)
    if d is None:
        return None
    formula = (f"detrazione annua su un reddito stimato di {_fmt(d.projected)} € × {d.days} / {DAYS_IN_YEAR}")
    if d.matches:
        return CheckResult(check_id="detrazione_mese", status=CheckStatus.OK, title="Detrazione del mese",
                           formula=formula, expected=d.printed, actual=d.computed)
    detail = ("Il gestionale sembra stimare il reddito dell'anno in un altro modo. Il valore definitivo "
              "si vede nel conguaglio di dicembre.")
    if d.contract is None:
        detail = (f"Il contratto ({p.contract.ccnl or 'non indicato'}) non è tra quelli che conosco, quindi "
                  "nella stima ho contato solo la tredicesima: se ci sono altre mensilità la stima è più bassa "
                  "di quella del gestionale. " + detail)
    return CheckResult(
        check_id="detrazione_mese", status=CheckStatus.NOT_VERIFIABLE, title="Detrazione del mese",
        formula=formula, expected=d.printed, actual=d.computed, detail=detail)


def _unknown(ctx: _Context) -> CheckResult | None:
    unknown = sorted({f"{l.code} {l.description}" for l in ctx.p.lines if not ctx.g.known(l)})
    if not unknown:
        return None
    return CheckResult(
        check_id="voci_sconosciute", status=CheckStatus.NOT_VERIFIABLE, title="Voci non in glossario",
        formula="ogni voce deve avere una spiegazione",
        detail="Non so spiegare: " + "; ".join(unknown) + ". Chiedere all'ufficio paghe.")


def check(p: Payslip) -> list[CheckResult]:
    r = rules(p.period.year)
    ctx = _Context(p, glossary(p.parser))
    results: list[CheckResult | None] = [
        *_inps(ctx, r),
        _taxable_inps(ctx),
        _taxable_irpef(ctx, r),
        *_irpef(ctx, r),
        _monthly_deduction(p),
        *_year_end(ctx, r),
        _tfr(ctx, r),
        *_leave(p),
        _unknown(ctx),
    ]
    return [c for c in results if c is not None]
