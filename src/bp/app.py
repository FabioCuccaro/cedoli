"""App locale: un piccolo server raggiungibile solo da questo computer, aperto nel browser.

Il server ascolta su 127.0.0.1, rifiuta richieste con un Host diverso (DNS rebinding) e accetta
modifiche solo con l'intestazione X-BP, che una pagina di un altro sito non può aggiungere senza
un preflight a cui il server non risponde.
"""

import json
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bp import __version__, contribute, extract
from bp.anonymize import anonymize
from bp.archive import Archive
from bp.report import month_label, render, render_archive, render_history

MAX_UPLOAD = 20 * 1024 * 1024
# Sempre la stessa porta, così schede aperte e segnalibri restano validi tra un avvio e l'altro.
DEFAULT_PORT = 8573
PING = "busta-paga"
DOWNLOAD_NAME = "storico_cedolini.html"
ANON_NAME = "struttura_anonima.json"
ERROR_PAGE = ('<!doctype html><meta charset="utf-8"><title>Cedolì</title>'
              '<p style="font-family:sans-serif;max-width:40em;margin:3em auto">'
              'Cedolì ha incontrato un errore imprevisto ({}) e non è riuscita a mostrare questa pagina. '
              'I tuoi cedolini sono al sicuro nella cartella dell\'archivio. <a href="/">Torna all\'elenco</a></p>')
# Fisso in basso: lo storico si apre sull'ultimo mese, lontano dall'inizio della pagina.
BACK_LINK = ('<a href="/" style="position:fixed;left:16px;bottom:16px;z-index:10;padding:8px 14px;'
             'border-radius:20px;background:var(--accent);color:var(--on-accent);text-decoration:none;'
             'font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,.2)">← Le tue buste paga</a>')


def with_back_link(html: str) -> str:
    return html.replace("<body>", "<body>\n" + BACK_LINK, 1)


class Handler(BaseHTTPRequestHandler):
    archive: Archive
    lock = threading.Lock()  # pdfplumber e la cache non sono pensati per letture in parallelo

    def log_message(self, format, *args):  # niente log su terminale: conterrebbero solo rumore
        pass

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, status: HTTPStatus, body: str, ctype: str = "text/html; charset=utf-8",
              download: str | None = None) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # La pagina non carica nulla dall'esterno; lo dichiariamo anche al browser.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: HTTPStatus, **data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        try:
            self._get()
        except Exception as e:  # una pagina che non si genera non deve far cadere la connessione senza spiegazioni
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, ERROR_PAGE.format(type(e).__name__))

    def do_POST(self):
        try:
            self._post()
        except Exception as e:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, ok=False,
                       message=f"errore imprevisto ({type(e).__name__}): riprova o riavvia l'app")

    def _get(self):
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, "Accesso consentito solo da questo computer.")
        with self.lock:
            if self.path == "/ping":
                return self._send(HTTPStatus.OK, f"{PING} {__version__}", "text/plain; charset=utf-8")
            if self.path == "/":
                return self._send(HTTPStatus.OK, render_archive(self.archive.all(), str(self.archive.root),
                                                                self.archive.unreadable()))
            if self.path == "/storico":
                payslips = self.archive.all()
                if not payslips:
                    return self._redirect("/")
                return self._send(HTTPStatus.OK, with_back_link(render_history(payslips)))
            if self.path == "/storico/scarica":
                # Lo stesso storico come file autonomo da salvare dove si vuole, per esempio sul NAS;
                # nome fisso, così ogni mese il file nuovo sostituisce il precedente.
                payslips = self.archive.all()
                if not payslips:
                    return self._redirect("/")
                return self._send(HTTPStatus.OK, render_history(payslips), download=DOWNLOAD_NAME)
            if self.path.startswith("/mese/"):
                p = self.archive.get(self.path.removeprefix("/mese/"))
                if p is not None:
                    return self._send(HTTPStatus.OK, with_back_link(render(p)))
        self._send(HTTPStatus.NOT_FOUND, "Pagina non trovata.")

    def _post(self):
        if not self._host_ok() or self.headers.get("X-BP") != "1":
            return self._json(HTTPStatus.FORBIDDEN, ok=False, message="richiesta non consentita")
        length = int(self.headers.get("Content-Length") or 0)
        if self.path == "/carica":
            if length > MAX_UPLOAD:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, ok=False,
                                  message="file troppo grande (oltre 20 MB): un cedolino di solito è meno di 1 MB")
            data = self.rfile.read(length)
            with self.lock:
                added = self.archive.add(data)
            p = added.payslip
            return self._json(HTTPStatus.OK, ok=p is not None, new=added.new, message=added.message,
                              label=month_label(p) if p else None, new_format=added.new_format,
                              send=contribute.links() if added.new_format else None)
        if self.path == "/anonimo":
            # La struttura anonima di un PDF che non si sa leggere: il file non viene salvato da nessuna parte.
            if length > MAX_UPLOAD:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, ok=False, message="file troppo grande")
            data = self.rfile.read(length)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "cedolino.pdf"
                path.write_bytes(data)
                try:
                    dump = anonymize(extract.load(path))
                except ValueError as e:
                    return self._json(HTTPStatus.UNPROCESSABLE_ENTITY, ok=False, message=str(e))
            return self._send(HTTPStatus.OK, json.dumps(dump, ensure_ascii=False, indent=1),
                              "application/json; charset=utf-8", download=ANON_NAME)
        if self.path == "/chiudi":
            # Risponde prima di spegnersi; shutdown() aspetta serve_forever, quindi da un altro thread.
            self._json(HTTPStatus.OK, ok=True, message="")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path.startswith("/elimina/"):
            with self.lock:
                done = self.archive.remove(self.path.removeprefix("/elimina/"))
            return self._json(HTTPStatus.OK if done else HTTPStatus.NOT_FOUND, ok=done, message="")
        self._json(HTTPStatus.NOT_FOUND, ok=False, message="pagina non trovata")

    def _redirect(self, to: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", to)
        self.end_headers()


class Server(ThreadingHTTPServer):
    # Su Windows SO_REUSEADDR permetterebbe a due programmi di ascoltare sulla stessa porta.
    allow_reuse_address = sys.platform != "win32"


def make_server(archive: Archive, port: int = 0) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"archive": archive})
    return Server(("127.0.0.1", port), handler)


def _direct():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # mai attraverso un proxy


def running_version(port: int) -> str | None:
    """Versione dell'app che risponde su quella porta, "" se è una versione che non la dice, None se non c'è."""
    try:
        with _direct().open(f"http://127.0.0.1:{port}/ping", timeout=1) as r:
            text = r.read().decode()
    except OSError:
        return None
    return text.removeprefix(PING).strip() if text.startswith(PING) else None


def already_running(port: int) -> bool:
    """True se su quella porta risponde già questa app (per esempio aperta con un secondo doppio clic)."""
    return running_version(port) is not None


def close_running(port: int, wait: float = 5.0) -> bool:
    """Chiede all'app aperta su quella porta di chiudersi e aspetta che la porta si liberi."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/chiudi", data=b"", method="POST", headers={"X-BP": "1"})
    try:
        _direct().open(req, timeout=2).close()
    except OSError:
        pass
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not already_running(port):
            return True
        time.sleep(0.2)
    return False


def serve(data_dir: Path, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    running = running_version(port) if port else None
    if running is not None and running != __version__:
        # Dopo un aggiornamento la vecchia app resta aperta con i file nuovi sotto: la chiudiamo e ripartiamo.
        print(f"Chiudo Cedolì {running or 'precedente'} ancora aperta e avvio la {__version__}", flush=True)
        if close_running(port):
            running = None
    if running is not None:
        url = f"http://127.0.0.1:{port}/"
        print(f"Cedolì è già aperta su {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        return
    try:
        server = make_server(Archive(data_dir), port)
    except OSError:  # porta occupata da un altro programma: ne prendiamo una libera
        server = make_server(Archive(data_dir), 0)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Cedolì è aperta su {url}")
    print(f"Archivio: {data_dir}")
    print("Per uscire usa il tasto Chiudi nell'app, chiudi questa finestra o premi Ctrl+C.", flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
