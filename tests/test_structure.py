import json

import pytest

from bp import extract, partial, structure
from bp.anonymize import anonymize
from tests import synthetic


@pytest.fixture
def dump(tmp_path):
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")
    path = tmp_path / "struttura_anonima.json"
    path.write_text(json.dumps(anonymize(extract.load(pdf))), encoding="utf-8")
    return path


def test_analyze(dump):
    layout = structure.analyze(structure.load(dump))
    assert layout.model == "PAYLUL01" and layout.pages == 1
    assert set(layout.totals) == {"competenze", "trattenute", "netto"}
    assert len(layout.partial.values) == 3 and layout.columns
    text = structure.describe(layout)
    assert "modello PAYLUL01" in text and "Lettura parziale: funziona" in text


def test_synthetic_pdf_keeps_the_layout(dump, tmp_path):
    doc = structure.load(dump)
    pdf = structure.synthesize(doc, tmp_path / "s.pdf")
    again = extract.load(pdf)
    rows = [r.text for page in again.pages for r in page]
    original = [r.text for page in doc.pages for r in page]
    assert sum(a == b for a, b in zip(rows, original)) >= 0.9 * len(original)
    assert again.keywords["HRZ_MODEL"] == "PAYLUL01"
    assert len(partial.read(again).values) == 3


def test_parser_skeleton(dump, tmp_path):
    layout = structure.analyze(structure.load(dump))
    source = structure.skeleton(layout)
    ns: dict = {}
    exec(compile(source, "paylul01_bozza.py", "exec"), ns)
    assert ns["NAME"] == "paylul01" and ns["detect"](structure.load(dump))
    with pytest.raises(NotImplementedError):
        ns["parse"](structure.load(dump))


def test_not_a_structure(tmp_path):
    (tmp_path / "x.json").write_text('{"formato": "altro"}', encoding="utf-8")
    with pytest.raises(ValueError, match="non è una struttura anonima"):
        structure.load(tmp_path / "x.json")
