import re

from typer.testing import CliRunner

from bp.cli import app, import_file
from bp.report import render, waterfall
from tests import synthetic
from tests.synthetic import FAKE_CF, FAKE_IBAN


def test_waterfall_adds_up(tmp_path):
    p = import_file(synthetic.build(synthetic.december_with_conguaglio(), tmp_path / "c.pdf"))
    steps = waterfall(p)
    assert steps[0].label == "Competenze" and steps[-1].label == "Netto"
    assert sum(s.amount for s in steps[:-1]) == steps[-1].amount


def test_report_content(tmp_path):
    html = render(import_file(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")))
    assert "Cedolino Marzo 2026" in html
    assert "1.906,85 €" in html
    assert "Auto aziendale a uso promiscuo" in html  # nome dal glossario
    assert "Lettura verificata" in html
    assert "Controlli di coerenza" in html
    assert "31,9% del lordo" in html  # trattenute 893,15 su competenze 2.800,00
    assert "Le spiegazioni delle voci sono indicative" in html


def test_report_is_offline_and_private(tmp_path):
    html = render(import_file(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")))
    # Nessuna risorsa esterna: il file si apre senza rete.
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", html)
    assert "@import" not in html
    for secret in (FAKE_CF, FAKE_IBAN, "ROSSI"):
        assert secret not in html


def test_cli_report(tmp_path):
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")
    out = tmp_path / "report.html"
    result = CliRunner().invoke(app, ["report", str(pdf), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_axis_covers_the_tallest_month():
    from decimal import Decimal

    from bp.report import _ticks

    top, ticks = _ticks(Decimal("3800"))
    assert top == Decimal("4000") and ticks[-1] == top
    assert _ticks(Decimal("7600"))[0] >= Decimal("7600")


def test_brand_and_theme_on_every_page(tmp_path):
    from bp.report import render_archive, render_history

    p = import_file(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf"))
    for html in (render(p), render_history([p]), render_archive([p], str(tmp_path))):
        assert 'class="brandbar"' in html and 'rel="icon"' in html
        # Il tema scelto si applica prima del disegno della pagina e si può cambiare dal menu.
        assert html.index('localStorage.getItem("bp-tema")') < html.index("<body>")
        assert 'select class="theme"' in html


def test_cli_version():
    from typer.testing import CliRunner

    from bp import __version__
    from bp.cli import app

    r = CliRunner().invoke(app, ["--version"])
    assert r.exit_code == 0 and r.output.strip() == f"Busta chiara {__version__}"


def test_report_explains_what_does_not_add_up(tmp_path):
    from decimal import Decimal

    from bp.models import CheckResult, CheckStatus

    p = import_file(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf"))
    html = render(p)
    assert "da guardare" not in html and "Cosa vuol dire" not in html

    p.coherence.append(CheckResult(check_id="x", title="IRPEF lorda del mese", status=CheckStatus.ANOMALOUS,
                                   formula="scaglioni", expected=Decimal("500.00"), actual=Decimal("512.30")))
    html = render(p)
    assert "1 controllo da guardare" in html
    assert "stampato 500,00 €" in html and "differenza +12,30 €" in html
    assert "Non vuol dire per forza che la busta paga sia sbagliata" in html and "ufficio paghe" in html

    p.checks[0].status = CheckStatus.FAILED
    assert not p.extraction_ok and "Cosa vuol dire" in render(p)


def test_donation_link_only_when_configured(tmp_path, monkeypatch):
    from bp import contribute
    from bp.report import render_archive
    from tests.test_zero_rete import _allowed_link, external_problems

    monkeypatch.setattr(contribute, "KOFI", "")
    assert "ko-fi" not in render_archive([], str(tmp_path))
    monkeypatch.setattr(contribute, "KOFI", "bustachiara")
    html = render_archive([], str(tmp_path))
    assert 'href="https://ko-fi.com/bustachiara"' in html
    problems, links = external_problems(html)
    assert not problems and all(_allowed_link(h) for h in links)


def test_disclaimer_on_every_page(tmp_path):
    from bp.report import render_archive, render_history

    p = import_file(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf"))
    for html in (render(p), render_history([p]), render_archive([p], str(tmp_path))):
        assert "Non è consulenza del lavoro né fiscale" in html
