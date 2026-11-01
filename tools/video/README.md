# Video dimostrativo della home

`docs/video/cedoli-demo.mp4` (e la copertina `cedoli-demo.jpg`) si generano da qui. Le scene sono una pagina HTML,
`demo.html`: ogni fotogramma è la funzione `render(t)` con `t` in secondi, quindi il video si rifà uguale ogni volta
e si modifica come il resto del sito. Serve solo a chi mantiene il sito: l'app e il sito non usano nulla di questa cartella.

Servono Node.js con Playwright e FFmpeg.

1. Avvia l'app su un archivio di cedolini **sintetici** (mai dati veri), per esempio quelli dei test:
   `uv run bp app --cartella <archivio di prova> --porta 8577 --no-browser`.
2. `node cattura.js http://127.0.0.1:8577 <hash di un mese con controlli da guardare>` rifà gli screenshot in `img/`.
3. `node registra.js` scrive il video e la copertina in `docs/video/` (circa un minuto).

Per provare una scena senza registrare, apri `demo.html` nel browser: si anima in tempo reale, e con `?t=14` mostra
quel secondo. La durata è la costante `DURATA` in fondo alla pagina.
