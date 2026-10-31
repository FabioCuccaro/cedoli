import json
import re

from bp import extract
from bp.anonymize import FORMAT, anonymize, mask
from tests import synthetic
from tests.synthetic import FAKE_CF, FAKE_IBAN, FAKE_NAME


def test_masks_personal_data_and_keeps_the_form(tmp_path):
    doc = extract.load(synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf"))
    dump = anonymize(doc)
    text = json.dumps(dump, ensure_ascii=False)
    assert dump["formato"] == FORMAT
    for secret in (FAKE_CF, FAKE_IBAN, *FAKE_NAME.split(), "ESEMPIO"):
        assert secret not in text
    rows = [r["testo"] for page in dump["pagine"] for r in page]
    assert not any(re.search(r"[0-8]", r) for r in rows)  # ogni cifra è diventata 9
    assert any("VOCI RETRIBUTIVE" in r for r in rows) and any("NETTO" in r for r in rows)
    # Posizioni e font restano: servono a scrivere il parser del formato nuovo.
    first = dump["pagine"][0][0]["parole"][0]
    assert isinstance(first[1], float) and first[3]


def test_mask_keeps_item_codes_but_not_identifiers():
    assert mask("Z00087 INPS-FPLD/IVS c/DIP") == "Z99999 INPS-FPLD/IVS x/DIP"
    assert mask("ROSSI MARIO RSSMRA80A01H501U") == "XXXXX XXXXX XXXXXX99X99X999X"
    assert mask("Auto targa AB123CD") == "Auto xxxxx XX999XX"
