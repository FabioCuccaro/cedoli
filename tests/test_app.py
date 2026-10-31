import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from bp.app import already_running, make_server, running_version, serve
from bp.archive import Archive
from tests import synthetic
from tests.synthetic import FAKE_CF, FAKE_IBAN


@pytest.fixture
def server(tmp_path):
    srv = make_server(Archive(tmp_path / "archivio"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"X-BP": "1", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_upload_report_history_and_remove(server, tmp_path):
    srv, base = server
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf").read_bytes()

    status, body = call(base + "/carica", pdf)
    r = json.loads(body)
    assert status == 200 and r["ok"] and r["new"] and r["label"] == "Marzo 2026"
    # Lo stesso file una seconda volta non si duplica.
    assert json.loads(call(base + "/carica", pdf)[1])["message"] == "già presente"

    _, home = call(base + "/")
    assert "Marzo 2026" in home and "1.906,85 €" in home
    sha = home.split('href="/mese/')[1].split('"')[0]

    status, month = call(f"{base}/mese/{sha}")
    assert status == 200 and "Cedolino Marzo 2026" in month and 'href="/"' in month
    status, hist = call(base + "/storico")
    assert status == 200 and "Storico cedolini" in hist
    for page in (home, month, hist):
        assert FAKE_CF not in page and FAKE_IBAN not in page

    assert call(f"{base}/elimina/{sha}", b"")[0] == 200
    assert "Marzo 2026" not in call(base + "/")[1]
    assert not list((tmp_path / "archivio" / "cedolini").iterdir())


def test_unreadable_files_are_not_kept(server, tmp_path):
    _, base = server
    r = json.loads(call(base + "/carica", b"non sono un pdf")[1])
    assert not r["ok"] and r["message"].startswith("non è un PDF")
    assert not list((tmp_path / "archivio" / "cedolini").iterdir())


def test_damaged_pdf_never_blocks_the_archive(server, tmp_path):
    _, base = server
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf").read_bytes()
    r = json.loads(call(base + "/carica", pdf[: len(pdf) // 2])[1])  # download interrotto a metà
    assert not r["ok"] and "rovinato" in r["message"]
    assert not list((tmp_path / "archivio" / "cedolini").iterdir())

    # Un file illeggibile finito nella cartella in altro modo: l'elenco si apre e lo segnala.
    junk = tmp_path / "archivio" / "cedolini" / ("0" * 64 + ".pdf")
    junk.write_bytes(b"%PDF-1.4 rotto")
    call(base + "/carica", pdf)
    status, home = call(base + "/")
    assert status == 200 and "Marzo 2026" in home and "File che non si riescono a leggere" in home
    assert call(base + "/storico")[0] == 200
    assert call(f"{base}/elimina/{'0' * 64}", b"")[0] == 200
    assert not junk.exists() and "File che non si riescono a leggere" not in call(base + "/")[1]


def test_unexpected_error_shows_a_page(server, monkeypatch):
    _, base = server

    def boom(*args):
        raise RuntimeError("guasto")

    monkeypatch.setattr("bp.app.render_archive", boom)
    status, page = call(base + "/")
    assert status == 500 and "errore imprevisto (RuntimeError)" in page and "al sicuro" in page


def test_rejects_foreign_requests(server, tmp_path):
    _, base = server
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf").read_bytes()
    # Senza X-BP (come farebbe un form di un altro sito) il caricamento è rifiutato.
    req = urllib.request.Request(base + "/carica", data=pdf, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    # Un Host diverso (DNS rebinding) non vede l'archivio.
    assert call(base + "/", headers={"Host": "attacker.example"})[0] == 403
    assert call(base + "/mese/../../etc/passwd")[0] == 404


def test_second_launch_reuses_the_running_app(server, tmp_path, capsys):
    srv, _ = server
    port = srv.server_address[1]
    assert already_running(port)
    serve(tmp_path / "altro", port, open_browser=False)  # ritorna subito invece di avviare un secondo server
    assert "già aperta" in capsys.readouterr().out


def test_launch_after_update_replaces_the_old_app(tmp_path, capsys):
    """Dopo un aggiornamento la versione vecchia ancora aperta viene chiusa e sostituita."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from bp import __version__

    class Old(BaseHTTPRequestHandler):  # come le versioni fino alla 0.4: ping senza versione
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"busta-paga")

        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    old = ThreadingHTTPServer(("127.0.0.1", 0), Old)
    port = old.server_address[1]

    def run_old():  # come serve(): finito serve_forever, libera la porta
        old.serve_forever()
        old.server_close()

    threading.Thread(target=run_old, daemon=True).start()
    assert running_version(port) == ""
    threading.Thread(target=serve, args=(tmp_path / "a", port, False), daemon=True).start()
    for _ in range(50):
        if running_version(port) == __version__:
            break
        time.sleep(0.1)
    assert running_version(port) == __version__
    assert "Chiudo Busta chiara precedente" in capsys.readouterr().out
    call(f"http://127.0.0.1:{port}/chiudi", b"")


def test_busy_port_is_not_mistaken_for_the_app():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert not already_running(s.getsockname()[1])


def test_download_history_as_standalone_file(server, tmp_path):
    _, base = server
    pdf = synthetic.build(synthetic.normal_month(), tmp_path / "c.pdf").read_bytes()
    call(base + "/carica", pdf)
    with urllib.request.urlopen(base + "/storico/scarica") as r:
        assert r.headers["Content-Disposition"] == 'attachment; filename="storico_cedolini.html"'
        html = r.read().decode()
    assert "Storico cedolini" in html
    assert 'href="/"' not in html  # fuori dall'app il link per tornare all'elenco non avrebbe senso


def test_quit_button_stops_the_server(tmp_path):
    srv = make_server(Archive(tmp_path / "archivio"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    assert "Chiudi l'app" in call(base + "/")[1]
    assert call(base + "/chiudi", b"", {"X-BP": ""})[0] == 403  # una pagina di un altro sito non può spegnerla
    assert call(base + "/chiudi", b"")[0] == 200
    t.join(timeout=5)
    assert not t.is_alive()
    srv.server_close()


def test_version_is_shown(server):
    from bp import __version__

    _, base = server
    assert __version__ != "sviluppo"
    assert f"Busta chiara {__version__}" in call(base + "/")[1]


def test_new_format_offers_anonymous_structure(server, tmp_path):
    from reportlab.pdfgen.canvas import Canvas

    _, base = server
    pdf = tmp_path / "altro.pdf"
    c = Canvas(str(pdf))
    for i, text in enumerate(["CEDOLINO PAGA ROSSI MARIO", "TOTALE COMPETENZE 2.000,00", "TOTALE TRATTENUTE 500,00",
                              "NETTO IN BUSTA 1.500,00"]):
        c.drawString(72, 700 - 20 * i, text)
    c.save()
    data = pdf.read_bytes()

    r = json.loads(call(base + "/carica", data)[1])
    assert not r["ok"] and r["new_format"]
    # I link per mandare il file non portano nulla del cedolino.
    issue = r["send"]["issue"]
    assert issue.startswith("https://github.com/FabioCuccaro/busta-chiara-segnalazioni/issues/new?template=nuovo-formato.md")
    assert "ROSSI" not in issue and "1.500" not in issue and "2.000" not in issue
    assert not list((tmp_path / "archivio" / "cedolini").iterdir())

    req = urllib.request.Request(base + "/anonimo", data=data, method="POST", headers={"X-BP": "1"})
    with urllib.request.urlopen(req) as res:
        assert res.headers["Content-Disposition"] == 'attachment; filename="struttura_anonima.json"'
        dump = json.loads(res.read().decode())
    rows = [row["testo"] for row in dump["pagine"][0]]
    assert "CEDOLINO PAGA XXXXX XXXXX" in rows and "NETTO IN BUSTA 9.999,99" in rows
    assert not list((tmp_path / "archivio" / "cedolini").iterdir())  # niente viene salvato

    # Un PDF che non è una busta paga non propone l'export.
    r = json.loads(call(base + "/carica", b"non sono un pdf")[1])
    assert not r.get("new_format") and not r.get("send")
