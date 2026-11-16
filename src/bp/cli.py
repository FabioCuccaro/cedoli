"""Riga di comando `bp`."""

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

import typer

from bp import __version__, extract, partial
from bp.parsers import find_parser
from bp.rules import check
from bp.validate import reconcile

app = typer.Typer(help="Analisi locale delle buste paga. Nessun dato esce dal computer.", no_args_is_help=True)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"Cedolì {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Mostra la versione ed esce"),
) -> None:
    pass


# Per i PDF protetti quando non c'è un terminale a cui chiedere la password (per esempio in uno script).
PASSWORD_ENV = "CEDOLI_PASSWORD"
PASSWORD_ATTEMPTS = 3
# Password che hanno già aperto un file in questo comando: di solito i cedolini hanno tutti la stessa.
# Solo in memoria, per la durata del comando.
_passwords: list[str] = []


def _interactive() -> bool:
    return sys.stdin.isatty()


def with_password[T](read: Callable[[Path, str | None], T], path: Path) -> T:
    """Chiama `read(path, password)`. Se il PDF è protetto prova la variabile CEDOLI_PASSWORD e le
    password già usate in questo comando, poi la chiede sul terminale senza mostrarla.

    La password non è un'opzione del comando: resterebbe nella cronologia della shell.
    """
    try:
        return read(path, None)
    except extract.PasswordNeeded:
        pass
    known = ([os.environ[PASSWORD_ENV]] if os.environ.get(PASSWORD_ENV) else []) + _passwords
    for password in known:
        try:
            return read(path, password)
        except extract.PasswordNeeded:
            pass
    if not _interactive():
        raise extract.PasswordNeeded(
            wrong=bool(known),
            hint=f"lancia il comando da un terminale per scriverla, oppure mettila nella variabile {PASSWORD_ENV}")
    for _ in range(PASSWORD_ATTEMPTS):
        password = typer.prompt(f"Password di {path.name} (Invio per saltarlo)", default="", hide_input=True,
                                show_default=False, err=True)
        if not password:
            break
        try:
            result = read(path, password)
        except extract.PasswordNeeded:
            typer.echo("  la password non apre questo PDF", err=True)
            continue
        _passwords.append(password)
        return result
    raise extract.PasswordNeeded(hint="saltato")


def import_file(path: Path, password: str | None = None):
    """Legge un cedolino. Qualsiasi problema diventa un ReadError con un messaggio leggibile."""
    doc = extract.load(path, password)
    parser = find_parser(doc)
    try:
        payslip = parser.parse(doc)
        payslip.checks = reconcile(payslip)
        payslip.coherence = check(payslip)
    except Exception as e:  # un caso che il parser non prevede non deve fermare l'app
        detail = str(e).splitlines()[0][:200] if isinstance(e, ValueError) and str(e) else type(e).__name__
        raise extract.ReadError(
            f"formato {parser.NAME} riconosciuto, ma la lettura si è interrotta ({detail}): "
            f"probabilmente è un caso che Cedolì non conosce ancora{partial.note(doc)}",
            new_format=True,
        ) from e
    return payslip


@app.command("import")
def import_cmd(
    pdf: list[Path] = typer.Argument(..., exists=True, dir_okay=False, help="Uno o più cedolini PDF"),
    out: Path | None = typer.Option(None, "--out", "-o", help="Cartella in cui scrivere i JSON"),
) -> None:
    """Estrae il cedolino e verifica la quadratura. Stampa il JSON o lo scrive in --out."""
    failed = False
    for path in pdf:
        try:
            payslip = with_password(import_file, path)
        except ValueError as e:  # layout non riconosciuto o non leggibile
            typer.echo(f"✗ {path.name}: {e}", err=True)
            failed = True
            continue
        status = "✓ quadra" if payslip.extraction_ok else "✗ NON quadra"
        p = payslip.period
        typer.echo(f"{status}  {p.year}-{p.month:02d} {p.kind}  ({path.name})", err=True)
        failed |= not payslip.extraction_ok
        data = payslip.model_dump_json(indent=2)
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{p.year}-{p.month:02d}_{payslip.file_sha256[:8]}.json").write_text(data, encoding="utf-8")
        elif len(pdf) == 1:
            typer.echo(data)
    raise typer.Exit(1 if failed else 0)


@app.command()
def report(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", "-o", help="File HTML da scrivere"),
) -> None:
    """Scrive il report HTML del cedolino: voci spiegate, dal lordo al netto, controlli."""
    from bp.report import render

    try:
        payslip = with_password(import_file, pdf)
    except ValueError as e:
        typer.echo(f"✗ {pdf.name}: {e}", err=True)
        raise typer.Exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payslip), encoding="utf-8")
    anomalies = [c for c in payslip.coherence if c.status == "anomalo"]
    typer.echo(f"Scritto {out}" + (f" ({len(anomalies)} controlli con differenze)" if anomalies else ""), err=True)
    raise typer.Exit(0 if payslip.extraction_ok else 1)


@app.command()
def storico(
    pdf: list[Path] = typer.Argument(..., exists=True, dir_okay=False, help="I cedolini PDF, in qualsiasi ordine"),
    out: Path = typer.Option(..., "--out", "-o", help="File HTML da scrivere"),
) -> None:
    """Scrive un'unica pagina con tutti i cedolini: grafico mese per mese, navigazione e confronto col mese prima."""
    from bp.report import render_history

    payslips, failed = [], False
    for path in pdf:
        try:
            payslip = with_password(import_file, path)
        except ValueError as e:  # un file illeggibile non blocca lo storico
            typer.echo(f"✗ {path.name}: {e}", err=True)
            failed = True
            continue
        if not payslip.extraction_ok:
            typer.echo(f"✗ {path.name}: la lettura non quadra, lo includo segnalandolo", err=True)
            failed = True
        payslips.append(payslip)
    if not payslips:
        typer.echo("Nessun cedolino leggibile: storico non scritto.", err=True)
        raise typer.Exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_history(payslips), encoding="utf-8")
    typer.echo(f"Scritto {out} con {len(payslips)} cedolini", err=True)
    raise typer.Exit(1 if failed else 0)


@app.command("app")
def app_cmd(
    cartella: Path | None = typer.Option(None, "--cartella", help="Dove tenere l'archivio dei cedolini (predefinita: la cartella dati dell'utente)"),
    porta: int = typer.Option(8573, "--porta", help="Porta locale; se è occupata se ne usa una libera, 0 ne sceglie sempre una libera"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Non aprire il browser"),
) -> None:
    """Apre l'app nel browser: trascini i PDF e vedi report e storico. Il server è raggiungibile solo da questo computer."""
    from bp.app import serve

    serve(cartella, porta, not no_browser)


@app.command()
def verifica(
    pdf: list[Path] = typer.Argument(..., exists=True, help="Cedolini PDF o cartelle che li contengono"),
    istantanea: Path = typer.Option(Path("data/verifica.json"), "--istantanea", help="File dell'istantanea (contiene importi reali: tienilo in data/)"),
    aggiorna: bool = typer.Option(False, "--aggiorna", help="Sostituisce l'istantanea con la lettura di oggi"),
) -> None:
    """Rilegge i cedolini e segnala ogni cambiamento rispetto all'istantanea salvata. Da usare prima di un rilascio."""
    from bp.verify import collect, compare, snapshot

    now: dict[str, dict] = {}
    for path in collect(pdf):
        try:
            payslip = with_password(import_file, path)
        except ValueError as e:
            typer.echo(f"✗ {path.name}: {e}", err=True)
            continue
        now[payslip.file_sha256] = snapshot(payslip, path.name)
    anomalies = sum(s == "anomalo" for v in now.values() for s in v["controlli"].values())
    typer.echo(f"{len(now)} cedolini letti, {sum(not v['quadra'] for v in now.values())} non quadrano, "
               f"{anomalies} controlli con differenze non spiegate", err=True)

    if istantanea.exists() and not aggiorna:
        changes = compare(json.loads(istantanea.read_text(encoding="utf-8")), now)
        for line in changes:
            typer.echo(line)
        typer.echo("Nessun cambiamento rispetto all'istantanea." if not changes else
                   f"{len(changes)} cambiamenti: se sono voluti, rilancia con --aggiorna.", err=True)
        raise typer.Exit(1 if changes else 0)
    istantanea.parent.mkdir(parents=True, exist_ok=True)
    istantanea.write_text(json.dumps(now, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    typer.echo(f"Istantanea salvata in {istantanea}", err=True)


@app.command()
def anonimo(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", "-o", help="File JSON da scrivere"),
) -> None:
    """Scrive la struttura anonima del PDF: posizioni e intestazioni, ogni cifra 9, nomi e indirizzi X.

    Serve per far supportare un formato nuovo senza condividere il cedolino. Controlla il file prima di inviarlo.
    """
    from bp.anonymize import anonymize

    try:
        dump = anonymize(with_password(extract.load, pdf))
    except ValueError as e:
        typer.echo(f"✗ {pdf.name}: {e}", err=True)
        raise typer.Exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"Scritto {out}: aprilo e controlla che non ci sia nulla di personale prima di condividerlo", err=True)


@app.command()
def struttura(
    json_file: Path = typer.Argument(..., exists=True, dir_okay=False, help="struttura_anonima.json ricevuta"),
    pdf: Path | None = typer.Option(None, "--pdf", help="Rigenera un PDF sintetico con lo stesso layout"),
    parser: Path | None = typer.Option(None, "--parser", help="Scrive la bozza del modulo parser"),
) -> None:
    """Analizza la struttura anonima di un formato nuovo: riepilogo del layout, PDF sintetico, bozza del parser.

    Per chi mantiene Cedolì. Il PDF sintetico richiede le dipendenze di sviluppo (uv sync).
    """
    from bp import structure

    try:
        doc = structure.load(json_file)
    except (ValueError, KeyError) as e:
        typer.echo(f"✗ {json_file.name}: {e}", err=True)
        raise typer.Exit(1)
    layout = structure.analyze(doc)
    typer.echo(structure.describe(layout))
    if pdf:
        structure.synthesize(doc, pdf)
        typer.echo(f"Scritto {pdf}", err=True)
    if parser:
        parser.write_text(structure.skeleton(layout), encoding="utf-8")
        typer.echo(f"Scritto {parser}: completa parse(), registralo in parsers/__init__.py e aggiungi i test", err=True)


@app.command()
def inspect(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False),
    out: Path = typer.Option(..., "--out", "-o", help="File JSON in cui scrivere parole e coordinate"),
) -> None:
    """Scrive su disco testo, coordinate e metadati del PDF, per studiare un layout nuovo in locale.

    L'output contiene i dati del cedolino così come sono: tienilo in data/ e non condividerlo.
    """
    try:
        doc = with_password(extract.load, pdf)
    except ValueError as e:
        typer.echo(f"✗ {pdf.name}: {e}", err=True)
        raise typer.Exit(1)
    dump = {
        "metadata": doc.metadata,
        "pages": [
            [{"top": round(r.top, 1), "words": [[w.text, round(w.x0, 1), round(w.x1, 1)] for w in r.words]}
             for r in page]
            for page in doc.pages
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"Scritto {out}", err=True)
