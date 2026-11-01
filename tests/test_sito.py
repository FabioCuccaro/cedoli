"""Il sito (docs/, pubblicato con GitHub Pages dal repository pubblico) mantiene la stessa promessa dell'app:
nessuna risorsa esterna, nessun tracker, solo link che l'utente clicca da sé."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.test_zero_rete import external_problems

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGES = sorted(DOCS.glob("*.html"))
CSP = "default-src 'none'; img-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'none'"
# Link che portano fuori dal sito: solo pagine ufficiali di Busta chiara, Ko-fi e documentazione citata.
ALLOWED = re.compile(
    r"https://github\.com/FabioCuccaro/busta-chiara(-segnalazioni)?(/|$)"
    r"|https://ko-fi\.com/busta_chiara$"
    r"|mailto:bustachiara\.segnalazioni@proton\.me$"
    r"|https://docs\.astral\.sh/uv/"
    r"|https://docs\.github\.com/"
)


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.local: list[str] = []
        self.csp = ""

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "meta" and a.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = a["content"]
        for k in ("src", "href"):
            v = a.get(k, "")
            if v and not re.match(r"[a-z]+:|#", v):
                self.local.append(v.split("#")[0] or "./")


def test_site_exists():
    assert {p.name for p in PAGES} >= {"index.html", "verifica.html"}
    assert (DOCS / ".nojekyll").exists()


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_site_loads_nothing_from_outside(page):
    html = page.read_text(encoding="utf-8")
    problems, links = external_problems(html)
    assert not problems
    external = [h for h in links if re.match(r"[a-z]+:", h)]
    assert all(ALLOWED.match(h) for h in external), [h for h in external if not ALLOWED.match(h)]
    assert "style=" not in html  # la CSP vieta gli stili in linea: devono stare in sito.css
    assert not re.search(r"<script>(?!\s*</script>)", html)  # nessuno script in linea: solo sito.js


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_site_pages_forbid_external_loads_and_link_existing_files(page):
    r = _Refs()
    r.feed(page.read_text(encoding="utf-8"))
    assert r.csp == CSP
    for ref in r.local:
        target = DOCS / ("index.html" if ref == "./" else ref)
        assert target.exists(), ref


def test_release_markers_are_filled():
    """Il workflow windows riscrive questi segnaposto nel repository pubblico a ogni release."""
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d+\.\d+\.\d+", re.search(r"<!--versione-->(.*?)<!--/versione-->", html)[1])
    assert re.fullmatch(r"[0-9a-f]{64}", re.search(r"<!--sha256-->(.*?)<!--/sha256-->", html)[1])
    assert re.fullmatch(r"\d\d/\d\d/\d{4}", re.search(r"<!--data-->(.*?)<!--/data-->", html)[1])
    assert re.fullmatch(r"\d+ MB", re.search(r"<!--dimensione-->(.*?)<!--/dimensione-->", html)[1])
    assert "releases/latest/download/BustaChiara-windows.zip" in html
