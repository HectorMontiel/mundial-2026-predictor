// v402 — parser ISO probado también fuera del navegador (test_web_v402.cjs).
// Las fechas locales de los JSON históricos se interpretan como UTC; si el dato ya
// trae Z u offset ±HH, ±HHMM o ±HH:MM se respeta y no se le agrega otra zona.
(function (root) {
  'use strict';

  function aFecha(s) {
    if (!s) return null;
    let t = String(s).trim().replace(' ', 'T');
    if (/^\d{4}-\d{2}-\d{2}$/.test(t)) t += 'T12:00:00';
    const tieneZona = /[zZ]|[+-]\d{2}(?::?\d{2})?$/.test(t.slice(10));
    const d = new Date(t + (tieneZona ? '' : 'Z'));
    return Number.isNaN(d.getTime()) ? null : d;
  }

  root.SharPicksFechas = Object.assign(root.SharPicksFechas || {}, { aFecha });
})(typeof window !== 'undefined' ? window : globalThis);
