# Novità di Busta chiara

Le versioni seguono `MAGGIORE.MINORE.CORREZIONE`. Il numero in uso si vede in fondo all'app e con `bp --version`.

## 0.6.0 (31/10/2026)

- Busta chiara ha una licenza scritta (`LICENZA.md`, anche dentro lo zip): l'app è gratuita per uso personale e si può passare ad altri così com'è; il codice si può leggere per verificarla, ma non riutilizzare.
- L'avviso in fondo alle pagine dice più chiaramente che le spiegazioni sono indicative e non sono consulenza del lavoro né fiscale, e a chi rivolgersi per una verifica.
- In fondo all'app c'è il link per una donazione volontaria su Ko-fi (ko-fi.com/busta_chiara). Come gli altri link, si apre solo se lo clicchi.

## 0.5.0 (31/10/2026)

- Spiegazioni delle voci riviste sui cedolini reali: retribuzione a 26 giorni, buoni pasto, TFR al fondo, quote annuali Qu.A.S. e Quadrifor (a gennaio o nel mese di assunzione), ente bilaterale, rimborso internet, conguaglio contributivo, trattamento integrativo, esonero contributivo 2023 e 2024 distinti. Sotto ogni elenco di voci il report ricorda che le spiegazioni sono indicative e che fanno fede i numeri.
- La garanzia che nessun dato esca dal computer ora è provata a ogni modifica: i test falliscono se l'app, i report o le esportazioni provano a usare la rete, o se una pagina prova a caricare qualcosa da Internet.
- Un secondo controllo legge il codice dell'app e l'eseguibile e fallisce se vi compare una libreria di rete o di telemetria.
- Nuove istruzioni, nel README e in `LEGGIMI.txt` dentro lo zip, per verificare da soli che Busta chiara non usi la rete: modalità aereo, firewall di Windows, Monitoraggio risorse, strumenti del browser.
- Le mensilità aggiuntive dipendono dal contratto collettivo, descritto in un file dati: terziario (quattordicesima a giugno e tredicesima) e metalmeccanici (solo tredicesima). Con un contratto non riconosciuto la stima della detrazione del mese conta solo la tredicesima, e il report lo dice invece di dare un risultato sbagliato in silenzio.

## 0.4.0 (31/10/2026)

- Per una busta paga di un formato non ancora supportato il messaggio riporta comunque totale competenze, totale trattenute e netto, se li trova, e dice se tornano tra loro. Il cedolino non viene archiviato.
- Dopo *Salva struttura anonima* l'app mostra cosa contiene il file, per controllarlo, e i link per mandarlo a mano: segnalazione su GitHub già compilata o email a bustachiara.segnalazioni@proton.me. L'app non invia nulla da sola: il file va allegato a mano, e il messaggio lo ricorda in cima.
- Nuovo comando `bp struttura`, per chi mantiene l'app: da una struttura anonima ricevuta ricava il riepilogo del layout, un PDF sintetico con lo stesso layout e la bozza del parser.
- Dopo un aggiornamento, se la versione precedente è ancora aperta, `bp app` (o il doppio clic) la chiude e avvia la nuova, invece di riaprire quella vecchia.
- Per chi mantiene l'app: `uv run tools/segnalazioni.py` apre una pagina locale che scarica le strutture anonime dalle segnalazioni del repository pubblico, le raggruppa per formato e prepara la bozza del parser. Sta fuori dall'app, che resta senza accesso alla rete.

## 0.3.0 (31/10/2026)

- Un PDF rovinato, troncato o protetto da password non blocca più l'app: viene rifiutato con un messaggio che dice cosa fare.
- Messaggi distinti per scansioni senza testo, file che non sono buste paga e buste paga di formati non ancora supportati.
- I file illeggibili già presenti nell'archivio compaiono a parte e si possono rimuovere.
- Quando un controllo non torna, il riepilogo del mese lo mette in evidenza con la differenza in euro, spiega cosa può voler dire e cosa fare.
- Per una busta paga di un formato non ancora supportato, *Salva struttura anonima* scarica la sola forma del PDF, senza dati personali, da mandare per farlo supportare.
- La versione dell'app si vede in fondo a ogni pagina e con `bp --version`.

## 0.2.0 (20/10/2026)

- Nuovo nome e aspetto: Busta chiara, logo "busta e grafico", tema chiaro e scuro a scelta.
- Secondo formato di cedolino: HR1LULDIP (Zucchetti), con regole 2023 e 2024.
- Cambio di azienda nello stesso anno: cedolini, confronti e detrazioni separati per datore di lavoro.
- Tasto *Chiudi l'app* e filtro per anno nello storico.

## 0.1.0 (17/10/2026)

- Prima versione per Windows: app nel browser con elenco, report del mese e storico.
- Formato PAYLUL01, controlli di coerenza con le regole 2025 e 2026, detrazione per lavoro dipendente mese per mese.
- *Scarica storico* per tenere lo storico su un NAS o un altro dispositivo.
