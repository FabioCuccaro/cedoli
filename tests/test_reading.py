"""Messaggi chiari per i PDF che non si possono leggere: nessun errore tecnico arriva a chi usa l'app."""

import pytest
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen.canvas import Canvas

from bp.cli import import_file
from bp.extract import ReadError
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
    assert "protetto da password" in message(pdf)


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
