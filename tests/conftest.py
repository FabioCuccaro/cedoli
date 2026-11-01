"""Garanzia zero rete: durante i test nessun codice può uscire da questo computer.

Un audit hook di Python (``sys.addaudithook``) osserva ogni connessione, invio, risoluzione di nomi
e richiesta ``urllib`` fatta da qualsiasi thread, anche dentro librerie di terze parti. Se la
destinazione non è il computer stesso (127.0.0.1, ::1, localhost) l'operazione viene bloccata e il
test fallisce, anche se il codice provato intercetta l'errore e prosegue. Un ``bind`` su tutte le
interfacce (0.0.0.0) conta come violazione: renderebbe l'app raggiungibile dalla rete locale.

Un audit hook non si può togliere una volta installato, quindi vale per tutta la sessione di test.
"""

import ipaddress
import sys
import threading
from urllib.parse import urlsplit

import pytest

LOCAL_NAMES = {"localhost"}


class NetworkBlocked(RuntimeError):
    """Non è un OSError: un ``except OSError`` nel codice provato non la nasconde."""


_violations: list[str] = []
_lock = threading.Lock()


def _host(value) -> str | None:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    return value if isinstance(value, str) else None


def is_local(host, *, wildcard_ok: bool = False) -> bool:
    host = _host(host)
    if host is None:  # indirizzo non di rete (AF_UNIX) o host assente
        return True
    host = host.strip("[]").split("%")[0].lower()
    if host in LOCAL_NAMES:
        return True
    if host == "":
        return wildcard_ok
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # un nome di dominio da risolvere: uscirebbe verso un DNS
    return ip.is_loopback or (wildcard_ok and ip.is_unspecified)


def _address_host(address):
    if isinstance(address, tuple) and address:
        return address[0]
    return None  # AF_UNIX e simili: restano sul computer


def _block(what: str) -> None:
    with _lock:
        _violations.append(what)
    raise NetworkBlocked(f"Cedolì non deve usare la rete: {what}")


def _audit(event: str, args) -> None:
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        address = args[1] if len(args) > 1 else None
        if not is_local(_address_host(address)):
            _block(f"{event} verso {address!r}")
    elif event == "socket.bind":
        if not is_local(_address_host(args[1])):
            _block(f"socket.bind su {args[1]!r} (fuori da 127.0.0.1)")
    elif event == "socket.getaddrinfo":
        if not is_local(args[0], wildcard_ok=True):
            _block(f"risoluzione del nome {args[0]!r}")
    elif event in ("socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"):
        if not is_local(args[0]):
            _block(f"{event}({args[0]!r})")
    elif event == "urllib.Request":
        url = args[0]
        parts = urlsplit(url)
        if parts.scheme not in ("", "file", "data") and not is_local(parts.hostname):
            _block(f"richiesta urllib a {url}")


sys.addaudithook(_audit)


def take_violations() -> list[str]:
    with _lock:
        taken = list(_violations)
        _violations.clear()
    return taken


@pytest.fixture(autouse=True)
def zero_rete():
    """Ogni test fallisce se durante la sua esecuzione qualcosa ha provato a uscire in rete."""
    take_violations()
    yield
    violations = take_violations()
    if violations:
        pytest.fail("Tentativi di uscire in rete:\n- " + "\n- ".join(violations), pytrace=False)
