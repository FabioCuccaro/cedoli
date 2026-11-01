"""Garanzia zero rete, controllo statico: il codice dell'app non importa librerie di rete o telemetria.

Il blocco a run time di ``conftest.py`` vede solo il codice che i test eseguono. Questo controllo legge
tutti i file di ``src/bp`` e l'avvio dell'eseguibile (``packaging/Cedoli.py``) e fallisce se
compare un modulo di rete fuori dall'elenco ammesso, un import dinamico o un indirizzo fuori da
127.0.0.1. Controlla anche le dipendenze dichiarate in ``pyproject.toml``.

``tools/`` resta fuori: ``tools/segnalazioni.py`` usa la rete di proposito e non fa parte dell'app.
"""

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP_FILES = sorted((ROOT / "src" / "bp").rglob("*.py")) + [ROOT / "packaging" / "Cedoli.py"]

# Moduli della libreria standard e librerie note che parlano con la rete, o servono a farlo.
NETWORK = {
    "socket", "ssl", "socketserver", "asyncio", "selectors", "select",
    "http", "urllib.request", "urllib.error", "urllib.response", "urllib.robotparser",
    "ftplib", "smtplib", "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc", "email.mime",
    "webbrowser", "wsgiref", "mailbox", "subprocess", "multiprocessing.connection", "ctypes",
    "requests", "httpx", "urllib3", "aiohttp", "httplib2", "pycurl", "websocket", "websockets",
    "grpc", "paramiko", "boto3", "botocore", "google", "azure", "dns", "zmq", "pika",
    "sentry_sdk", "posthog", "mixpanel", "analytics", "segment", "rollbar", "bugsnag", "honeybadger",
    "opentelemetry", "datadog", "ddtrace", "newrelic", "statsd", "prometheus_client", "logging.handlers",
}

# Le sole eccezioni, una per una e motivate. Tutte in app.py, che è il server locale.
ALLOWED = {
    ("app.py", "http"): "HTTPStatus, solo costanti dei codici di risposta",
    ("app.py", "http.server"): "server dell'app, in ascolto solo su 127.0.0.1 (make_server)",
    ("app.py", "urllib.request"): "chiede all'app già aperta su 127.0.0.1 versione e chiusura, senza proxy",
    ("app.py", "webbrowser"): "apre la pagina http://127.0.0.1:<porta>/ nel browser dell'utente",
}

URL = re.compile(r"\b(?:https?|wss?|ftp)://[^\s\"'<>]*", re.I)
# Indirizzi ammessi nei testi del codice: il computer stesso e i link che l'utente apre da sé.
ALLOWED_URLS = ("http://127.0.0.1", "https://github.com/FabioCuccaro/cedoli-segnalazioni", "https://ko-fi.com/", "http://www.w3.org/2000/svg")


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module
            for alias in node.names:  # from urllib import request: il sottomodulo conta da sé
                if f"{node.module}.{alias.name}" in NETWORK:
                    yield node.lineno, f"{node.module}.{alias.name}"


def _is_network(module: str) -> str | None:
    parts = module.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in NETWORK:
            return ".".join(parts[:i])
    return None


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_app_code_imports_no_network_library():
    problems = []
    for path in APP_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for line, module in _imports(tree):
            hit = _is_network(module)
            if hit and (path.name, module) not in ALLOWED:
                problems.append(f"{_name(path)}:{line} importa {module} (rete: {hit})")
    assert not problems, "\n".join(problems)


def test_no_dynamic_imports_or_code_execution():
    """Un import fatto con una stringa sfuggirebbe al controllo qui sopra."""
    problems = []
    for path in APP_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name in {"__import__", "import_module", "exec", "eval", "spec_from_file_location", "system", "popen"}:
                    problems.append(f"{_name(path)}:{node.lineno} chiama {name}()")
    assert not problems, "\n".join(problems)


def test_exceptions_are_still_needed():
    """Un'eccezione che non serve più va tolta, così l'elenco resta corto e vero."""
    used = set()
    for path in APP_FILES:
        for _, module in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            used.add((path.name, module))
    assert set(ALLOWED) <= used, set(ALLOWED) - used


def test_app_addresses_are_local_or_user_clicked_links():
    files = APP_FILES + sorted((ROOT / "src" / "bp" / "report" / "templates").glob("*"))
    problems = []
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for url in URL.findall(line):
                if not url.startswith(ALLOWED_URLS):
                    problems.append(f"{_name(path)}:{n} {url}")
    assert not problems, "\n".join(problems)


def test_server_listens_only_on_this_computer():
    tree = ast.parse((ROOT / "src" / "bp" / "app.py").read_text(encoding="utf-8"))
    hosts = [n.elts[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Tuple) and len(n.elts) == 2 and isinstance(n.elts[0], ast.Constant)
             and isinstance(n.elts[0].value, str)]
    assert hosts and set(hosts) == {"127.0.0.1"}, hosts


def test_dependencies_contain_no_network_library():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = [re.split(r"[\s<>=!~;\[]", d, maxsplit=1)[0].lower().replace("-", "_") for d in project["dependencies"]]
    assert names == ["jinja2", "pdfplumber", "pydantic", "pyyaml", "typer"], (
        "Dipendenze cambiate: controlla che la nuova non usi la rete, poi aggiorna questo elenco")
    assert not [n for n in names if _is_network(n)]


def test_checker_catches_network_code(tmp_path):
    bad = ast.parse("import requests\nfrom urllib import request\nimport sentry_sdk.integrations\n"
                    "from http.client import HTTPSConnection\nimport json\n")
    hits = [m for _, m in _imports(bad) if _is_network(m)]
    assert {"requests", "urllib.request", "sentry_sdk.integrations", "http.client"} <= set(hits)
    assert "json" not in hits and not _is_network("urllib.parse")
