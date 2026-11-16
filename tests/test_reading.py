"""Messaggi chiari per i PDF che non si possono leggere: nessun errore tecnico arriva a chi usa l'app."""

import pytest
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen.canvas import Canvas

from bp.cli import import_file
from bp import extract
from bp.extract import PasswordNeeded, ReadError
from bp.parsers import UnsupportedLayout, paylul01
from tests import synthetic


def pdf_with(path, lines, **kwargs):
    c = Canvas(str(path), **kwargs)
    for i, text in enumerate(lines):
        c.drawString(72, 700 - 20 * i, text)
    if not lines:
        c.rect(72, 600, 200, 100)  # solo grafica, come una scansione senza testo
    c.save()
    return path


def message(path) -> str:
    with pytest.raises(ReadError) as e:
        import_file(path)
    return str(e.value)


def test_truncated_pdf(tmp_path):
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")
    pdf.write_bytes(pdf.read_bytes()[:3000])
    assert "rovinato o incompleto" in message(pdf)


def test_garbage_after_pdf_header(tmp_path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4\nnon proprio un pdf")
    assert "rovinato o incompleto" in message(tmp_path / "x.pdf")


def test_password_protected_pdf(tmp_path):
    pdf = pdf_with(tmp_path / "p.pdf", ["NETTO"], encrypt=StandardEncryption("segreta"))
    assert message(pdf) == "il PDF è protetto da password"
    with pytest.raises(PasswordNeeded) as e:
        import_file(pdf, "sbagliata")
    assert e.value.wrong and "non apre questo PDF" in str(e.value) and "sbagliata" not in str(e.value)


@pytest.mark.parametrize("strength", [40, 128])
@pytest.mark.parametrize("password", ["segreta", "Pässwörd €5"])
def test_protected_payslip_reads_like_the_plain_one(tmp_path, strength, password):
    """Con la password giusta un cedolino protetto dà esattamente la stessa lettura di quello senza."""
    plain = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")
    locked = synthetic.build(synthetic.normal_month(), tmp_path / "p.pdf",
                             encrypt=StandardEncryption(password, ownerPassword="altra", strength=strength))
    assert b"/Encrypt" in locked.read_bytes()
    a, b = import_file(plain), import_file(locked, password)
    assert b.extraction_ok and b.file_sha256 != a.file_sha256
    assert b.model_dump(exclude={"file_sha256"}) == a.model_dump(exclude={"file_sha256"})


def test_protected_old_layout_reads_like_the_plain_one(tmp_path):
    from tests import synthetic_hr1

    plain = synthetic_hr1.build(synthetic_hr1.normal_month(), tmp_path / "c.pdf")
    locked = synthetic_hr1.build(synthetic_hr1.normal_month(), tmp_path / "p.pdf", encrypt=StandardEncryption("segreta"))
    a, b = import_file(plain), import_file(locked, "segreta")
    assert b.model_dump(exclude={"file_sha256"}) == a.model_dump(exclude={"file_sha256"})


def test_pdf_protected_only_against_printing_needs_no_password(tmp_path):
    """Solo la password "del proprietario" (limita stampa e copia): si apre senza chiedere nulla."""
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "p.pdf",
                          encrypt=StandardEncryption("", ownerPassword="altra", canPrint=0))
    assert import_file(pdf).extraction_ok


def test_password_is_ignored_for_a_plain_pdf(tmp_path):
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")
    assert extract.unlock(pdf.read_bytes(), "inutile") == pdf.read_bytes()
    assert import_file(pdf, "inutile").file_sha256 == import_file(pdf).file_sha256


def test_cli_asks_the_password_without_showing_it(tmp_path, monkeypatch):
    """Sul terminale la password si chiede (nascosta) una volta e vale per gli altri file dello stesso comando."""
    from typer.testing import CliRunner

    from bp import cli

    a = synthetic.build(synthetic.normal_month(), tmp_path / "a.pdf", encrypt=StandardEncryption("segreta"))
    b = synthetic.build(synthetic.normal_month(), tmp_path / "b.pdf", encrypt=StandardEncryption("segreta"))
    asked = []

    def prompt(text, **kwargs):
        assert kwargs["hide_input"]
        asked.append(text)
        return "sbagliata" if len(asked) == 1 else "segreta"

    monkeypatch.setattr(cli, "_passwords", [])
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli.typer, "prompt", prompt)
    r = CliRunner().invoke(cli.app, ["storico", str(a), str(b), "-o", str(tmp_path / "s.html")])
    assert r.exit_code == 0, r.output
    assert len(asked) == 2 and "a.pdf" in asked[0]  # una sbagliata, una giusta; per b.pdf non si richiede
    assert "segreta" not in r.output and "segreta" not in (tmp_path / "s.html").read_text(encoding="utf-8")


def test_cli_without_terminal_explains_and_accepts_the_variable(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from bp import cli

    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "p.pdf", encrypt=StandardEncryption("segreta"))
    monkeypatch.setattr(cli, "_passwords", [])
    monkeypatch.delenv(cli.PASSWORD_ENV, raising=False)
    r = CliRunner().invoke(cli.app, ["report", str(pdf), "-o", str(tmp_path / "r.html")])
    assert r.exit_code == 1 and "protetto da password" in r.output and "CEDOLI_PASSWORD" in r.output

    monkeypatch.setenv(cli.PASSWORD_ENV, "segreta")
    r = CliRunner().invoke(cli.app, ["report", str(pdf), "-o", str(tmp_path / "r.html")])
    assert r.exit_code == 0 and "Cedolino Marzo 2026" in (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "segreta" not in r.output


def test_pdf_without_text(tmp_path):
    assert "non contiene testo" in message(pdf_with(tmp_path / "s.pdf", []))


def test_not_a_payslip(tmp_path):
    pdf = pdf_with(tmp_path / "f.pdf", ["Fattura n. 12", "Totale da pagare 100,00"])
    with pytest.raises(UnsupportedLayout, match="non sembra una busta paga"):
        import_file(pdf)


def test_payslip_of_another_software(tmp_path):
    pdf = pdf_with(tmp_path / "b.pdf", ["CEDOLINO PAGA", "TOTALE COMPETENZE 2.000,00",
                                        "TOTALE TRATTENUTE 500,00", "NETTO IN BUSTA 1.500,00"])
    msg = message(pdf)
    assert "formato che Cedolì non sa ancora leggere" in msg and "paylul01" in msg
    assert ("lettura parziale: competenze 2.000,00 €, trattenute 500,00 €, netto 1.500,00 € "
            "(i tre numeri tornano tra loro)") in msg


def test_partial_reading_with_values_below_the_labels(tmp_path):
    from bp import extract, partial

    pdf = tmp_path / "c.pdf"
    c = Canvas(str(pdf))
    for x, label, value in [(72, "TOT. COMPETENZE", "2.000,00"), (220, "TOT. TRATTENUTE", "520,00"),
                            (370, "NETTO DEL MESE", "1.500,00€")]:
        c.drawString(x, 700, label)
        c.drawString(x + 10, 685, value)
    c.save()
    found = partial.read(extract.load(pdf))
    assert {k: str(v) for k, v in found.values.items()} == \
        {"competenze": "2000.00", "trattenute": "520.00", "netto": "1500.00"}
    assert found.adds_up is False and "non tornano" in found.summary()


def test_partial_reading_finds_nothing(tmp_path):
    from bp import extract, partial

    found = partial.read(extract.load(pdf_with(tmp_path / "n.pdf", ["CEDOLINO", "IRPEF INPS"])))
    assert found.values == {} and found.adds_up is None and partial.note(extract.load(tmp_path / "n.pdf")) == ""


def test_parser_crash_becomes_a_message(tmp_path, monkeypatch):
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")

    def broken(doc):
        raise KeyError("voce")

    monkeypatch.setattr(paylul01, "parse", broken)
    msg = message(pdf)
    assert "formato paylul01 riconosciuto" in msg and "KeyError" in msg
