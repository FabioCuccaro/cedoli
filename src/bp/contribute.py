"""Come far arrivare la struttura anonima di un formato nuovo a chi mantiene Cedolì.

L'app non invia mai nulla: prepara solo i link a un'email o a una segnalazione su GitHub già
compilate. L'utente salva il file, lo apre, lo controlla e lo allega lui, dal suo programma di posta
o dal browser. Nei testi precompilati non finisce nulla del cedolino: né importi né nomi.
"""

from urllib.parse import quote, urlencode

from bp import __version__

# Repository pubblico solo per le segnalazioni: il codice resta privato.
REPO = "https://github.com/FabioCuccaro/cedoli-segnalazioni"
# Indirizzo a cui mandare le strutture anonime. Vuoto: l'app propone solo la segnalazione su GitHub.
EMAIL = "bustachiara.segnalazioni@proton.me"
# Nome della pagina Ko-fi per le donazioni volontarie. Vuoto: l'app non mostra il link.
KOFI = "busta_chiara"

SUBJECT = "Cedolì: nuovo formato di busta paga"
TEXT = (
    "Ciao,\n\n"
    "allego la struttura anonima (struttura_anonima.json) di una busta paga che Cedolì "
    f"{__version__} non sa ancora leggere. L'ho aperta e controllata: non contiene importi né dati personali.\n\n"
    "Gestionale o portale da cui arriva il cedolino (se lo sai): \n"
)
# Né i link mailto né quelli di GitHub possono allegare file: il promemoria in cima evita invii senza allegato.
BODY = ">>> PRIMA DI INVIARE: allega il file struttura_anonima.json che hai salvato dall'app (di solito è in Download). <<<\n\n" + TEXT
ISSUE_BODY = (">>> PRIMA DI CREARE LA SEGNALAZIONE: trascina in questo riquadro il file struttura_anonima.json "
              "(di solito è in Download), oppure usa \"Paste, drop, or click to add files\" qui sotto. "
              "Se GitHub non lo accetta, comprimilo in .zip. <<<\n\n" + TEXT)


def links() -> dict[str, str]:
    """Link per mandare il file: sempre la segnalazione su GitHub, l'email solo se configurata."""
    out = {"issue": f"{REPO}/issues/new?" + urlencode(
        {"template": "nuovo-formato.md", "title": SUBJECT, "body": ISSUE_BODY}, quote_via=quote)}
    if EMAIL:
        out["email"] = f"mailto:{EMAIL}?" + urlencode({"subject": SUBJECT, "body": BODY}, quote_via=quote)
    return out


def donate_url() -> str:
    """Link alle donazioni volontarie, "" finché la pagina Ko-fi non è configurata. È un normale link: si apre solo se l'utente ci clicca."""
    return f"https://ko-fi.com/{quote(KOFI)}" if KOFI else ""
