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

const negocio = fs.readFileSync('web/negocio.sql', 'utf8');
assert.doesNotMatch(negocio, /\bas \$(?:\s|$)/m, 'negocio.sql no debe abrir funciones con un delimitador SQL incompleto');
assert.doesNotMatch(negocio, /^\s*\$;\s*$/m, 'negocio.sql no debe cerrar funciones con un delimitador SQL incompleto');
assert.equal((negocio.match(/\$\$/g) || []).length % 2, 0, 'delimitadores $ balanceados en negocio.sql');
const hardening = fs.readFileSync('supabase/v402_bughunter_hardening.sql', 'utf8');
assert.match(hardening, /revoke insert on public\.perfiles from anon, authenticated/);
assert.match(hardening, /telegram_vip_abierto/);
assert.match(hardening, /procesar_vip_unico/);
assert.match(hardening, /registrar_comentario/);
assert.match(hardening, /v_intentos > 5/);
const commentsCutover = fs.readFileSync('supabase/v405_comentarios_solo_edge.sql', 'utf8');
assert.match(commentsCutover, /revoke insert on public\.comentarios from public, anon, authenticated/);
assert.match(commentsCutover, /drop policy if exists "cualquiera deja comentario"/);
assert.match(hardening, /Compatibilidad de despliegue/);

assert.equal((hardening.match(/create or replace function public\.registrar_comentario/g) || []).length, 1);
assert.equal((hardening.match(/-- SHP-014:/g) || []).length, 1);
assert.match(hardening, /if p_id is null or length\(p_id\) <> 44 or left\(p_id, 8\) <> 'reserva:'\s+or p_usuario is null or p_precio is null or p_precio <= 0 then/);
assert.doesNotMatch(hardening, /^\s*as \$(?:\s|$)/m);
const dollarTags = [...hardening.matchAll(/\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$/g)].map(m => m[0]);
for (const tag of new Set(dollarTags)) {
  assert.equal(dollarTags.filter(x => x === tag).length % 2, 0, 'delimitador SQL balanceado: ' + tag);
}

assert.match(hardening, /pg_advisory_xact_lock/);
assert.match(hardening, /reservar_lugar_fundador/);
assert.match(hardening, /estado in \('authorized', 'pagado'\)/);
const vipEdge = fs.readFileSync('supabase/functions/vip/index.ts', 'utf8');
const stripeEdge = fs.readFileSync('supabase/functions/stripe/index.ts', 'utf8');
assert.match(vipEdge, /rpc\('reservar_lugar_fundador'/);
assert.match(stripeEdge, /rpc\('reservar_lugar_fundador'/);
assert.doesNotMatch(vipEdge, /Number\(lugares \?\? 0\)/);
assert.doesNotMatch(stripeEdge, /Number\(lugares \?\? 0\)/);

const priceMigration = fs.readFileSync('supabase/v404_precios_cuota_canonico.sql', 'utf8');
assert.match(priceMigration, /create table if not exists public\.precios_cuota/);
assert.match(priceMigration, /coalesce\(\(p\)\.tipo, 'pick'\) = 'error'/);
assert.doesNotMatch(priceMigration, /coalesce\(p\.(?:elige|tipo|prob|cuota)/, 'v404 debe usar la referencia portable (p).campo');
assert.doesNotMatch(negocio, /coalesce\(p\.(?:elige|tipo|prob|cuota)/, 'bootstrap debe usar la referencia portable (p).campo');
assert.match(priceMigration, /coalesce\(\(p\)\.cuota, 1\) >= pc\.desde/);
assert.match(priceMigration, /coalesce\(\(p\)\.prob, 0\) >= 0\.85/);
assert.match(negocio, /create table if not exists public\.precios_cuota/);

const vipSql = fs.readFileSync('supabase/v383_usuarios_vip.sql', 'utf8');
for (const [nombre, sql] of [['web/negocio.sql', negocio], ['supabase/v383_usuarios_vip.sql', vipSql], ['supabase/v402_bughunter_hardening.sql', hardening]]) {
  assert.doesNotMatch(sql, /end \$;/, nombre + ': no debe truncarse el delimitador $$');
  assert.equal((sql.match(/\$\$/g) || []).length % 2, 0, nombre + ': delimitadores $$ balanceados');
}
assert.match(negocio, /p\.estado in \('verde','roja','nula'\)/);
assert.doesNotMatch(negocio, /p\.id = picks_premium\.id and p\.inicio <= now\(\)/);
assert.match(hardening, /p\.estado in \('verde','roja','nula'\)/);
assert.match(hardening, /revoke execute on function public\.desbloquear\(text\) from public, anon/);

const commentEdge = fs.readFileSync('supabase/functions/comentario/index.ts', 'utf8');
assert.match(commentEdge, /rpc\('registrar_comentario'/);
assert.match(commentEdge, /, 429, origin\)/);
assert.match(commentEdge, /const esClavePublica = token === ANON \|\| token\.startsWith\('sb_publishable_'\)/);

const mp = fs.readFileSync('supabase/functions/mp-webhook/index.ts', 'utf8');
const stripe = fs.readFileSync('supabase/functions/stripe-webhook/index.ts', 'utf8');
assert.match(mp, /procesar_vip_unico/);
assert.match(mp, /status: 500/);
assert.match(stripe, /procesar_vip_unico/);
assert.match(stripe, /status: 503/);
console.log('OK: fechas ISO + guardas estáticas de feed, historial, pagos y comentarios');