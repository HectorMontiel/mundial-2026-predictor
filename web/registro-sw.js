// v413 — antes iba en línea dentro de index.html; en un archivo, la política
// de contenido (CSP) puede prohibir TODO script en línea.
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(function () {});
