from decimal import Decimal

import pytest

from bp.cli import import_file
from bp.knowledge import rules
from bp.models import CheckStatus
from bp.rules import employee_deduction, irpef_gross, monthly_deduction, remaining_months
from tests import synthetic


@pytest.fixture
def pdf(tmp_path):
    def make(spec, name="cedolino.pdf"):
        return synthetic.build(spec, tmp_path / name)
    return make


def statuses(payslip):
    return {c.check_id: c.status for c in payslip.coherence}


def test_irpef_brackets_2025_and_2026():
    # Valori verificati sui conguagli e sulle IRPEF mensili dei cedolini reali.
    assert irpef_gross(Decimal("45270"), rules(2025)["irpef"]["scaglioni"]) == Decimal("12484.50")
    monthly = irpef_gross(Decimal("2892.69"), rules(2026)["irpef"]["scaglioni"], 12)
    assert abs(monthly - Decimal("721.26")) < Decimal("0.01")


@pytest.mark.parametrize("income, expected", [
    (Decimal("10000"), Decimal("1955")),
    (Decimal("28000"), Decimal("1910")),
    (Decimal("45270"), Decimal("410.65")),
    (Decimal("60000"), Decimal("0")),
])
def test_employee_deduction_2025(income, expected):
    got = employee_deduction(income, rules(2025)["detrazione_lavoro_dipendente"]["fasce"])
    assert abs(got - expected) < Decimal("0.01")


def test_coherent_month(pdf):
    s = statuses(import_file(pdf(synthetic.normal_month())))
    for check_id in ("inps_005", "imponibile_inps", "imponibile_fiscale", "irpef_lorda", "irpef_netta",
                     "saldo_FERIE", "saldo_R.O.L.", "detrazione_mese"):
        assert s[check_id] == CheckStatus.OK, check_id
    assert "voci_sconosciute" not in s


def test_year_end_conguaglio(pdf):
    s = statuses(import_file(pdf(synthetic.december_with_conguaglio())))
    assert s["conguaglio_lorda"] == CheckStatus.OK
    assert s["conguaglio_detrazione"] == CheckStatus.OK
    assert s["conguaglio"] == CheckStatus.OK
    assert s["imponibile_fiscale"] == CheckStatus.OK  # il rimborso contributivo riduce i contributi dedotti


def test_wrong_contribution_is_anomalous(pdf):
    spec = synthetic.normal_month()
    spec.contributi[0]["trat"] = "260,00"
    spec.summary["totali.trattenute"] = "895,83"
    spec.summary["totali.netto"] = "1.904,17"
    p = import_file(pdf(spec))
    assert p.extraction_ok  # il PDF è letto bene: è il contributo a non tornare
    check = next(c for c in p.coherence if c.check_id == "inps_005")
    assert check.status == CheckStatus.ANOMALOUS
    assert check.expected == Decimal("260.00") and check.actual == Decimal("257.32")


def test_unknown_item_is_reported(pdf):
    spec = synthetic.normal_month()
    spec.voci.append({"code": "ZZ999", "desc": "Voce misteriosa", "fig": "10,00"})
    check = next(c for c in import_file(pdf(spec)).coherence if c.check_id == "voci_sconosciute")
    assert check.status == CheckStatus.NOT_VERIFIABLE
    assert "ZZ999" in check.detail


def test_year_without_rules(pdf):
    spec = synthetic.normal_month()
    spec.year = 2019
    s = statuses(import_file(pdf(spec)))
    assert s["irpef_lorda"] == CheckStatus.NOT_VERIFIABLE
    assert s["imponibile_fiscale"] == CheckStatus.NOT_VERIFIABLE
    assert s["inps_005"] == CheckStatus.OK  # usa l'aliquota stampata


def test_remaining_months():
    assert remaining_months(3, "Terziario Confcommercio") == ["9 mesi", "tredicesima", "quattordicesima"]
    assert remaining_months(7, "Terziario Confcommercio") == ["5 mesi", "tredicesima"]
    assert remaining_months(11, "Metalmeccanica") == ["1 mese", "tredicesima"]
    assert remaining_months(12, None) == []
    # Contratto non riconosciuto: si conta solo la tredicesima.
    assert remaining_months(3, "Contratto sconosciuto") == ["9 mesi", "tredicesima"]


def test_contracts():
    from bp.knowledge import contract

    assert contract("Terziario Confcommercio")["nome"] == "Terziario, distribuzione e servizi"
    assert contract("COMMERCIO")["nome"] == "Terziario, distribuzione e servizi"
    assert contract("Metalmeccanica industria")["nome"] == "Metalmeccanici industria"
    assert contract("Turismo") is None and contract(None) is None


def test_unknown_contract_explains_the_estimate(pdf):
    spec = synthetic.normal_month()
    p = import_file(pdf(spec))
    p.contract.ccnl = "Contratto sconosciuto"
    d = monthly_deduction(p)
    assert d.contract is None and d.remaining == ["9 mesi", "tredicesima"]
    from bp.report import render
    assert "non è tra quelli che Busta chiara conosce" in render(p)


def test_monthly_deduction_projection(pdf):
    d = monthly_deduction(import_file(pdf(synthetic.normal_month())))
    assert d.projected == Decimal("41591.62")
    assert d.annual == Decimal("730.00") and d.days == 31
    assert d.computed == d.printed == Decimal("62.00")


def test_no_deduction_when_projection_exceeds_limit(pdf):
    # Un mese con importi alti fa superare i 50.000 € alla stima: il gestionale non stampa la detrazione.
    spec = synthetic.normal_month()
    spec.summary["annuo.imponibile_fiscale"] = "30.000,00"
    spec.summary.pop("irpef.detr_lavoro_dipendente")
    spec.summary.pop("irpef.totale_detrazioni")
    spec.summary["irpef.imposta_netta"] = "606,58"
    spec.summary["totali.trattenute"] = "955,15"
    spec.summary["totali.netto"] = "1.844,85"
    p = import_file(pdf(spec))
    assert p.extraction_ok
    d = monthly_deduction(p)
    assert d.computed == 0 and d.matches and "non spetta" in d.band
    assert statuses(p)["detrazione_mese"] == CheckStatus.OK


def test_other_projection_is_not_verifiable(pdf):
    spec = synthetic.normal_month()
    spec.summary["annuo.imponibile_fiscale"] = "7.635,54"
    assert statuses(import_file(pdf(spec)))["detrazione_mese"] == CheckStatus.NOT_VERIFIABLE
