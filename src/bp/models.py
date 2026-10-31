"""Schema dati di un cedolino estratto.

Nessun dato personale (nome, codice fiscale, IBAN, indirizzo, date di nascita) entra in
questi modelli: il parser li scarta in memoria.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class Section(StrEnum):
    VOCI = "voci"
    CONTRIBUTI = "contributi"
    DEDUCIBILI = "deducibili"
    IMPOSTA = "imposta"  # es. rate del trattamento integrativo da restituire
    ADDIZIONALI = "addizionali"


class Line(BaseModel):
    """Una riga di una delle tabelle del cedolino, con gli importi nelle colonne in cui sono stampati."""

    section: Section
    code: str
    description: str
    note: str | None = None
    year: int | None = None
    qty: Decimal | None = None
    unit_amount: Decimal | None = None
    base: Decimal | None = None
    rate: Decimal | None = None
    figurative: Decimal | None = None
    deduction: Decimal | None = None
    earning: Decimal | None = None
    deductible: Decimal | None = None
    non_deductible: Decimal | None = None


class Period(BaseModel):
    year: int
    month: int
    kind: str  # come stampato nei metadati: "Mensilita'normale", "Tredicesima", ...


class Contract(BaseModel):
    employer: str | None = None
    ccnl: str | None = None
    qualifica: str | None = None


class LeaveBalance(BaseModel):
    kind: str  # "FERIE" o "R.O.L."
    unit: str | None = None  # None: giorni per le ferie e ore per i ROL, come nel layout PAYLUL01
    maturate: Decimal | None = None
    godute: Decimal | None = None
    residue_ap: Decimal | None = None
    residue_ap2: Decimal | None = None
    saldo: Decimal | None = None


class CheckStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"  # quadratura dell'estrazione non riuscita
    EXPLAINED = "spiegabile"  # differenza con una spiegazione nota
    ANOMALOUS = "anomalo"  # differenza non spiegata
    NOT_VERIFIABLE = "non_verificabile"


class CheckResult(BaseModel):
    check_id: str
    status: CheckStatus
    formula: str
    expected: Decimal | None = None  # valore stampato nel cedolino
    actual: Decimal | None = None  # valore ricalcolato
    title: str | None = None
    detail: str | None = None


class Payslip(BaseModel):
    file_sha256: str
    parser: str
    parser_version: str
    pages: int
    period: Period
    contract: Contract
    salary_elements: dict[str, Decimal] = Field(default_factory=dict)
    days: dict[str, Decimal] = Field(default_factory=dict)
    lines: list[Line] = Field(default_factory=list)
    # Blocchi riassuntivi in fondo al cedolino, per chiave normalizzata (vedi parser).
    summary: dict[str, Decimal] = Field(default_factory=dict)
    leave: list[LeaveBalance] = Field(default_factory=list)
    # Quadrature dell'estrazione (bp.validate) e controlli di coerenza (bp.rules).
    checks: list[CheckResult] = Field(default_factory=list)
    coherence: list[CheckResult] = Field(default_factory=list)

    @property
    def extraction_ok(self) -> bool:
        return all(c.status == CheckStatus.OK for c in self.checks)

    def amount(self, key: str) -> Decimal:
        return self.summary.get(key, Decimal("0"))
