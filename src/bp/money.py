"""Parsing di importi e numeri come stampati nei cedolini italiani."""

import re
from decimal import Decimal

# "1.234,56", "-5.826,00", "126,37385"
_IT = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d+$|^-?\d+,\d+$")
# Alcuni campi sono stampati con il punto decimale: "3207.4"
_DOT = re.compile(r"^-?\d+\.\d{1,2}$")
_YEAR = re.compile(r"^(19|20)\d{2}$")


def is_amount(text: str) -> bool:
    return bool(_IT.match(text) or _DOT.match(text))


def is_year(text: str) -> bool:
    return bool(_YEAR.match(text))


def parse_amount(text: str) -> Decimal:
    """Converte un importo stampato in Decimal, senza passare da float."""
    if _IT.match(text):
        return Decimal(text.replace(".", "").replace(",", "."))
    if _DOT.match(text):
        return Decimal(text)
    raise ValueError(f"importo non riconosciuto: {text!r}")
