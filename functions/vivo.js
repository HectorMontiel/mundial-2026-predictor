// v424 — EL MARCADOR EN VIVO DE TODOS LOS PARTIDOS (Cloudflare Pages Function, /vivo).
//
// El usuario: «no todos los partidos en vivo traen cuánto va el marcador; es
// importante que todos lo tengan, con sus estadísticas del momento». La página
// lo pide a ESPN desde el navegador, pero ESPN no cubre muchas ligas (Tercera
// RFEF, Sub-21…). Flashscore sí, y el navegador no puede pedírselo (no permite
// otros orígenes): esta función lo pide por él, desde NUESTRO dominio.
//   GET /vivo?dep=futbol|tenis|basquet|hockey|beisbol  → los partidos del día
//   GET /vivo?id=<id de Flashscore>                      → sus estadísticas
// Sólo lectura, con 30 s de caché en el borde de Cloudflare.
const FEED = 'https://global.flashscore.ninja/2/x/feed/';
const H = { 'x-fsign': 'SW9D1eZo', Referer: 'https://www.flashscore.com/', 'User-Agent': 'Mozilla/5.0' };
const DEPORTES = { futbol: 1, tenis: 2, basquet: 3, hockey: 4, beisbol: 6 };
// detalle del estado (AC) → texto
const FASE = { 12: '1.ª parte', 13: '2.ª parte', 38: 'Medio tiempo', 6: 'Prórroga', 7: 'Penales', 3: 'Final', 10: 'Final (prórroga)', 11: 'Final (penales)',
  17: '1.er set', 18: '2.º set', 19: '3.er set', 20: '4.º set', 21: '5.º set', 22: '1.er cuarto', 23: '2.º cuarto', 24: '3.er cuarto', 25: '4.º cuarto',
  14: '1.er periodo', 15: '2.º periodo', 16: '3.er periodo', 46: 'Descanso' };

const json = (d, s = 200) => new Response(JSON.stringify(d), {
  status: s, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=30' } });

function campos(r) {
  const o = {};
  for (const par of r.split('¬')) { const i = par.indexOf('÷'); if (i > 0) o[par.slice(0, i)] = par.slice(i + 1); }
  return o;
}

function partidos(txt) {
  const out = [];
  let liga = '';
  for (const r of txt.split('~')) {
    if (r.startsWith('ZA÷')) { liga = campos(r).ZA || ''; continue; }
    if (!r.startsWith('AA÷')) continue;
    const c = campos(r);
    const ab = Number(c.AB || 0);
    out.push({ id: c.AA, liga, home: c.AE || c.CX || '', away: c.AF || '', gh: c.AG != null ? Number(c.AG) : null, ga: c.AH != null ? Number(c.AH) : null,
      estado: ab === 2 ? 'in' : ab === 3 ? 'post' : 'pre', detalle: FASE[Number(c.AC)] || (ab === 3 ? 'Final' : ab === 2 ? 'En juego' : ''), inicio: Number(c.AD || 0) });
  }
  return out;
}

function estadisticas(txt) {
  // sólo la sección «Match» (el partido entero), no las de cada tiempo
  const sec = txt.split('~SE÷').filter(Boolean)[0] || '';
  const out = {};
  for (const r of sec.split('~')) {
    const c = campos(r);
    if (c.SG && c.SH != null && c.SI != null && !(c.SG in out)) out[c.SG] = [c.SH, c.SI];
  }
  return out;
}

async function pedir(ruta) {
  const r = await fetch(FEED + ruta, { headers: H, cf: { cacheTtl: 30, cacheEverything: true } });
  return r.ok ? r.text() : '';
}

export async function onRequestGet({ request }) {
  const u = new URL(request.url);
  const id = u.searchParams.get('id');
  try {
    if (id) {
      if (!/^[A-Za-z0-9]{6,12}$/.test(id)) return json({ error: 'id' }, 400);
      return json({ id, stats: estadisticas(await pedir('df_st_1_' + id)) });
    }
    const dep = DEPORTES[u.searchParams.get('dep') || 'futbol'];
    if (!dep) return json({ error: 'deporte' }, 400);
    return json({ partidos: partidos(await pedir('f_' + dep + '_0_3_es-mx_1')) });
  } catch (e) {
    return json({ error: 'sin respuesta de la fuente' }, 502);
  }
}
