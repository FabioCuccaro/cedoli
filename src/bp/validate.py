"""Quadratura dell'estrazione: le righe lette devono ricostruire i totali stampati.

Se una quadratura non torna, l'estrazione non è affidabile e il report non deve fingere sicurezza.
"""

from decimal import Decimal

from bp.models import CheckResult, CheckStatus, Payslip, Section

TOLERANCE = Decimal("0.005")


def _check(check_id: str, formula: str, expected: Decimal | None, actual: Decimal) -> CheckResult:
    if expected is None:
        return CheckResult(check_id=check_id, status=CheckStatus.NOT_VERIFIABLE, formula=formula, actual=actual)
    status = CheckStatus.OK if abs(expected - actual) <= TOLERANCE else CheckStatus.FAILED
    return CheckResult(check_id=check_id, status=status, formula=formula, expected=expected, actual=actual)


def _sum(values) -> Decimal:
    return sum((v for v in values if v is not None), Decimal("0"))


def reconcile(p: Payslip) -> list[CheckResult]:
    if p.parser == "hr1luldip":
        return _reconcile_columns(p)
    s = p.summary
    competenze = s.get("totali.competenze")
    trattenute = s.get("totali.trattenute")
    netto = s.get("totali.netto")

    checks = []
    if competenze is not None and trattenute is not None:
        checks.append(_check(
            "netto", "totale competenze − totale trattenute = netto", netto, competenze - trattenute))
    else:
        checks.append(_check("netto", "totali stampati presenti", None, Decimal("0")))

    # Anche le righe di imposta pagate (trattamento integrativo, restituzioni) sono competenze.
    earnings = _sum(l.earning for l in p.lines if l.section in (Section.VOCI, Section.IMPOSTA))
    checks.append(_check(
        "competenze", "somma delle competenze delle voci e dell'imposta = totale competenze", competenze, earnings))

    # Nelle tabelle dei contributi un importo in colonna competenze è un rimborso
    # (es. conguaglio IVS aggiuntivo): nel totale riduce le trattenute.
    refunds = _sum(l.earning for l in p.lines if l.section == Section.CONTRIBUTI)
    deductions = (
        _sum(l.deduction for l in p.lines)
        - refunds
        + p.amount("irpef.imposta_netta")
        + p.amount("progr.conguaglio_debito")
        - p.amount("progr.conguaglio_credito")
    )
    checks.append(_check(
        "trattenute",
        "trattenute delle righe − rimborsi + IRPEF netta + conguaglio a debito − a credito = totale trattenute",
        trattenute, deductions))
    return checks


def _reconcile_columns(p: Payslip) -> list[CheckResult]:
    """Layout HR1LULDIP: un'unica tabella, i totali sono le somme delle colonne Competenze e Trattenute.

    La ritenuta IRPEF del mese è nel riepilogo, non tra le righe; gli esoneri contributivi stanno
    in colonna competenze."""
    s = p.summary
    competenze, trattenute = s.get("totali.competenze"), s.get("totali.trattenute")
    checks = []
    if competenze is not None and trattenute is not None:
        checks.append(_check(
            "netto", "totale competenze − totale trattenute = netto", s.get("totali.netto"), competenze - trattenute))
    else:
        checks.append(_check("netto", "totali stampati presenti", None, Decimal("0")))
    checks.append(_check(
        "competenze", "somma della colonna competenze = totale competenze",
        competenze, _sum(l.earning for l in p.lines)))
    checks.append(_check(
        "trattenute", "somma della colonna trattenute + IRPEF del mese = totale trattenute",
        trattenute, _sum(l.deduction for l in p.lines) + p.amount("irpef.imposta_netta")))
    return checks
