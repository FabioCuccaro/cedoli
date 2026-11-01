// Screenshot dell'app (con cedolini sintetici) usati dalle scene del video. Vedi README.md qui accanto.
// Uso: node cattura.js [indirizzo dell'app, default http://127.0.0.1:8577] [hash del mese con controlli da guardare]
const { chromium } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8577';
const mese = process.argv[3];
(async () => {
  const b = await chromium.launch();
  const shots = [['elenco', '/', 760, false], ['mese', '/mese/' + mese, 900, true], ['storico', '/storico', 900, true]];
  for (const [name, path, h, full] of shots) {
    const p = await b.newPage({ viewport: { width: 1100, height: h }, deviceScaleFactor: 2, colorScheme: 'light' });
    await p.goto(base + path, { waitUntil: 'networkidle' });
    // Il pulsante fisso "Le tue buste paga" finirebbe a metà della pagina intera.
    await p.addStyleTag({ content: 'a[style*="position:fixed"] { display: none !important; }' });
    await p.screenshot({ path: __dirname + '/img/' + name + '.png', fullPage: full });
    await p.close();
  }
  await b.close();
})();
