#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
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
console.log('OK: parser ISO de SharPicks (8 casos)');
