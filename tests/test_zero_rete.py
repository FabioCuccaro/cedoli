"""Garanzia zero rete: l'app, il parser, i report e le esportazioni non escono mai da questo computer.

Due livelli:
- a run time, l'audit hook di ``conftest.py`` blocca e fa fallire ogni connessione verso fuori, in
  tutti i test; qui sotto ogni funzione dell'app viene usata almeno una volta sotto quel controllo;
- nelle pagine generate (report, storico, app) nessun elemento può far caricare al browser qualcosa
  da Internet: niente script, stili, immagini, font o richieste verso indirizzi esterni. Restano
  ammessi i link ``<a>`` che l'utente clicca da sé (segnalazione su GitHub, email).
"""

import json
import re
import socket
import threading
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bp import contribute
from bp.app import make_server, serve
from bp.archive import Archive
from bp.cli import app as cli
from tests import synthetic, synthetic_hr1
from tests.conftest import NetworkBlocked, is_local, take_violations

# Unico URL assoluto ammesso dentro script e stili: lo spazio dei nomi SVG, che non viene scaricato.
SVG_NS = "http://www.w3.org/2000/svg"


# --- il controllo funziona davvero --------------------------------------------------------------


@pytest.mark.parametrize("attempt", [
    lambda: socket.create_connection(("1.1.1.1", 443), timeout=1),
    lambda: socket.getaddrinfo("example.com", 443),
    lambda: socket.gethostbyname("example.com"),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("8.8.8.8", 53)),
    lambda: socket.socket().bind(("0.0.0.0", 0)),
    lambda: urllib.request.urlopen("https://example.com", timeout=1),
], ids=["tcp", "dns", "gethostbyname", "udp", "bind-tutte-le-interfacce", "urllib"])
def test_guard_blocks_outbound(attempt):
    with pytest.raises(NetworkBlocked):
        attempt()
    assert take_violations()  # registrato: il test fallirebbe anche se l'errore venisse intercettato


def test_guard_sees_attempts_swallowed_in_other_threads():
    def sneaky():
        try:
            socket.create_connection(("192.0.2.1", 80), timeout=1)
        except Exception:
            pass

    t = threading.Thread(target=sneaky)
    t.start()
    t.join()
    assert any("192.0.2.1" in v for v in take_violations())


def test_guard_allows_this_computer():
    for host in ("127.0.0.1", "127.8.9.10", "::1", "[::1]", "localhost"):
        assert is_local(host)
    for host in ("0.0.0.0", "", "192.168.1.10", "10.0.0.1", "example.com", "github.com"):
        assert not is_local(host)
    assert is_local("0.0.0.0", wildcard_ok=True)


# --- ogni funzione dell'app, sotto il controllo -------------------------------------------------


def _pdfs(tmp_path: Path) -> list[Path]:
    return [
        synthetic.build(synthetic.normal_month(), tmp_path / "paylul01.pdf"),
        synthetic.build(synthetic.december_with_conguaglio(), tmp_path / "dicembre.pdf"),
        synthetic_hr1.build(synthetic_hr1.normal_month(), tmp_path / "hr1.pdf"),
    ]


def _unknown_format(tmp_path: Path) -> Path:
    from reportlab.pdfgen.canvas import Canvas

    pdf = tmp_path / "altro.pdf"
    c = Canvas(str(pdf))
    for i, text in enumerate(["CEDOLINO PAGA", "TOTALE COMPETENZE 2.000,00", "TOTALE TRATTENUTE 500,00",
                              "NETTO IN BUSTA 1.500,00"]):
        c.drawString(72, 700 - 20 * i, text)
    c.save()
    return pdf


def test_command_line_never_goes_online(tmp_path):
    pdfs = _pdfs(tmp_path)
    run = lambda *args: CliRunner().invoke(cli, [*map(str, args)])
    for pdf in pdfs:
        assert run("report", pdf, "-o", tmp_path / f"{pdf.stem}.html").exit_code == 0
        assert run("import", pdf).exit_code == 0
        assert run("inspect", pdf, "-o", tmp_path / f"{pdf.stem}.json").exit_code == 0
    assert run("storico", *pdfs, "-o", tmp_path / "storico.html").exit_code == 0
    assert run("verifica", tmp_path, "--istantanea", tmp_path / "v.json").exit_code == 0
    anon = tmp_path / "anonima.json"
    assert run("anonimo", _unknown_format(tmp_path), "-o", anon).exit_code == 0
    r = run("struttura", anon, "--pdf", tmp_path / "sint.pdf", "--parser", tmp_path / "bozza.py")
    assert r.exit_code == 0, r.output
    assert run("--version").exit_code == 0


def _call(base: str, path: str, data: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"X-BP": "1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _app_pages(tmp_path: Path) -> dict[str, str]:
    """Usa l'app come farebbe un collega e restituisce ogni pagina che il browser riceve."""
    srv = make_server(Archive(tmp_path / "archivio"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    host, port = srv.server_address[:2]
    assert host == "127.0.0.1"
    base = f"http://127.0.0.1:{port}"
    pages = {"home vuota": _call(base, "/")[1].decode()}
    for pdf in _pdfs(tmp_path):
        assert json.loads(_call(base, "/carica", pdf.read_bytes())[1])["ok"]
    other = _unknown_format(tmp_path).read_bytes()
    r = json.loads(_call(base, "/carica", other)[1])
    assert r["new_format"]
    assert json.loads(_call(base, "/carica", b"non sono un pdf")[1])["ok"] is False
    pages["struttura anonima"] = _call(base, "/anonimo", other)[1].decode()
    home = _call(base, "/")[1].decode()
    pages["home"] = home
    pages["storico"] = _call(base, "/storico")[1].decode()
    pages["storico scaricato"] = _call(base, "/storico/scarica")[1].decode()
    for i, sha in enumerate(dict.fromkeys(re.findall(r'href="/mese/([0-9a-f]+)"', home))):
        pages[f"mese {i}"] = _call(base, f"/mese/{sha}")[1].decode()
    assert len([k for k in pages if k.startswith("mese")]) == 3
    assert _call(base, f"/elimina/{sha}", b"")[0] == 200
    assert _call(base, "/chiudi", b"")[0] == 200
    t.join(timeout=5)
    srv.server_close()
    return pages


def test_app_never_goes_online(tmp_path):
    _app_pages(tmp_path)  # il controllo di conftest.py fa fallire il test a ogni tentativo


def test_app_launch_opens_only_the_local_page(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # porta libera, poi la lasciamo all'app
    t = threading.Thread(target=serve, args=(tmp_path / "a", port, True), daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        if opened:
            break
        threading.Event().wait(0.1)
    assert opened == [base + "/"]
    _call(base, "/chiudi", b"")
    t.join(timeout=5)


# --- le pagine generate non caricano nulla da fuori ---------------------------------------------


# Attributi che fanno scaricare qualcosa al browser senza che l'utente clicchi.
FETCHING = {"src", "srcset", "data", "poster", "background", "action", "formaction", "manifest",
            "ping", "codebase", "archive", "longdesc", "xlink:href", "lowsrc", "dynsrc"}
# API del browser che possono parlare con un server.
SCRIPT_NET = re.compile(r"\b(XMLHttpRequest|WebSocket|EventSource|sendBeacon|importScripts|"
                        r"RTCPeerConnection|SharedWorker|ServiceWorker|serviceWorker|Worker)\b|\bimport\s*\(")
FETCH_CALL = re.compile(r"\bfetch\s*\(\s*([\"'`])(.*?)\1")
CSS_URL = re.compile(r"url\(\s*([\"']?)(.*?)\1\s*\)|@import", re.I)
ABSOLUTE = re.compile(r"(?:[a-z][a-z0-9+.-]*:)?//[^\s\"'`)<>]+", re.I)


def _local_ref(value: str) -> bool:
    v = value.strip().lower()
    return v.startswith(("data:", "#", "blob:", "about:blank")) or (v.startswith("/") and not v.startswith("//")) \
        or not re.match(r"[a-z][a-z0-9+.-]*:|//", v)


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.links: list[str] = []
        self._in: str | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v or "" for k, v in attrs}
        for k, v in a.items():
            if k in FETCHING and not _local_ref(v):
                self.problems.append(f"<{tag} {k}={v!r}>")
        if tag == "link" and not _local_ref(a.get("href", "")):
            self.problems.append(f"<link href={a['href']!r}>")
        if tag == "base":
            self.problems.append("<base>")
        if tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            self.problems.append("<meta http-equiv=refresh>")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if "style" in a:
            self._css(a["style"])
        if tag in ("script", "style"):
            self._in = tag

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "style":
            self._css(data)
        elif self._in == "script":
            if m := SCRIPT_NET.search(data):
                self.problems.append(f"script usa {m.group(0)}")
            for _, url in FETCH_CALL.findall(data):
                if not _local_ref(url):
                    self.problems.append(f"fetch({url!r})")
            for url in ABSOLUTE.findall(data):
                if url != SVG_NS:
                    self.problems.append(f"indirizzo esterno nello script: {url}")

    def _css(self, css):
        for m in CSS_URL.finditer(css):
            if m.group(0).lower() == "@import" or not _local_ref(m.group(2)):
                self.problems.append(f"css {m.group(0)}")


def external_problems(html: str) -> tuple[list[str], list[str]]:
    c = _Collector()
    c.feed(html)
    c.close()
    return c.problems, c.links


def _allowed_link(href: str) -> bool:
    """Link che il browser apre solo se l'utente ci clicca: pagine dell'app, segnalazione o donazione volontaria."""
    return (_local_ref(href) or href.startswith(contribute.REPO + "/") or href.startswith(f"mailto:{contribute.EMAIL}")
            or href.startswith("https://ko-fi.com/"))


def test_checker_catches_external_resources():
    bad = """<html><head><link rel="stylesheet" href="https://cdn.example/x.css">
    <script src="//cdn.example/x.js"></script><style>body{background:url(https://t.example/p.gif)}
    @import "x.css";</style></head><body><img src="http://t.example/p.png">
    <a href="https://x.example" ping="https://t.example">x</a><div style="background:url('//t.example/q')"></div>
    <script>fetch("https://api.example/x"); navigator.sendBeacon("/x"); const u = "https://t.example/";</script>
    </body></html>"""
    problems, links = external_problems(bad)
    assert len(problems) >= 9, problems
    assert not _allowed_link(links[0])
    ok = f"""<link rel="icon" href="data:image/svg+xml,x"><script>fetch("/carica");
    document.createElementNS("{SVG_NS}", "svg")</script><a href="/storico">s</a>"""
    assert external_problems(ok) == ([], ["/storico"])


def test_generated_pages_load_nothing_from_outside(tmp_path):
    pages = _app_pages(tmp_path)
    pages.pop("struttura anonima")  # JSON scaricato, non una pagina: controllato a parte
    pdfs = _pdfs(tmp_path)
    for pdf in pdfs:
        out = tmp_path / f"{pdf.stem}.html"
        CliRunner().invoke(cli, ["report", str(pdf), "-o", str(out)])
        pages[f"bp report {pdf.name}"] = out.read_text(encoding="utf-8")
    CliRunner().invoke(cli, ["storico", *map(str, pdfs), "-o", str(tmp_path / "s.html")])
    pages["bp storico"] = (tmp_path / "s.html").read_text(encoding="utf-8")

    for name, html in pages.items():
        problems, links = external_problems(html)
        assert not problems, f"{name}: {problems}"
        assert all(_allowed_link(h) for h in links), f"{name}: {[h for h in links if not _allowed_link(h)]}"


def test_new_format_links_open_only_on_click():
    """I link di invio sono indirizzi da aprire nel browser o nel programma di posta, mai richieste dell'app."""
    links = contribute.links()
    assert links["issue"].startswith(contribute.REPO + "/issues/new?")
    assert links.get("email", "mailto:").startswith("mailto:")
