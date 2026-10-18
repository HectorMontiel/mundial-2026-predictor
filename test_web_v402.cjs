#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
globalThis.window = globalThis;
require('./web/fechas.js');

const parse = globalThis.SharPicksFechas.aFecha;
assert.equal(parse('2026-10-17T19:30:00Z').toISOString(), '2026-10-17T19:30:00.000Z');
assert.equal(parse('2026-10-17T19:30:00-06:00').toISOString(), '2026-10-18T01:30:00.000Z');
assert.equal(parse('2026-10-17T19:30:00+02:00').toISOString(), '2026-10-17T17:30:00.000Z');
assert.equal(parse('2026-10-17T19:30:00-0600').toISOString(), '2026-10-18T01:30:00.000Z');
assert.equal(parse('2026-10-17 19:30:00').toISOString(), '2026-10-17T19:30:00.000Z');
assert.equal(parse('2026-10-17').toISOString(), '2026-10-17T12:00:00.000Z');
assert.equal(parse('no-es-fecha'), null);
assert.equal(parse(null), null);

const app = fs.readFileSync('web/app.js', 'utf8');
assert.match(app, /const aFecha = window\.SharPicksFechas\.aFecha/);
assert.match(app, /vivoCursor/);
assert.match(app, /errorCombinadas/);
assert.match(app, /respaldoPicks/);
assert.match(app, /No se pudieron consultar las combinadas/);

const cuenta = fs.readFileSync('web/cuenta.js', 'utf8');
assert.match(cuenta, /fetch\(FN \+ 'comentario'/);
assert.doesNotMatch(cuenta, /sb\.from\('comentarios'\)\.insert/);
assert.doesNotMatch(cuenta, /Math\.round\(100 \* tv \/ \(tv \+ tr\)\)/);

const hardening = fs.readFileSync('supabase/v402_bughunter_hardening.sql', 'utf8');
assert.match(hardening, /revoke insert on public\.perfiles from anon, authenticated/);
assert.match(hardening, /telegram_vip_abierto/);
assert.match(hardening, /procesar_vip_unico/);
assert.match(hardening, /registrar_comentario/);
assert.match(hardening, /v_intentos > 5/);

const commentEdge = fs.readFileSync('supabase/functions/comentario/index.ts', 'utf8');
assert.match(commentEdge, /rpc\('registrar_comentario'/);
assert.match(commentEdge, /status: 429/);
assert.match(commentEdge, /const esClavePublica = token === ANON \|\| token\.startsWith\('sb_publishable_'\)/);

const mp = fs.readFileSync('supabase/functions/mp-webhook/index.ts', 'utf8');
const stripe = fs.readFileSync('supabase/functions/stripe-webhook/index.ts', 'utf8');
assert.match(mp, /procesar_vip_unico/);
assert.match(mp, /status: 500/);
assert.match(stripe, /procesar_vip_unico/);
assert.match(stripe, /status: 503/);
console.log('OK: fechas ISO + guardas estáticas de feed, historial, pagos y comentarios');
