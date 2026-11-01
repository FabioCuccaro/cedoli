"""Il sito (docs/, pubblicato con GitHub Pages dal repository pubblico) mantiene la stessa promessa dell'app:
nessuna risorsa esterna, nessun tracker, solo link che l'utente clicca da sé."""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.test_zero_rete import external_problems

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGES = sorted(DOCS.glob("*.html"))
CSP = "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'none'"
# Link che portano fuori dal sito: solo pagine ufficiali di Cedolì, Ko-fi e documentazione citata.
ALLOWED = re.compile(
    r"https://github\.com/FabioCuccaro/cedoli(-segnalazioni)?(/|$)"
    r"|https://ko-fi\.com/cedoli$"
    r"|mailto:bustachiara\.segnalazioni@proton\.me$"
    r"|https://docs\.astral\.sh/uv/"
    r"|https://docs\.github\.com/"
    r"|https://www\.garanteprivacy\.it/$"
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
        for k in ("src", "href", "poster"):
            v = a.get(k, "")
            if v and not re.match(r"[a-z]+:|#", v):
                self.local.append(v.split("#")[0] or "./")


def test_site_exists():
    assert {p.name for p in PAGES} >= {"index.html", "funzioni.html", "verifica.html", "scarica.html", "sostieni.html", "legale.html"}
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
    home = (DOCS / "index.html").read_text(encoding="utf-8")
    dl = (DOCS / "scarica.html").read_text(encoding="utf-8")
    for html in (home, dl):
        assert re.fullmatch(r"\d+\.\d+\.\d+", re.search(r"<!--versione-->(.*?)<!--/versione-->", html)[1])
        assert "releases/latest/download/Cedoli-windows.zip" in html
    assert re.fullmatch(r"\d+ MB", re.search(r"<!--dimensione-->(.*?)<!--/dimensione-->", home)[1])
    assert re.fullmatch(r"[0-9a-f]{64}", re.search(r"<!--sha256-->(.*?)<!--/sha256-->", dl)[1])
    assert re.fullmatch(r"\d\d/\d\d/\d{4}", re.search(r"<!--data-->(.*?)<!--/data-->", dl)[1])


def test_every_page_has_the_same_menu():
    """Tutte le pagine del sito hanno lo stesso menu in alto, con la pagina corrente segnata."""
    menus = {}
    for page in PAGES:
        html = page.read_text(encoding="utf-8")
        nav = re.search(r'<nav class="menu".*?</nav>', html, re.S)[0]
        menus[page.name] = re.sub(r' aria-current="page"', "", nav)
        if page.name != "index.html":
            assert f'<a href="{page.name}"' in nav and 'aria-current="page"' in nav, page.name
    assert len(set(menus.values())) == 1, menus.keys()


def test_custom_domain():
    """GitHub Pages serve il sito su cedoli.it: il file CNAME arriva nel repo pubblico con docs/."""
    assert (DOCS / "CNAME").read_text(encoding="utf-8").strip() == "cedoli.it"


def test_demo_video_is_local_and_loads_only_on_click():
    """Il video della home sta nel sito e non si scarica finché non si preme play."""
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    video = re.search(r"<video[^>]*>", html)[0]
    assert 'preload="none"' in video and "autoplay" not in video and 'poster="video/' in video
    hero = re.search(r'<section class="hero home">.*?</section>', html, re.S)[0]
    assert "<video" in hero, "il video sta nella prima schermata, accanto al titolo"
    assert (DOCS / "video" / "cedoli-demo.mp4").stat().st_size < 3_000_000


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_page_offers_a_coffee_without_external_images(page):
    """Invito discreto a sostenere il progetto in fondo a ogni pagina, disegnato in CSS e SVG."""
    footer = re.search(r"<footer>.*?</footer>", page.read_text(encoding="utf-8"), re.S)[0]
    assert 'class="btn-cafe" href="https://ko-fi.com/cedoli"' in footer
    assert "<img" not in footer
