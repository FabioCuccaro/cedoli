import json

from typer.testing import CliRunner

from bp.cli import app
from tests import synthetic


def test_verifica_snapshot_and_changes(tmp_path):
    (tmp_path / "pdf").mkdir()
    synthetic.build(synthetic.normal_month(), tmp_path / "pdf" / "marzo.pdf")
    snap = tmp_path / "data" / "verifica.json"
    run = lambda *extra: CliRunner().invoke(app, ["verifica", str(tmp_path / "pdf"), "--istantanea", str(snap), *extra])

    r = run()
    assert r.exit_code == 0 and snap.exists()
    assert run().exit_code == 0  # stessa lettura: nessun cambiamento

    # Una modifica che cambia il netto letto deve venire segnalata.
    data = json.loads(snap.read_text(encoding="utf-8"))
    entry = next(iter(data.values()))
    entry["totali"]["totali.netto"] = "1.00"
    check_id = next(iter(entry["controlli"]))
    entry["controlli"][check_id] = "anomalo"
    snap.write_text(json.dumps(data), encoding="utf-8")
    r = run()
    assert r.exit_code == 1
    assert "totali.netto 1.00 → 1906.85" in r.output and f"{check_id} anomalo → ok" in r.output

    assert run("--aggiorna").exit_code == 0 and run().exit_code == 0
