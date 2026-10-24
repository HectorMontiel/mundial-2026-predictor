// v460 — LA PRESIÓN DE TODOS LOS PARTIDOS (Cloudflare Pages Function, /presion).
//
// El usuario: «todos los partidos tienen que tener su barra de presión, dividida
// en primer y segundo tiempo». ESPN da jugadas con lugar y 365Scores tiros sólo
// en algunas ligas; en las demás no había con qué dibujarla. FotMob tiene, para
// las ligas grandes, la presión minuto a minuto («momentum») y, para casi todas,
// las estadísticas de cada tiempo. El navegador no se lo puede pedir (no permite
// otros orígenes): esta función lo pide por él, desde NUESTRO dominio.
//   GET /presion?f=AAAAMMDD&l=<local>&v=<visitante>
//   → { id, momentum: [valores por minuto] | null, mitades: [{...}, {...}] | null,
//       eventos: [{ m, tipo: 'gol'|'amarilla'|'roja', local }], terminado }
// Sólo lectura; caché en el borde: la lista del día 10 min, el detalle 30 s en vivo.
const API = 'https://www.fotmob.com/api/data/';
const UA = { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' };

const json = (d, s = 200, edad = 30) => new Response(JSON.stringify(d), {
  status: s, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=' + edad } });

const norm = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/\b(fc|cf|sc|ac|cd|ud|ca|club|de|the|afc|fk|sk|if|bk)\b/g, ' ').replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
const fichas = (s) => new Set(norm(s).split(' ').filter(Boolean));
function parecido(x, y) {                     // x, y: conjuntos de palabras ya normalizadas
  if (!x.size || !y.size) return 0;
  let c = 0; x.forEach((t) => { if (y.has(t)) c++; });
  return c / Math.min(x.size, y.size);
}

async function pedir(url, ttl) {
  const r = await fetch(url, { headers: UA, cf: { cacheTtl: ttl, cacheEverything: true } });
  return r.ok ? r.json() : null;
}

function mitades(stats) {
  const P = (stats && stats.Periods) || {};
  const uno = (per) => {
    const out = {};
    for (const g of ((P[per] || {}).stats) || []) {
      for (const s of g.stats || []) {
        const k = { total_shots: 'tiros', ShotsOnTarget: 'puerta', corners: 'corners', big_chance: 'ocasiones',
          touches_opp_box: 'area', BallPossesion: 'pos', yellow_cards: 'amarillas', fouls: 'faltas' }[s.key];
        if (k && Array.isArray(s.stats) && out[k] == null) out[k] = s.stats.map((x) => Number(x) || 0);
      }
    }
    return Object.keys(out).length ? out : null;
  };
  const a = uno('FirstHalf'), b = uno('SecondHalf');
  return { mitades: a || b ? [a, b] : null, todo: uno('All') };
}

export async function onRequestGet(ctx) {
  // la misma pregunta en 30 s se contesta desde la caché del borde (sin volver a calcular)
  const cache = caches.default, guardada = await cache.match(ctx.request);
  if (guardada) return guardada;
  const r = await responder(ctx.request);
  if (r.status === 200) ctx.waitUntil(cache.put(ctx.request, r.clone()));
  return r;
}

async function responder(request) {
  const u = new URL(request.url);
  const f = u.searchParams.get('f') || '', l = (u.searchParams.get('l') || '').slice(0, 80), v = (u.searchParams.get('v') || '').slice(0, 80);
  if (!/^\d{8}$/.test(f) || !l || !v) return json({ error: 'parámetros' }, 400, 60);
  try {
    // el día de FotMob no siempre es el de la hora UTC del partido: el pedido, y si no está, el anterior y el siguiente
    const otro = (d) => { const x = new Date(Date.UTC(+f.slice(0, 4), +f.slice(4, 6) - 1, +f.slice(6, 8) + d)); return x.toISOString().slice(0, 10).replace(/-/g, ''); };
    let mejor = null, puntos = 0, girado = false;
    const L = fichas(l), V = fichas(v);
    for (const d of [0, -1, 1]) {
      const dia = await pedir(API + 'matches?date=' + otro(d), 600);
      for (const liga of (dia && dia.leagues) || []) {
        for (const m of liga.matches || []) {
          const h = fichas((m.home || {}).name), a = fichas((m.away || {}).name);
          const directo = parecido(L, h) + parecido(V, a), vuelta = parecido(L, a) + parecido(V, h);
          const p = Math.max(directo, vuelta);
          if (p > puntos) { puntos = p; mejor = m; girado = vuelta > directo; }
        }
      }
      if (puntos >= 1.6) break;
    }
    if (!mejor || puntos < 1.2) return json({ id: null }, 200, 300);
    const st = mejor.status || {};
    const det = await pedir(API + 'matchDetails?matchId=' + mejor.id, st.finished ? 3600 : 30);
    const c = (det && det.content) || {};
    const mo = c.momentum && c.momentum.main && Array.isArray(c.momentum.main.data) ? c.momentum.main.data : null;
    const momentum = mo ? mo.map((x) => (girado ? -1 : 1) * Math.max(-100, Math.min(100, Number(x.value) || 0))) : null;
    const voltea = (x) => x && Object.fromEntries(Object.entries(x).map(([k, a]) => [k, [a[1], a[0]]]));
    const est = mitades(c.stats);
    const mt = est.mitades && girado ? est.mitades.map(voltea) : est.mitades, todo = girado ? voltea(est.todo) : est.todo;
    // v462 — la compensación anunciada (FotMob la da en cuanto la muestra el cuarto árbitro)
    const lt = st.liveTime || {};
    const compensacion = Number(lt.addedTime) > 0 ? { min: Number(lt.addedTime), tiempo: Number(lt.basePeriod) === 45 ? 1 : 2 } : null;
    const eventos = ((((c.matchFacts || {}).events) || {}).events || [])
      .filter((e) => e.type === 'Goal' || e.type === 'Card')
      .map((e) => ({ m: Number(e.time) || 0, extra: Number(e.overloadTime) || 0,
        tipo: e.type === 'Goal' ? 'gol' : /red/i.test(e.card || '') ? 'roja' : 'amarilla',
        local: girado ? !e.isHome : !!e.isHome }));
    return json({ id: mejor.id, momentum, mitades: mt, todo, compensacion, eventos, terminado: !!st.finished, girado }, 200, st.finished ? 3600 : 30);
  } catch (e) {
    return json({ error: 'sin respuesta de la fuente' }, 502, 30);
  }
}
