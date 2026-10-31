"""Pagina locale per chi mantiene Busta chiara: le strutture anonime ricevute, raggruppate per formato.

    uv run tools/segnalazioni.py            # apre http://127.0.0.1:8574/

Legge le segnalazioni aperte del repository pubblico busta-chiara-segnalazioni e ne scarica gli
allegati (.json o .zip), più i file messi a mano in data/segnalazioni/email/ (quelli arrivati per
email). Tutto finisce in data/segnalazioni/, che non va mai nel repository. Per ogni formato mostra
il riepilogo di `bp struttura` e con "Prepara bozza" scrive in data/formati/<formato>/ il PDF
sintetico e la bozza del parser.

Questo strumento usa la rete (l'API pubblica di GitHub) e per questo sta fuori dal pacchetto bp:
l'app e l'eseguibile non lo contengono. Con la variabile GITHUB_TOKEN il limite di richieste sale.
"""

import html
import io
import json
import os
import re
import sys
import threading
import urllib.request
import webbrowser
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bp import structure

REPO = "FabioCuccaro/busta-chiara-segnalazioni"
API = f"https://api.github.com/repos/{REPO}/issues?state=open&per_page=100"
ROOT = Path(__file__).resolve().parent.parent / "data"
PORT = 8574
# Allegati delle segnalazioni: GitHub li mette nel testo come link a user-attachments.
ATTACHMENT = re.compile(r"\((https://github\.com/(?:user-attachments/files|[^)]+/files)/[^)]+\.(?:json|zip))\)")


@dataclass
class Item:
    source: str  # "#12" per una segnalazione, "email" per un file messo a mano
    url: str | None
    file: Path
    layout: structure.Layout | None = None
    error: str | None = None


@dataclass
class Group:
    key: str
    items: list[Item] = field(default_factory=list)

    @property
    def layout(self) -> structure.Layout:
        return next(i.layout for i in self.items if i.layout)


def _get(url: str) -> bytes:
    headers = {"User-Agent": "busta-chiara-segnalazioni", "Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


def _jsons(data: bytes, name: str) -> list[tuple[str, bytes]]:
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return [(Path(n).name, z.read(n)) for n in z.namelist() if n.endswith(".json")]
    return [(name, data)]


def download(root: Path = ROOT, get=_get) -> list[str]:
    """Scarica gli allegati delle segnalazioni aperte che non sono ancora in data/segnalazioni/github/."""
    out = root / "segnalazioni" / "github"
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    for issue in json.loads(get(API)):
        if "pull_request" in issue:
            continue
        for k, url in enumerate(ATTACHMENT.findall(issue.get("body") or "")):
            prefix = f"{issue['number']}-{k}"
            if any(out.glob(f"{prefix}-*")):
                continue
            try:
                for n, (name, data) in enumerate(_jsons(get(url), url.rsplit("/", 1)[-1])):
                    (out / f"{prefix}-{n}-{name}").write_bytes(data)
                (out / f"{prefix}.url").write_text(issue["html_url"], encoding="utf-8")
            except Exception as e:  # un allegato rotto non deve fermare gli altri
                errors.append(f"#{issue['number']}: {type(e).__name__} {e}")
    return errors


def collect(root: Path = ROOT) -> list[Group]:
    items = []
    base = root / "segnalazioni"
    for f in sorted((base / "github").glob("*.json")):
        number = f.name.split("-")[0]
        link = base / "github" / f"{number}-{f.name.split('-')[1]}.url"
        items.append(Item(f"#{number}", link.read_text(encoding="utf-8") if link.exists() else None, f))
    for f in sorted((base / "email").glob("*.json")):
        items.append(Item("email", None, f))
    groups: dict[str, Group] = {}
    for item in items:
        try:
            item.layout = structure.analyze(structure.load(item.file))
            key = item.layout.model or item.layout.producer
        except Exception as e:
            item.error, key = f"{type(e).__name__}: {e}", "file non leggibili"
        groups.setdefault(key, Group(key)).items.append(item)
    return sorted(groups.values(), key=lambda g: (g.key == "file non leggibili", -len(g.items), g.key))


def prepare(group: Group, root: Path = ROOT) -> Path:
    """Scrive in data/formati/<formato>/ le strutture, il PDF sintetico e la bozza del parser."""
    layout = group.layout
    name = structure.name(layout) if layout.model else re.sub(r"\W+", "_", group.key.lower()).strip("_")
    out = root / "formati" / name
    out.mkdir(parents=True, exist_ok=True)
    first = next(i for i in group.items if i.layout)
    for i in group.items:
        if i.layout:
            (out / i.file.name).write_bytes(i.file.read_bytes())
    (out / "riepilogo.txt").write_text(structure.describe(layout) + "\n", encoding="utf-8")
    (out / f"{name}_bozza.py").write_text(structure.skeleton(layout), encoding="utf-8")
    try:
        structure.synthesize(structure.load(first.file), out / "sintetico.pdf")
    except ImportError:  # reportlab manca: serve uv sync con le dipendenze di sviluppo
        pass
    return out


PAGE = """<!doctype html><html lang="it"><meta charset="utf-8"><title>Segnalazioni Busta chiara</title>
<style>
:root {{ --bg:#f6f4ef; --surface:#fff; --text:#1c1f24; --muted:#5f6670; --line:#e2ded5; --accent:#23507a; --neg:#b24a33; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#121417; --surface:#1b1e22; --text:#eceae4; --muted:#a3a7ae; --line:#2e3238; --accent:#8cb6e0; --neg:#ec9a85; }} }}
body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); max-width: 60em; margin: 2em auto; padding: 0 16px; }}
.card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 18px; margin: 14px 0; }}
h2 {{ margin: 0 0 4px; font-size: 18px; }} .sub {{ color: var(--muted); margin: 0; }} .bad {{ color: var(--neg); }}
pre {{ white-space: pre-wrap; font-size: 12px; }} a {{ color: var(--accent); }}
button {{ background: var(--accent); color: var(--surface); border: 0; border-radius: 16px; padding: 6px 14px; cursor: pointer; }}
</style>
<h1>Segnalazioni</h1>
<p class="sub">Strutture anonime dal repository <a href="https://github.com/{repo}/issues">{repo}</a> e da data/segnalazioni/email/, raggruppate per formato. {msg}</p>
<p></p>
<form method="post" action="/aggiorna"><button>Scarica le nuove segnalazioni</button></form>
{groups}
</html>"""


def render(groups: list[Group], msg: str = "") -> str:
    cards = []
    for n, g in enumerate(groups):
        sources = ", ".join(f'<a href="{html.escape(i.url)}">{i.source}</a>' if i.url else i.source for i in g.items)
        if g.key == "file non leggibili":
            body = "".join(f'<p class="bad">{html.escape(i.file.name)}: {html.escape(i.error or "")}</p>' for i in g.items)
        else:
            body = (f"<details><summary>Riepilogo del layout</summary><pre>{html.escape(structure.describe(g.layout))}</pre></details>"
                    f'<form method="post" action="/bozza?g={n}"><button>Prepara bozza</button></form>')
        cards.append(f'<div class="card"><h2>{html.escape(g.key)}</h2>'
                     f'<p class="sub">{len(g.items)} {"struttura" if len(g.items) == 1 else "strutture"}: {sources}</p>{body}</div>')
    return PAGE.format(repo=REPO, msg=html.escape(msg),
                       groups="".join(cards) or '<p class="sub">Nessuna struttura ancora.</p>')


class Handler(BaseHTTPRequestHandler):
    root = ROOT
    msg = ""

    def log_message(self, *args):
        pass

    def _page(self):
        body = render(collect(self.root), Handler.msg).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._page()

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/aggiorna":
            try:
                errors = download(self.root)
                Handler.msg = "Aggiornato." + (" Errori: " + "; ".join(errors) if errors else "")
            except Exception as e:
                Handler.msg = f"Non riesco a leggere le segnalazioni: {type(e).__name__} {e}"
        elif url.path == "/bozza":
            groups = collect(self.root)
            out = prepare(groups[int(parse_qs(url.query)["g"][0])], self.root)
            Handler.msg = f"Bozza scritta in {out}"
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.end_headers()


def main() -> None:
    (ROOT / "segnalazioni" / "email").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Segnalazioni su {url} (Ctrl+C per uscire). I JSON arrivati per email vanno in {ROOT / 'segnalazioni' / 'email'}")
    threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
