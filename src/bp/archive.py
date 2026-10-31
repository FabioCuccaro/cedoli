"""Archivio locale dei cedolini caricati: i PDF in una cartella dell'utente, letti una volta per sessione."""

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from bp import history
from bp.models import Payslip

APP_DIR_NAME = "BustaPagaBeautify"


def default_dir() -> Path:
    """La cartella dei dati personali dell'utente: mai dentro il programma, mai in rete."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_DIR_NAME


@dataclass
class Added:
    payslip: Payslip | None
    message: str
    new: bool = False
    new_format: bool = False  # busta paga di un formato non ancora supportato: si può esportarne la struttura anonima


class Archive:
    def __init__(self, root: Path):
        self.root = root
        self.pdfs = root / "cedolini"
        self.pdfs.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Payslip] = {}
        self._errors: dict[str, str] = {}
        self._new_format: set[str] = set()

    def _path(self, sha: str) -> Path:
        return self.pdfs / f"{sha}.pdf"

    def _load(self, sha: str) -> Payslip | None:
        from bp.cli import import_file

        if sha not in self._cache and sha not in self._errors:
            try:
                self._cache[sha] = import_file(self._path(sha))
            except ValueError as e:
                self._errors[sha] = str(e)
                if getattr(e, "new_format", False):
                    self._new_format.add(sha)
            except Exception as e:  # un file solo non deve mai bloccare l'archivio intero
                self._errors[sha] = f"errore imprevisto nella lettura ({type(e).__name__})"
        return self._cache.get(sha)

    def add(self, data: bytes) -> Added:
        if not data.startswith(b"%PDF"):
            return Added(None, "non è un PDF: carica il file PDF del cedolino")
        sha = hashlib.sha256(data).hexdigest()
        path = self._path(sha)
        if path.exists() and (p := self._load(sha)):
            return Added(p, "già presente")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        self._errors.pop(sha, None)
        p = self._load(sha)
        if p is None:  # layout non riconosciuto: non teniamo un file che non sappiamo leggere
            path.unlink(missing_ok=True)
            new_format = sha in self._new_format
            self._new_format.discard(sha)
            return Added(None, self._errors.pop(sha), new_format=new_format)
        return Added(p, "caricato" if p.extraction_ok else "caricato, ma la lettura non quadra", new=True)

    def _exists(self, sha: str) -> bool:
        return len(sha) == 64 and all(c in "0123456789abcdef" for c in sha) and self._path(sha).exists()

    def get(self, sha: str) -> Payslip | None:
        return self._load(sha) if self._exists(sha) else None

    def all(self) -> list[Payslip]:
        found = [self._load(f.stem) for f in sorted(self.pdfs.glob("*.pdf"))]
        return history.ordered([p for p in found if p is not None])

    def unreadable(self) -> dict[str, str]:
        """File nell'archivio che non si riescono a leggere (per esempio rovinati, o messi a mano nella cartella)."""
        for f in self.pdfs.glob("*.pdf"):
            self._load(f.stem)
        return {sha: msg for sha, msg in sorted(self._errors.items()) if self._path(sha).exists()}

    def remove(self, sha: str) -> bool:
        if not self._exists(sha):
            return False
        self._path(sha).unlink()
        self._cache.pop(sha, None)
        self._errors.pop(sha, None)
        return True
