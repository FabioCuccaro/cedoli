// Unico script del sito: applica il tema chiaro o scuro scelto (salvato solo in questo browser).
// Non fa richieste di rete: la Content-Security-Policy delle pagine le vieterebbe comunque.
(function () {
  try { var t = localStorage.getItem("bc-tema"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
  document.addEventListener("DOMContentLoaded", function () {
    var sel = document.querySelector("select.theme");
    if (!sel) return;
    sel.value = document.documentElement.dataset.theme || "";
    sel.addEventListener("change", function () {
      if (sel.value) document.documentElement.dataset.theme = sel.value;
      else delete document.documentElement.dataset.theme;
      try { if (sel.value) localStorage.setItem("bc-tema", sel.value); else localStorage.removeItem("bc-tema"); } catch (e) {}
    });
  });
})();
