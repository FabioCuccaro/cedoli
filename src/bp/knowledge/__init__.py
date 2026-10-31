"""Dati di dominio versionati: glossario delle voci per layout, regole fiscali per anno, contratti collettivi."""

from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache
from pathlib import Path

import yaml

from bp.models import Line, Section

BASE = Path(__file__).parent


@dataclass(frozen=True)
class Entry:
    nome: str
    spiega: str
    tipo: str
    flags: frozenset[str] = field(default_factory=frozenset)

    def has(self, flag: str) -> bool:
        return flag in self.flags


UNKNOWN = Entry(
    nome="Voce non in glossario",
    spiega="Significato non determinabile dal documento: chiedere all'ufficio paghe.",
    tipo="sconosciuto",
)

_SECTION_KEYS = {
    Section.VOCI: "voci",
    Section.CONTRIBUTI: "contributi",
    Section.DEDUCIBILI: "deducibili",
    Section.IMPOSTA: "imposta",
    Section.ADDIZIONALI: "addizionali",
}


class Glossary:
    def __init__(self, data: dict):
        self._entries: dict[tuple[str, str], Entry] = {}
        for section, entries in data.items():
            for code, e in (entries or {}).items():
                flags = frozenset(k for k, v in e.items() if v is True)
                self._entries[(section, str(code))] = Entry(e["nome"], e["spiega"].strip(), e["tipo"], flags)

    def get(self, line: Line) -> Entry:
        return self._entries.get((_SECTION_KEYS[line.section], line.code), UNKNOWN)

    def known(self, line: Line) -> bool:
        return (_SECTION_KEYS[line.section], line.code) in self._entries


@cache
def glossary(parser: str) -> Glossary:
    with open(BASE / "glossario" / f"{parser}.yaml", encoding="utf-8") as f:
        return Glossary(yaml.safe_load(f))


def _decimals(obj):
    """I numeri dei file regole diventano Decimal, passando dalla loro forma testuale."""
    if isinstance(obj, dict):
        return {k: _decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimals(v) for v in obj]
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return Decimal(str(obj))
    return obj


@cache
def rules(year: int) -> dict | None:
    path = BASE / "regole" / f"{year}.yaml"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return _decimals(yaml.safe_load(f))


# Senza un contratto riconosciuto si conta solo la tredicesima, che hanno tutti i contratti.
DEFAULT_EXTRA_MONTHS = ({"nome": "tredicesima", "mese": 12},)


@cache
def _contracts() -> tuple[dict, ...]:
    out = []
    for path in sorted((BASE / "contratti").glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            out.append(yaml.safe_load(f))
    return tuple(out)


def contract(ccnl: str | None) -> dict | None:
    """Il contratto collettivo il cui nome compare nel CCNL stampato sul cedolino; None se non è tra quelli noti."""
    if not ccnl:
        return None
    low = ccnl.lower()
    return next((c for c in _contracts() if any(w in low for w in c["riconosci"])), None)
