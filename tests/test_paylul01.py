from decimal import Decimal

import pytest
from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from bp.cli import app, import_file
from bp.models import CheckStatus, Section
from bp.parsers import UnsupportedLayout
from tests import synthetic
from tests.synthetic import FAKE_CF, FAKE_IBAN, FAKE_NAME


@pytest.fixture
def pdf(tmp_path):
    def make(spec, name="cedolino.pdf"):
        return synthetic.build(spec, tmp_path / name)
    return make


def checks(payslip):
    return {c.check_id: c.status for c in payslip.checks}


def test_normal_month(pdf):
    p = import_file(pdf(synthetic.normal_month()))

    assert (p.period.year, p.period.month, p.period.kind) == (2026, 3, "Mensilita'normale")
    assert p.contract.ccnl == "Terziario Confcommercio"
    assert p.salary_elements["Stipendio base"] == Decimal("2000.00")
    assert p.salary_elements["TOTALE"] == Decimal("2800.00")
    assert p.days["gg_detrazioni"] == Decimal("31.00")

    by_code = {l.code: l for l in p.lines}
    assert by_code["AA245"].earning == Decimal("2800.00")
    assert by_code["AA245"].qty == Decimal("26.00")
    assert by_code["AA245"].unit_amount == Decimal("107.69231")
    assert by_code["B0016"].figurative == Decimal("150.00")
    assert by_code["B0016"].earning is None
    assert by_code["TN0211"].deduction == Decimal("50.00")
    assert by_code["005"].section == Section.CONTRIBUTI
    assert (by_code["005"].base, by_code["005"].rate) == (Decimal("2800.00"), Decimal("9.190"))
    assert by_code["F00065"].deductible == Decimal("60.00")
    assert by_code["001"].year == 2025
    assert by_code["001"].note == "REGIONE DI ESEMPIO"

    assert p.summary["totali.netto"] == Decimal("1906.85")
    assert p.summary["totali.imponibile_fiscale"] == Decimal("2545.18")
    assert p.summary["irpef.imposta_netta"] == Decimal("544.58")
    assert p.summary["tfr.fondo_ap"] == Decimal("3207.4")

    leave = {b.kind: b for b in p.leave}
    assert leave["FERIE"].saldo == Decimal("4.17")
    assert leave["R.O.L."].godute is None

    assert checks(p) == {"netto": "ok", "competenze": "ok", "trattenute": "ok"}
    assert p.extraction_ok


def test_conguaglio_and_refund(pdf):
    p = import_file(pdf(synthetic.december_with_conguaglio()))
    refund = next(l for l in p.lines if l.code == "006CNG")
    assert refund.section == Section.CONTRIBUTI
    assert refund.earning == Decimal("20.00")
    assert refund.base == Decimal("-2000.00")
    assert refund.year == 2026
    assert p.summary["progr.conguaglio_debito"] == Decimal("150.00")
    # Il rimborso non entra nel totale competenze ma riduce le trattenute.
    assert p.extraction_ok, p.checks


def test_two_pages(pdf):
    spec = synthetic.normal_month()
    spec.two_pages = True
    p = import_file(pdf(spec))
    assert p.pages == 2
    assert p.summary["totali.netto"] == Decimal("1906.85")
    assert {b.kind for b in p.leave} == {"FERIE", "R.O.L."}
    assert p.extraction_ok


def test_detects_layout_without_metadata(pdf):
    spec = synthetic.normal_month()
    spec.metadata = False
    p = import_file(pdf(spec))
    assert (p.period.year, p.period.month) == (2026, 3)
    assert p.contract.ccnl is None
    assert p.extraction_ok


def test_totals_that_do_not_reconcile_are_flagged(pdf):
    spec = synthetic.normal_month()
    spec.summary["totali.trattenute"] = "900,00"
    spec.summary["totali.netto"] = "1.900,00"
    p = import_file(pdf(spec))
    assert checks(p)["netto"] == CheckStatus.OK
    assert checks(p)["trattenute"] == CheckStatus.FAILED
    assert not p.extraction_ok


def test_no_personal_data_in_output(pdf):
    p = import_file(pdf(synthetic.normal_month()))
    dump = p.model_dump_json()
    for secret in (FAKE_CF, FAKE_IBAN, "ROSSI", "MARIO", "01/01/1980"):
        assert secret not in dump


def test_rejects_other_pdfs(tmp_path):
    path = tmp_path / "altro.pdf"
    c = Canvas(str(path))
    c.drawString(100, 700, "Fattura n. 12 del 3 marzo 2026")
    c.save()
    with pytest.raises(UnsupportedLayout):
        import_file(path)


def test_cli_exit_codes(pdf, tmp_path):
    runner = CliRunner()
    ok = pdf(synthetic.normal_month(), "ok.pdf")
    result = runner.invoke(app, ["import", str(ok), "--out", str(tmp_path / "json")])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "json").glob("*.json"))) == 1

    spec = synthetic.normal_month()
    spec.summary["totali.competenze"] = "2.900,00"
    bad = pdf(spec, "bad.pdf")
    assert runner.invoke(app, ["import", str(bad)]).exit_code == 1
