import importlib.util
import io
import json
import zipfile
from pathlib import Path

from bp import extract
from bp.anonymize import anonymize
from tests import synthetic

spec = importlib.util.spec_from_file_location("segnalazioni", Path(__file__).parent.parent / "tools" / "segnalazioni.py")
seg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seg)


def test_download_group_and_prepare(tmp_path):
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf")
    dump = json.dumps(anonymize(extract.load(pdf))).encode()
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as z:
        z.writestr("struttura_anonima.json", dump)
    att = "https://github.com/user-attachments/files/1/struttura_anonima"
    issues = [
        {"number": 3, "html_url": "https://x/3", "body": f"testo\n[s.json]({att}.json)"},
        {"number": 4, "html_url": "https://x/4", "body": f"[s.zip]({att}.zip)"},
        {"number": 5, "html_url": "https://x/5", "body": "senza allegato"},
        {"number": 6, "html_url": "https://x/6", "body": "", "pull_request": {}},
    ]
    calls = []

    def get(url):
        calls.append(url)
        return {seg.API: json.dumps(issues).encode(), att + ".json": dump, att + ".zip": zipped.getvalue()}[url]

    assert seg.download(tmp_path, get) == []
    seg.download(tmp_path, get)  # la seconda volta non riscarica gli allegati
    assert calls.count(att + ".json") == 1
    (tmp_path / "segnalazioni" / "email").mkdir()
    (tmp_path / "segnalazioni" / "email" / "rotto.json").write_text("{}", encoding="utf-8")

    groups = seg.collect(tmp_path)
    assert [g.key for g in groups] == ["PAYLUL01", "file non leggibili"]
    assert [i.source for i in groups[0].items] == ["#3", "#4"] and groups[0].items[0].url == "https://x/3"
    page = seg.render(groups)
    assert "PAYLUL01" in page and 'href="https://x/4"' in page and "rotto.json" in page

    out = seg.prepare(groups[0], tmp_path)
    assert out == tmp_path / "formati" / "paylul01"
    assert {p.name for p in out.iterdir()} >= {"riepilogo.txt", "paylul01_bozza.py", "sintetico.pdf"}
