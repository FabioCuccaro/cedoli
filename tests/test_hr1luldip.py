from decimal import Decimal

import pytest

from bp.cli import import_file
from bp.models import CheckStatus, Section
from bp.report import month_id, month_label, render
from tests import synthetic_hr1
from tests.synthetic import FAKE_CF, FAKE_IBAN, FAKE_NAME


@pytest.fixture
def pdf(tmp_path):
    def make(spec, name="cedolino.pdf"):
        return synthetic_hr1.build(spec, tmp_path / name)
    return make


def test_normal_month(pdf):
    p = import_file(pdf(synthetic_hr1.normal_month()))

    assert p.parser == "hr1luldip"
    assert (p.period.year, p.period.month, p.period.kind) == (2024, 3, "Mensilita'normale")
    assert p.contract.employer == "AZIENDA DI ESEMPIO SPA"
    assert p.contract.ccnl == "Terziario EMI"
    assert p.salary_elements["PAGA BASE"] == Decimal("1500.00000")
    assert p.salary_elements["TOTALE"] == Decimal("2400.00000")
    assert p.days == {"settimane": Decimal("4"), "gg_inps": Decimal("26"), "gg_detrazioni": Decimal("31")}

    lines = [(l.code, l.note) for l in p.lines]
    assert ("Z31000", "C/Ditta") in lines and ("003041", "C/Ditta") in lines
    by_code = {l.code: l for l in p.lines if l.note != "C/Ditta"}
    assert by_code["Z00001"].description == "Retribuzione"
    assert (by_code["Z00001"].qty, by_code["Z00001"].unit_amount) == (Decimal("168.00000"), Decimal("14.28571"))
    assert by_code["004574"].figurative == Decimal("160.00")
    assert by_code["Z00000"].section == Section.CONTRIBUTI
    assert (by_code["Z00000"].base, by_code["Z00000"].rate) == (Decimal("2550.00"), Decimal("9.19000"))
    assert by_code["Z00346"].earning == Decimal("178.50")
    assert by_code["F09110"].section == Section.ADDIZIONALI
    assert (by_code["F09110"].year, by_code["F09110"].note) == (2023, "REGIONE ESEMPIO")
    assert by_code["F09110"].figurative == Decimal("300.00")
    # Imponibile, IRPEF e ritenuta del mese sono totali, non righe.
    assert "F03020" not in by_code
    assert p.summary["irpef.imposta_netta"] == Decimal("543.91")
    assert p.summary["totali.imponibile_fiscale"] == Decimal("2479.73")
    assert p.summary["tfr.quota_mese"] == Decimal("176.14")
    assert p.summary["tfr.accantonato_ap"] == Decimal("12000.00")
    assert p.summary["annuo.imponibile_fiscale"] == Decimal("7439.19")
    assert p.summary["totali.netto"] == Decimal("1902.77")
    assert {b.kind: (b.saldo, b.unit) for b in p.leave} == {
        "FERIE": (Decimal("45.33333"), "ore"), "R.O.L.": (Decimal("27.00000"), "ore")}

    assert p.extraction_ok


def test_coherence(pdf):
    p = import_file(pdf(synthetic_hr1.normal_month()))
    status = {c.check_id: c.status for c in p.coherence}

    for check in ("inps_Z00000", "imponibile_inps", "imponibile_fiscale", "irpef_lorda", "irpef_netta", "tfr",
                  "saldo_FERIE", "saldo_R.O.L."):
        assert status[check] == CheckStatus.OK, check
    assert "voci_sconosciute" not in status


def test_totals_must_reconcile(pdf):
    spec = synthetic_hr1.normal_month()
    spec.totals = ("2.728,50", "825,00", "1.903,50")
    p = import_file(pdf(spec))

    assert {c.check_id: c.status for c in p.checks}["trattenute"] == CheckStatus.FAILED
    assert not p.extraction_ok


def test_second_page(pdf):
    spec = synthetic_hr1.normal_month()
    spec.two_pages = True
    p = import_file(pdf(spec))

    assert p.pages == 2
    assert p.extraction_ok
    assert sum(1 for l in p.lines if l.code == "F09110") == 1


@pytest.mark.parametrize("tipced, month, kind, suffix", [
    ("40", 6, "Quattordicesima", "-14"),
    ("40", 12, "Tredicesima", "-13"),
    ("31", 4, "Cedolino aggiuntivo 1", "-agg"),
])
def test_additional_payslips(pdf, tipced, month, kind, suffix):
    spec = synthetic_hr1.normal_month()
    spec.tipced, spec.month, spec.dtipced = tipced, month, "Cedolino aggiuntivo 1"
    p = import_file(pdf(spec))

    assert p.period.kind == kind
    assert month_id(p) == f"2024-{month:02d}{suffix}"
    assert ("aggiuntivo" in month_label(p)) == (tipced == "31")


def test_no_personal_data(pdf):
    p = import_file(pdf(synthetic_hr1.normal_month()))
    out = p.model_dump_json() + render(p)

    for secret in (FAKE_NAME, FAKE_CF, FAKE_IBAN):
        assert secret not in out


def test_deduction_bonus_until_2024():
    from bp.knowledge import rules
    from bp.rules import employee_deduction

    d = rules(2023)["detrazione_lavoro_dipendente"]
    # 1.910 × (50.000 − 30.000) / 22.000, più i 65 € tra 25.000 e 35.000.
    assert employee_deduction(Decimal("30000"), d["fasce"], d["maggiorazione"]).quantize(Decimal("0.01")) \
        == Decimal("1801.36")
    assert employee_deduction(Decimal("36000"), d["fasce"], d["maggiorazione"]).quantize(Decimal("0.01")) \
        == Decimal("1215.45")
