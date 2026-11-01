"""Avvio dell'eseguibile: con doppio clic apre l'app, con argomenti si comporta come `bp`."""

import sys
import traceback

from bp.cli import app

if __name__ == "__main__":
    double_click = len(sys.argv) == 1
    if double_click:
        sys.argv.append("app")
    try:
        app()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        if double_click:  # senza questa pausa la finestra si chiuderebbe prima di poter leggere l'errore
            input("\nSi è verificato un errore. Premi Invio per chiudere.")
        sys.exit(1)
