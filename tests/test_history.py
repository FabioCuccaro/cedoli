import re
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from bp import history
from bp.cli import app, import_file
from bp.report import render_history
from tests import synthetic
from tests.synthetic import FAKE_CF, FAKE_IBAN


@pytest.fixture
def pdfs(tmp_path):
    """Marzo, dicembre e tredicesima: tre cedolini sintetici coerenti, in ordine sparso."""
    tredicesima = synthetic.normal_month()
    tredicesima.month, tredicesima.kind = 12, "Tredicesima"
    return [
        synthetic.build(synthetic.december_with_conguaglio(), tmp_path / "dic.pdf"),
        synthetic.build(tredicesima, tmp_path / "tredicesima.pdf"),
        synthetic.build(synthetic.normal_month(), tmp_path / "mar.pdf"),
    ]


@pytest.fixture
def payslips(pdfs):
    return [import_file(p) for p in pdfs]


def test_ordered_and_deduplicated(payslips):
    ps = history.ordered(payslips + payslips[:1])
    assert [(p.period.month, p.period.kind) for p in ps] == [
        (3, "Mensilita'normale"), (12, "Mensilita'normale"), (12, "Tredicesima")]


def test_previous_same_kind(payslips):
    ps = history.ordered(payslips)
    assert history.previous(ps, 0) is None
    assert history.previous(ps, 1) is ps[0]
    assert history.previous(ps, 2) is None  # la tredicesima si confronta solo con un'altra tredicesima



def _other_employer(p, employer="NUOVA AZIENDA S.R.L."):
    q = p.model_copy(deep=True, update={"file_sha256": "altro" + p.file_sha256})
    q.contract.employer = employer
    return q


def test_change_of_employer(payslips):
    from bp.report import names

    march = history.ordered(payslips)[0]
    other = _other_employer(march)
    ps = history.ordered([march, other])
    # Stesso mese, aziende diverse: due voci distinte, nessun confronto tra le due.
    assert len(ps) == 2
    assert history.previous(ps, 1) is None
    ids = names(ps)
    assert sorted(i for i, _ in ids.values()) == ["2026-03-aziendadiese", "2026-03-nuovaazienda"]
    assert ids[other.file_sha256][1].endswith("· NUOVA AZIENDA S.R.L.")
    page = render_history(ps)
    assert 'id="m-2024-03-nuovaazienda"' in page or "2026-03-nuovaazienda" in page

def test_changes_explain_net_difference(payslips):
    march, december, _ = history.ordered(payslips)
    changes = history.changes(march, december)
    delta = december.amount("totali.netto") - march.amount("totali.netto")
    assert sum((c.effect for c in changes), Decimal(0)) == delta
    assert any(c.note == "nuova" and c.effect > 0 for c in changes)  # il bonus di dicembre
    assert any(c.label == "Conguaglio IRPEF" and c.effect < 0 for c in changes)
    effects = [abs(c.effect) for c in changes if not c.label.startswith(("Altre", "Variazioni", "Un'altra"))]
    assert effects == sorted(effects, reverse=True)


def test_changes_fold_minor_items(payslips):
    march, december, _ = history.ordered(payslips)
    folded = history.changes(march, december, limit=1)
    assert len(folded) == 2 and folded[1].label.endswith("variazioni minori")
    assert sum(c.effect for c in folded) == sum(c.effect for c in history.changes(march, december))


def test_history_page(payslips):
    html = render_history(payslips)
    for month_id in ("2026-03", "2026-12", "2026-12-13"):
        assert f'id="m-{month_id}"' in html
    assert "Cosa è cambiato rispetto a marzo 2026" in html
    assert "non c'è un mese precedente" in html
    assert "Detrazioni mese per mese" in html and "Con il reddito vero dell'anno" in html
    assert "Trattenute / lordo" in html and "del lordo:" in html  # incidenza per mese e sull'intero periodo
    # Nessuna risorsa esterna e nessun dato personale.
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", html)
    assert "@import" not in html and "fetch(" not in html
    for secret in (FAKE_CF, FAKE_IBAN, "ROSSI"):
        assert secret not in html


def test_cli_storico(pdfs, tmp_path):
    out = tmp_path / "storico.html"
    result = CliRunner().invoke(app, ["storico", *map(str, pdfs), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").count('<article class="month"') == 3


def test_section_order_and_defaults(payslips):
    html = render_history(payslips)
    december = html[html.index('id="m-2026-12"'):html.index('id="m-2026-12-13"')]
    order = ["Riepilogo del cedolino", "Da sapere questo mese", "Cosa è cambiato rispetto a marzo 2026",
             "Dal lordo al netto", "Controlli di coerenza", "Retribuzione, ferie e TFR"]
    positions = [december.index(f"<h2>{title}</h2>") for title in order]
    assert positions == sorted(positions)
    assert html.index("<h2>Mese per mese</h2>") < html.index('id="m-2026-03"')
    # Aperte all'inizio solo le sezioni principali.
    opened = set(re.findall(r'<details class="fold" data-fold="([^"]+)" open>', html))
    assert opened == {"grafico", "riepilogo", "sapere", "diff"}


def test_preposition_before_month():
    from bp.report import rispetto_a
    assert rispetto_a("Marzo 2026") == "a marzo 2026"
    assert rispetto_a("Agosto 2026") == "ad agosto 2026"
    assert rispetto_a("Tredicesima 2025") == "alla tredicesima 2025"


def test_month_anchor_does_not_match_url_fragment(tmp_path):
    # L'URL dello storico termina con #2026-09: se un elemento avesse quell'id il browser
    # scorrerebbe da solo fino al mese, a metà pagina, a ogni apertura.
    ps = [import_file(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf"))]
    html = render_history(ps)
    assert 'id="2026-03"' not in html and 'id="m-2026-03"' in html


def test_year_filter(payslips):
    from bp.report import history_context

    march = history.ordered(payslips)[0]
    older = march.model_copy(deep=True, update={"file_sha256": "anno" + march.file_sha256})
    older.period.year = 2025
    ctx = history_context(payslips + [older])
    assert [y["year"] for y in ctx["years"]] == [2025, 2026]
    assert ctx["years"][1]["count"] == 3
    page = render_history(payslips + [older])
    assert 'data-filter="2025"' in page and 'data-filter=""' in page
    # Con un solo anno il filtro non serve.
    assert 'data-filter=""' not in render_history(payslips)
