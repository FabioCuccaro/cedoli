// Registra demo.html in docs/video/cedoli-demo.mp4 (più l'immagine di copertina). Vedi README.md qui accanto.
// Uso: node registra.js [fotogrammi al secondo, default 30]
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const fps = +(process.argv[2] || 30);
const out = path.join(__dirname, '..', '..', 'docs', 'video');
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 720 } });
  await p.goto('file://' + path.join(__dirname, 'demo.html') + '?fermo', { waitUntil: 'load' });
  const durata = await p.evaluate(() => DURATA);
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '30', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
    path.join(out, 'cedoli-demo.mp4')], { stdio: ['pipe', 'inherit', 'inherit'] });
  for (let i = 0; i < durata * fps; i++) {
    await p.evaluate(t => render(t), i / fps);
    const png = await p.screenshot({ type: 'png' });
    if (!ff.stdin.write(png)) await new Promise(r => ff.stdin.once('drain', r));
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  // Copertina: il report del mese a riposo, senza cursore né cerchi (il video sta accanto al titolo nella home).
  await p.evaluate(() => render(9.5));
  await p.screenshot({ path: path.join(out, 'cedoli-demo.jpg'), type: 'jpeg', quality: 82 });
  await b.close();
})();
