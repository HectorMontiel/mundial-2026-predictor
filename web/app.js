// v377-v378 — El sitio sólo LEE: los picks de Supabase (o de datos/hoy.json)
// y, EN VIVO, el marcador y las estadísticas directo de ESPN (permite leerlo
// desde la página), cada 30 s, sólo de los partidos que se están jugando.
(function () {
  const C = window.CONFIG || {};
  const ZONA = 'America/Mexico_City';
  const ESPN = 'https://site.api.espn.com/apis/site/v2/sports/';
  const $ = (id) => document.getElementById(id);
  const estado = { dia: 'hoy', deporte: 'Todos', nivel: 'Todos', soloElige: false, orden: 'hora', picks: [], vivo: {}, vivoCursor: 0, errorPicks: false, respaldoPicks: false, errorCombinadas: false };

  const diaCdmx = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: ZONA }).format(d);
  // v402 — parser ISO aislado y cubierto por test_web_v402.cjs. Reconoce Z y offsets ±HH:MM/±HHMM.
  const aFecha = window.SharPicksFechas.aFecha;
  const horaCdmx = (d) => d ? new Intl.DateTimeFormat('es-MX', { timeZone: ZONA, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(d) : '';
  const pct = (x) => x == null ? '—' : Math.round(100 * x) + ' %';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const lados = (p) => { const t = String(p.partido || ''); const i = t.indexOf(' vs '); return i < 0 ? [t, ''] : [t.slice(0, i), t.slice(i + 4)]; };

  function diaDe(p) { const d = aFecha(p.inicio); return d ? diaCdmx(d) : String(p.fecha || ''); }
  function diaPestana(n) { const d = new Date(); d.setUTCDate(d.getUTCDate() + n); return diaCdmx(d); }
  const OFFS = { ayer: -1, hoy: 0, manana: 1, pasado: 2 };

  // Niveles (como los «stakes» de BetFlipAi), pero con lo MEDIDO de verdad
  function nivel(p) {
    if (p.solo_analisis) return { n: 'Sólo análisis', c: 'analisis', i: '📊' };   // v418
    if (p.tipo === 'error') return { n: 'Cuota alta', c: 'error', i: '💰' };
    if (p.elige) return { n: 'Diamante', c: 'diamante', i: '💎' };
    if ((p.prob || 0) >= 0.85) return { n: 'Platino', c: 'platino', i: '🔷' };
    if ((p.prob || 0) >= 0.80) return { n: 'Oro', c: 'oro', i: '🥇' };
    return { n: 'Plata', c: 'plata', i: '🥈' };
  }

  // v396 — el nivel en palabras: probabilidad, nunca «segura» ni «se cumplen 9 de 10»
  function grado(p) {
    const n = nivel(p).n;
    return { Diamante: 'Muy alta', Platino: 'Muy alta', Oro: 'Alta', Plata: 'Buena' }[n] || '—';
  }

  async function cargar() {
    // v384 — datos de apoyo (deportes con partidos pero sin pick)
    fetch('combinadas_simuladas.json').then((r) => r.ok ? r.json() : null).then((d) => { estado.combSim = d; }).catch(() => {});   // v421
    fetch('datos/meta.json?t=' + Date.now()).then((r) => r.ok ? r.json() : null).then((m) => { estado.meta = m || {}; }).catch(() => {});
    // v418 — los partidos SIN pick, para analizarlos (no cuentan en ningún marcador)
    fetch('datos/analisis.json?t=' + Date.now()).then((r) => r.ok ? r.json() : null)
      .then((d) => { estado.analisis = (d && Array.isArray(d.analisis)) ? d.analisis : []; pintar(); }).catch(() => {});
    try {
      if (C.SUPABASE_URL && C.SUPABASE_ANON_KEY) {
        const desde = diaPestana(-2);
        const r = await fetch(C.SUPABASE_URL.replace(/\/$/, '') + '/rest/v1/picks?select=*&fecha=gte.' + desde + '&order=inicio.asc&limit=5000',
          { headers: { apikey: C.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + C.SUPABASE_ANON_KEY } });
        if (!r.ok) throw new Error('base de datos ' + r.status);
        const datos = await r.json();
        if (!Array.isArray(datos)) throw new Error('respuesta de picks no es una lista');
        estado.picks = datos;
        estado.errorPicks = false;
        estado.respaldoPicks = false;
        $('actualizado').textContent = 'Datos de la base · ' + horaCdmx(new Date());
      } else { throw new Error('sin base'); }
    } catch (e) {
      console.warn('[sharpicks] falló la consulta principal de picks', e);
      try {
        const r = await fetch('datos/hoy.json?t=' + Date.now());
        if (!r.ok) throw new Error('respaldo HTTP ' + r.status);
        const d = await r.json();
        if (!d || !Array.isArray(d.picks)) throw new Error('respaldo sin lista de picks');
        estado.picks = d.picks;
        estado.errorPicks = false;
        estado.respaldoPicks = true;
        const generada = aFecha(d.generado);
        $('actualizado').textContent = generada ? 'Respaldo local · ' + horaCdmx(generada) : 'Respaldo local · fecha de generación no verificable';
      } catch (e2) {
        console.error('[sharpicks] falló también el respaldo local de picks', e2);
        estado.picks = [];
        estado.errorPicks = true;
        estado.respaldoPicks = false;
        $('aviso').textContent = 'No se pudieron consultar los pronósticos. La fuente y el respaldo fallaron; reintenta en un momento.';
      }
    }
    // v396 — las combinadas (tabla pública `combinadas`)
    try {
      if (C.SUPABASE_URL && C.SUPABASE_ANON_KEY) {
        const rc = await fetch(C.SUPABASE_URL.replace(/\/$/, '') + '/rest/v1/combinadas?select=*&fecha=gte.' + diaPestana(-30) + '&order=inicio.asc&limit=2000',
          { headers: { apikey: C.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + C.SUPABASE_ANON_KEY } });
        if (!rc.ok) throw new Error('combinadas HTTP ' + rc.status);
        const datosCombinadas = await rc.json();
        if (!Array.isArray(datosCombinadas)) throw new Error('respuesta de combinadas no es una lista');
        estado.combinadas = datosCombinadas;
        estado.errorCombinadas = false;
      } else {
        estado.combinadas = [];
        estado.errorCombinadas = true;
      }
    } catch (e) {
      console.warn('[sharpicks] no se pudieron consultar las combinadas', e);
      estado.combinadas = [];
      estado.errorCombinadas = true;
    }
    pintar();
    vivo();
  }

  // ---------- EN VIVO (ESPN) ----------
  const STATS_FUT = [['totalShots', 'Tiros'], ['shotsOnTarget', 'A puerta'], ['wonCorners', 'Córners'],
    ['possessionPct', 'Posesión %'], ['foulsCommitted', 'Faltas'], ['yellowCards', 'Amarillas'], ['redCards', 'Rojas'],
    ['offsides', 'Fueras de lugar'], ['saves', 'Paradas'], ['accuratePasses', 'Pases buenos']];

  const TRAD = { 'Shots': 'Tiros', 'Shots on Goal': 'Tiros a puerta', 'Saves': 'Paradas', 'Hits': 'Golpes', 'Blocked Shots': 'Tiros bloqueados',
    'Penalty Minutes': 'Minutos de castigo', 'Power Play Goals': 'Goles en power play', 'Faceoffs Won': 'Saques ganados', 'Takeaways': 'Robos',
    'Giveaways': 'Pérdidas', 'Rebounds': 'Rebotes', 'Assists': 'Asistencias', 'Turnovers': 'Pérdidas', 'Steals': 'Robos', 'Blocks': 'Tapones',
    'Field Goal %': '% de tiro', 'Three Point %': '% de triples', 'Free Throw %': '% de libres', 'Total Yards': 'Yardas', 'Passing': 'Pase',
    'Rushing': 'Carrera', '1st Downs': 'Primeros downs', 'Turnovers ': 'Pérdidas', 'Possession': 'Posesión' };

  // v378 — LOS COLORES DE CADA EQUIPO (los da ESPN: principal y secundario).
  // Sobre el fondo oscuro, un color casi negro no se ve: se usa el secundario
  // o se aclara. Si los dos equipos quedan casi iguales, el visitante va con
  // su secundario (o con el rosa de la página).
  const hex = (h) => { h = String(h || '').replace('#', ''); return /^[0-9a-f]{6}$/i.test(h) ? h : null; };
  const rgb = (h) => [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  const luz = (h) => { const [r, g, b] = rgb(h).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const dist = (a, b) => { const x = rgb(a), y = rgb(b); return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]); };
  const aclarar = (h) => rgb(h).map((x) => Math.round(x + (255 - x) * 0.45).toString(16).padStart(2, '0')).join('');
  function visible(c, alt) {
    if (c && luz(c) >= 0.06) return c;
    if (alt && luz(alt) >= 0.06) return alt;
    return c ? aclarar(c) : null;
  }
  function coloresEquipos(t1, t2) {
    let a = visible(hex(t1.color), hex(t1.alternateColor)) || '7c5cff';
    let b = visible(hex(t2.color), hex(t2.alternateColor)) || 'ff5ca8';
    if (dist(a, b) < 90) {
      const alt = visible(hex(t2.alternateColor), null);
      b = alt && dist(a, alt) >= 90 ? alt : (dist(a, 'ff5ca8') >= 90 ? 'ff5ca8' : '7c5cff');
    }
    const txt = (c) => (luz(c) > 0.45 ? '#111' : '#fff');
    return { l: '#' + a, r: '#' + b, tl: txt(a), tr: txt(b) };
  }
  const varsColor = (v) => v && v.colores ? '--c-l:' + v.colores.l + ';--c-r:' + v.colores.r + ';--t-l:' + v.colores.tl + ';--t-r:' + v.colores.tr : '';

  function leerResumen(d, p) {
    const comp = ((d.header || {}).competitions || [])[0] || {};
    const st = (comp.status || {}).type || {};
    const cs = comp.competitors || [];
    const ch = cs.find((c) => c.homeAway === 'home') || {}, ca = cs.find((c) => c.homeAway === 'away') || {};
    const [nos1, nos2] = p.girado ? [ca, ch] : [ch, ca];        // en el orden de NUESTRO «A vs B»
    const stats = {};
    for (const t of ((d.boxscore || {}).teams || [])) {
      const lado = String((t.team || {}).id) === String((nos1.team || {}).id) ? 0 : 1;
      for (const s of t.statistics || []) {
        const k = s.name || s.label; if (!k) continue;
        stats[k] = stats[k] || { label: s.label || s.name, v: [null, null] };
        stats[k].v[lado] = s.displayValue;
      }
    }
    const eventos = ((d.keyEvents && d.keyEvents.length ? d.keyEvents : d.scoringPlays) || []).map((e) => {
      const tipo = ((e.type || {}).text) || '';
      const ico = /goal|penalty - scored/i.test(tipo) || e.scoringPlay ? '⚽' : /yellow/i.test(tipo) ? '🟨' : /red card/i.test(tipo) ? '🟥' : /substitution/i.test(tipo) ? '' : '•';
      const texto = String(e.text || e.shortText || '').replace(/\s+(Goal|Own Goal|Penalty - Scored|Yellow Card|Red Card|Substitution)[^]*$/i, '').replace(/^(Goal|Yellow Card|Red Card)!?\s*/i, '');
      return { min: ((e.clock || {}).displayValue) || '', ico, texto,
        lado: String((e.team || {}).id) === String((nos1.team || {}).id) ? 0 : 1, gol: ico === '⚽' };
    }).filter((e) => e.texto && e.ico);
    // v427 — las jugadas con su lugar en la cancha. ESPN las da en la dirección de
    // ataque de quien la hizo (los dos atacan hacia X=100): el visitante se refleja.
    const n1 = ((nos1.team || {}).displayName) || '';
    const jugadas = (d.commentary || []).map((c) => c.play).filter((x) => x && x.fieldPositionX != null).map((x) => ({
      t: ((x.type || {}).type) || '', min: ((x.clock || {}).displayValue) || '', seg: Number((x.clock || {}).value || 0),
      lado: ((x.team || {}).displayName) === n1 ? 0 : 1, equipo: ((x.team || {}).displayName) || '',
      x: Number(x.fieldPositionX), y: Number(x.fieldPositionY),
      x2: x.fieldPosition2X != null ? Number(x.fieldPosition2X) : null, y2: x.fieldPosition2Y != null ? Number(x.fieldPosition2Y) : null,
    })).sort((a, b) => a.seg - b.seg);
    return {
      jugadas,
      fase: st.state || 'pre', terminado: !!st.completed, detalle: ({ FT: 'Final', HT: 'Medio tiempo', AET: 'Final (prórroga)', 'FT-Pens': 'Final (penales)', Final: 'Final' })[st.shortDetail] || st.shortDetail || st.detail || '',
      reloj: (comp.status || {}).displayClock || '', g: [Number(nos1.score || 0), Number(nos2.score || 0)],
      stats, eventos, nombres: [((nos1.team || {}).displayName) || '', ((nos2.team || {}).displayName) || ''],
      colores: coloresEquipos(nos1.team || {}, nos2.team || {}),
    };
  }

  async function vivo() {
    const ahora = Date.now();
    const ids = {};
    for (const p of estado.picks.concat(estado.analisis || [])) {     // v424: también las de sólo análisis
      const ini = aFecha(p.inicio);
      if (!p.espn || !ini) continue;
      const desde = ini.getTime() - 10 * 60e3, hasta = ini.getTime() + 4 * 3600e3;
      const yaFin = (estado.vivo[p.espn] || {}).terminado;
      if (ahora >= desde && ahora <= hasta && !yaFin) ids[p.espn] = p;
    }
    const entradas = Object.entries(ids);
    if (estado.vivoCorriendo || !entradas.length) return;
    // v402 — ventana rotatoria: un límite de 40 por pasada no debe excluir siempre a los mismos partidos.
    const n = Math.min(40, entradas.length);
    const cursor = estado.vivoCursor % entradas.length;
    const lista = Array.from({ length: n }, (_, i) => entradas[(cursor + i) % entradas.length]);
    estado.vivoCursor = (cursor + n) % entradas.length;
    estado.vivoCorriendo = true;
    let cambio = false;
    try {
      for (let i = 0; i < lista.length; i += 8) {
        await Promise.all(lista.slice(i, i + 8).map(async ([k, p]) => {
          const [ruta, id] = k.split(':');
          try {
            const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), 8000);
            const r = await fetch(ESPN + ruta + '/summary?event=' + id, { signal: ctl.signal });
            clearTimeout(to);
            if (r.ok) {
              const nuevo = leerResumen(await r.json(), p), viejo = estado.vivo[k];
              if (!viejo || viejo.reloj !== nuevo.reloj || String(viejo.g) !== String(nuevo.g) || viejo.fase !== nuevo.fase) cambio = true;
              estado.vivo[k] = nuevo;
            }
          } catch (e) { /* sin red: se reintenta en 30 s */ }
        }));
      }
    } finally { estado.vivoCorriendo = false; }
    if (cambio && !document.hidden) { pintar(); refrescarFicha(); }
  }

  // v424 — EL MARCADOR DE TODOS: lo que ESPN no cubre (Tercera RFEF, Sub-21…)
  // sale de Flashscore por nuestra función `/vivo` (functions/vivo.js). Se
  // empareja por los nombres de los dos equipos; cuando la tarjeta está abierta
  // se piden también sus estadísticas del momento.
  const DEP_FS = { 'Fútbol': 'futbol', Tenis: 'tenis', NBA: 'basquet', NHL: 'hockey', MLB: 'beisbol', KBO: 'beisbol', 'Béisbol': 'beisbol' };
  const GENERICAS = new Set(['fc', 'cf', 'cd', 'sc', 'ac', 'club', 'the', 'afc', 'de', 'del', 'and', 'sad']);
  const fichas = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9 ]/g, ' ')
    .split(/\s+/).filter((w) => w.length >= 3 && !GENERICAS.has(w));
  const casan = (a, b) => { const x = fichas(a), y = new Set(fichas(b)); return x.length && y.size && x.some((w) => y.has(w)); };
  // v429 — el MÁS parecido, no el primero: «Bayern Munich» con «Bayern Munich»
  // gana a «Bayern Munich Sub19» (la Youth League juega el mismo día)
  const parecido = (a, b) => { const x = new Set(fichas(a)), y = new Set(fichas(b)); if (!x.size || !y.size) return 0;
    let c = 0; x.forEach((w) => { if (y.has(w)) c++; }); return c / (x.size + y.size - c); };
  function mejorCruce(L, V, lista, kh, ka) {
    let mejor = null, pm = 0;
    for (const x of lista) {
      for (const gir of [false, true]) {
        const a = parecido(L, gir ? x[ka] : x[kh]), b = parecido(V, gir ? x[kh] : x[ka]);
        if (a > 0 && b > 0 && a + b > pm) { pm = a + b; mejor = { m: x, girado: gir }; }
      }
    }
    return mejor;
  }
  const STATS_FS = { 'Ball possession': 'possessionPct', 'Total shots': 'totalShots', 'Shots on target': 'shotsOnTarget', 'Corner kicks': 'wonCorners',
    'Yellow cards': 'yellowCards', 'Red cards': 'redCards', 'Fouls': 'foulsCommitted', 'Offsides': 'offsides', 'Goalkeeper saves': 'saves',
    'Expected goals (xG)': 'xg', 'Passes': 'totalPasses' };
  estado.fsPor = {}; estado.fsStats = {}; estado.fsPedido = {};
  async function vivoFs() {
    if (document.hidden) return;
    const ahora = Date.now();
    const sin = estado.picks.concat(estado.analisis || []).filter((p) => {
      if (p.espn && estado.vivo[p.espn]) return false;          // ESPN ya lo da
      const ini = aFecha(p.inicio);
      return ini && DEP_FS[p.deporte] && ahora >= ini - 10 * 60e3 && ahora <= ini.getTime() + duracion(p.deporte) + 30 * 60e3;
    });
    if (!sin.length) return;
    let cambio = false;
    for (const dep of [...new Set(sin.map((p) => DEP_FS[p.deporte]))]) {
      let lista = [];
      try { const r = await fetch('vivo?dep=' + dep); if (r.ok) lista = (await r.json()).partidos || []; } catch (e) { continue; }
      for (const p of sin.filter((x) => DEP_FS[x.deporte] === dep)) {
        const [L, V] = lados(p);
        const cr = mejorCruce(L, V, lista, 'home', 'away'), m = cr && cr.m, girado = !!(cr && cr.girado);
        if (!m || m.estado === 'pre') continue;
        const k = clavePartido(p), viejo = estado.fsPor[k];
        const g = [m.gh == null ? 0 : m.gh, m.ga == null ? 0 : m.ga];
        const st = estado.fsStats[m.id] || {};
        estado.fsPor[k] = { fase: m.estado, terminado: m.estado === 'post', detalle: m.detalle, reloj: m.detalle, g: girado ? [g[1], g[0]] : g,
          stats: Object.fromEntries(Object.entries(st).map(([n, v]) => [STATS_FS[n] || n, { label: n, v: girado ? [v[1], v[0]] : v }])),
          eventos: [], nombres: [L, V], colores: null, fuente: 'flashscore', fsId: m.id };
        if (!viejo || String(viejo.g) !== String(estado.fsPor[k].g) || viejo.fase !== m.estado) cambio = true;
        // las estadísticas, sólo de las tarjetas abiertas (una vez por minuto)
        if (estado.abiertos.has(k) && m.estado === 'in' && dep === 'futbol' && !(estado.fsPedido[m.id] > ahora - 60e3)) {
          estado.fsPedido[m.id] = ahora;
          fetch('vivo?id=' + encodeURIComponent(m.id)).then((r) => (r.ok ? r.json() : null)).then((d) => {
            if (d && d.stats && Object.keys(d.stats).length) { estado.fsStats[m.id] = d.stats; vivoFs(); }
          }).catch(() => {});
        }
      }
    }
    if (cambio) pintar();
  }

  // ¿Cómo va la apuesta? (sólo para enseñarlo; lo oficial lo liquida el modelo)
  function progreso(p, v) {
    if (!v || v.fase === 'pre') return null;
    // v381 — el premium se sigue en vivo con su texto real (si el usuario lo ve)
    const [L, V] = lados(p), a = String((window.SPX && SPX.yo.desbloqueados[p.id]) || p.apuesta || '');
    const sv = (k) => { const s = v.stats[k]; return s ? s.v.map((x) => Number(x || 0)) : null; };
    let m, cuenta = null, lado = null, linea = null, tipo = null;
    if ((m = a.match(/^(Goles|Puntos|Córners|Tarjetas): (Más|Menos) de ([\d.]+)/))) {
      linea = Number(m[3]); lado = m[2];
      if (m[1] === 'Córners') { const c = sv('wonCorners'); cuenta = c ? c[0] + c[1] : null; tipo = 'córners'; }
      else if (m[1] === 'Tarjetas') { const y = sv('yellowCards'), rr = sv('redCards'); cuenta = y ? y[0] + y[1] + (rr ? rr[0] + rr[1] : 0) : null; tipo = 'tarjetas'; }
      else { cuenta = v.g[0] + v.g[1]; tipo = m[1].toLowerCase(); }
    } else if ((m = a.match(/^Goles (.+): (Más|Menos) de ([\d.]+)/))) {
      linea = Number(m[3]); lado = m[2]; cuenta = m[1] === V ? v.g[1] : v.g[0]; tipo = 'goles de ' + m[1];
    }
    if (cuenta != null) {
      const txt = 'Van ' + cuenta + ' ' + tipo + ' (línea ' + linea + ')';
      if (lado === 'Menos') return cuenta > linea ? { e: 'roja', t: txt + ' · ya se pasó' } : v.terminado ? { e: 'verde', t: txt } : { e: 'va', t: txt + ' · aguanta ' + Math.floor(linea - cuenta) + ' más' };
      return cuenta > linea ? { e: 'verde', t: txt + ' · ¡ya se cumplió!' } : v.terminado ? { e: 'roja', t: txt } : { e: 'va', t: txt + ' · faltan ' + Math.floor(linea - cuenta + 1) };
    }
    const dif = v.g[0] - v.g[1];
    let ok = null;
    if ((m = a.match(/^Gana (.+)/))) ok = m[1] === V ? dif < 0 : dif > 0;
    else if ((m = a.match(/^(.+) o empate$/))) ok = m[1] === V ? dif <= 0 : dif >= 0;
    else if ((m = a.match(/^Handicap: (.+) ([+-][\d.]+)/))) { const h = Number(m[2]); ok = m[1] === V ? (v.g[1] + h > v.g[0]) : (v.g[0] + h > v.g[1]); }
    if (ok == null) return null;
    return { e: v.terminado ? (ok ? 'verde' : 'roja') : 'va', t: v.terminado ? (ok ? 'Se cumplió' : 'No se cumplió') : (ok ? 'Ahorita se está cumpliendo' : 'Ahorita no se cumple') };
  }

  // ---------- MARCADORES ----------
  function cuenta(lista) {
    const v = lista.filter((p) => p.estado === 'verde').length, r = lista.filter((p) => p.estado === 'roja').length;
    const din = lista.reduce((s, p) => s + (p.estado === 'verde' ? (p.cuota || 1) - 1 : p.estado === 'roja' ? -1 : 0), 0);
    return { v, r, pct: v + r ? v / (v + r) : null, din };
  }
  function cajaMarcador(titulo, todo) {
    // v386 — los errores de cuota (💰) con su propio marcador, aparte
    const lista = todo.filter((p) => p.tipo !== 'error');
    const t = cuenta(lista), e = cuenta(lista.filter((p) => p.elige)), er = cuenta(todo.filter((p) => p.tipo === 'error'));
    const pend = lista.filter((p) => p.estado === 'pendiente' || p.estado === 'vivo').length;
    return '<div class="caja"><div class="tit">' + titulo + '</div>' +
      '<div class="num">✅ ' + t.v + ' &nbsp;❌ ' + t.r + ' <span class="pct">' + pct(t.pct) + '</span></div>' +
      '<div class="barra"><i style="width:' + (t.pct == null ? 0 : 100 * t.pct) + '%"></i></div>' +
      '<div class="sub">💎 Diamante: ✅ ' + e.v + ' ❌ ' + e.r + (e.pct == null ? '' : ' · ' + pct(e.pct)) + ' · por jugar ' + pend + '</div>' +
      (er.v + er.r ? '<div class="sub">💰 Cuota alta: ✅ ' + er.v + ' ❌ ' + er.r + ' · ' + pct(er.pct) + '</div>' : '') + '</div>';
  }

  // ---------- TARJETAS ----------
  function escudo(url, nombre) {
    return url ? '<img class="escudo" loading="lazy" src="' + esc(url) + '" alt="">' : '<span class="escudo letra">' + esc(String(nombre || '?').slice(0, 1)) + '</span>';
  }
  function cuentaAtras(ini) {
    const s = Math.floor((ini - Date.now()) / 1000);
    if (s <= 0) return '';
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h > 23 ? Math.floor(h / 24) + ' d ' + (h % 24) + ' h' : h + ' h ' + String(m).padStart(2, '0') + ' min';
  }
  function etiquetaEstado(p, v) {
    const ini = aFecha(p.inicio);
    if (p.estado === 'verde') return '<span class="et verde">✅ Verde</span>';
    if (p.estado === 'roja') return '<span class="et roja">❌ Roja</span>';
    if (p.estado === 'nula') return '<span class="et">Nula</span>';
    if (v && v.fase === 'in') return '<span class="et vivo"><i class="punto"></i>' + esc(v.detalle || v.reloj || 'En vivo') + '</span>';
    if (v && v.terminado) return '<span class="et">Terminado · liquidando</span>';
    if (ini && ini <= new Date()) return '<span class="et vivo"><i class="punto"></i>En juego</span>';
    return '<span class="et">⏳ ' + esc(cuentaAtras(ini)) + '</span>';
  }
  // ---------- ESTADÍSTICAS VISUALES (como SofaScore) ----------
  // Cada fila: número del local | nombre | número del visitante; el que va
  // adelante en su color, y dos barras que crecen desde el centro.
  const num = (x) => { const n = parseFloat(String(x == null ? '' : x).replace('%', '')); return isNaN(n) ? 0 : n; };
  function filaStat(etq, va, vb, chica) {
    const a = num(va), b = num(vb), m = Math.max(a, b) || 1;
    const ga = a > b, gb = b > a;
    return '<div class="st' + (chica ? ' chica' : '') + '">' +
      '<div class="st-nums"><span class="pill l' + (ga ? ' gana' : '') + '">' + esc(va ?? '-') + '</span>' +
      '<span class="st-etq">' + esc(etq) + '</span>' +
      '<span class="pill r' + (gb ? ' gana' : '') + '">' + esc(vb ?? '-') + '</span></div>' +
      '<div class="st-barras"><div class="mitad izq"><i class="' + (ga ? 'gana' : '') + '" style="width:' + (100 * a / m) + '%"></i></div>' +
      '<div class="mitad der"><i class="' + (gb ? 'gana' : '') + '" style="width:' + (100 * b / m) + '%"></i></div></div></div>';
  }
  function posesion(v) {
    const s = v.stats.possessionPct; if (!s) return '';
    const a = num(s.v[0]), b = num(s.v[1]), t = a + b || 1;
    if (!a || !b) return '';           // 0 % - 100 %: ESPN aún no la calcula
    return '<div class="posesion"><div class="pos-etq">Posesión</div><div class="pos-barra">' +
      '<i class="l" style="width:' + (100 * a / t) + '%">' + Math.round(a) + '%</i>' +
      '<i class="r" style="width:' + (100 * b / t) + '%">' + Math.round(b) + '%</i></div></div>';
  }
  // v394 — si ESPN todavía no manda las estadísticas (ligas chicas: llegan con
  // retraso o sólo al final) se dice, en vez de pintar barras en cero
  const AVISO_SIN_STATS = '<div class="mini sin-stats">📡 Las estadísticas en vivo de este partido aún no llegan: ' +
    'ESPN las publica con retraso en esta liga. El marcador sí va al minuto y esto se actualiza solo.</div>';
  function statsVacias(v) {
    const vals = Object.values(v.stats || {}).flatMap((s) => (s.v || []).map((x) => num(x)));
    return !vals.length || vals.every((x) => x === 0);
  }
  // v429 — LA CANCHA, «LO MEJOR DE CADA FUENTE». El usuario: «junta lo mejor
  // de cada una… que se vea como el partido; simple pero moderno e innovador».
  //   · 365Scores (abierto a cualquier página): la alineación de los 22 en su
  //     formación con número y calificación, y TODOS los tiros con su xG, xGOT,
  //     pie/cabeza y por dónde fueron al arco.
  //   · ESPN: las jugadas con lugar (faltas, córners, fueras de lugar…).
  //   · un balón que recorre las últimas jugadas en orden, para que se vea como
  //     el partido; y la «ola» de presión minuto a minuto (tiros por su xG,
  //     córners y jugadas de ataque).
  // Coordenadas: las dos fuentes dan cada jugada en la dirección de ataque de
  // quien la hizo (hacia 100); el local ataca a la derecha, el visitante se refleja.
  const API365 = 'https://webws.365scores.com/web/';
  const P365 = 'appTypeId=5&langId=29&timezoneName=America/Mexico_City&userCountryId=31';
  estado.d365 = {}; estado.g365 = {}; estado.p365 = {};
  async function dia365(dia) {
    const c = estado.g365[dia];
    if (c && Date.now() - c.ts < 3 * 60e3) return c.juegos;
    const [a, m, d] = dia.split('-');
    try {
      const r = await fetch(API365 + 'games/allscores/?' + P365 + '&sports=1&showOdds=false&startDate=' + d + '/' + m + '/' + a + '&endDate=' + d + '/' + m + '/' + a);
      const j = r.ok ? await r.json() : null;
      estado.g365[dia] = { ts: Date.now(), juegos: ((j && j.games) || []).map((g) => ({ id: g.id, home: g.homeCompetitor.name, away: g.awayCompetitor.name })) };
    } catch (e) { estado.g365[dia] = { ts: Date.now(), juegos: (c && c.juegos) || [] }; }
    return estado.g365[dia].juegos;
  }
  async function detalle365(p) {
    if (p.deporte !== 'Fútbol') return null;
    const k = clavePartido(p);
    let gid = estado.p365[k];
    if (gid === undefined) {
      const [L, V] = lados(p), cr = mejorCruce(L, V, await dia365(diaDe(p)), 'home', 'away');
      gid = estado.p365[k] = cr ? cr.m.id : null;
      if (cr && cr.girado) estado.p365[k + '|girado'] = true;
    }
    if (!gid) return null;
    const viejo = estado.d365[gid];
    if (viejo && Date.now() - viejo.ts < 30e3) return viejo;
    try {
      const r = await fetch(API365 + 'game/?' + P365 + '&gameId=' + gid);
      const g = r.ok ? (await r.json()).game : null;
      if (!g) return viejo || null;
      const gir = !!estado.p365[k + '|girado'];
      const nombres = Object.fromEntries((g.members || []).map((m) => [m.id, m]));
      const once = (comp, lado) => ((comp.lineups || {}).members || []).filter((m) => m.status === 1 && m.yardFormation).map((m) => ({
        lado, n: (nombres[m.id] || {}).jerseyNumber || '', nombre: (nombres[m.id] || {}).shortName || (nombres[m.id] || {}).name || '',
        prof: Number(m.yardFormation.fieldLine), ancho: Number(m.yardFormation.fieldSide), nota: m.ranking || null }));
      const lh = gir ? 1 : 0, la = gir ? 0 : 1;
      const tiros = (((g.chartEvents || {}).events) || []).map((e) => ({
        lado: e.competitorNum === 1 ? lh : la, x: Number(e.side), y: Number(e.line), xg: Number(e.xg || 0), xgot: Number(e.xgot || 0),
        min: e.time || '', gol: ((e.outcome || {}).name) === 'Gol', resultado: ((e.outcome || {}).name) || '', cuerpo: e.bodyPart || '',
        jugador: (nombres[e.playerId] || {}).shortName || '', arco: e.outcome && e.outcome.y != null ? { y: Number(e.outcome.y), z: Number(e.outcome.z) } : null }));
      estado.d365[gid] = { ts: Date.now(), once: once(g.homeCompetitor, lh).concat(once(g.awayCompetitor, la)), tiros,
        formacion: [gir ? g.awayCompetitor.lineups && g.awayCompetitor.lineups.formation : g.homeCompetitor.lineups && g.homeCompetitor.lineups.formation,
          gir ? g.homeCompetitor.lineups && g.homeCompetitor.lineups.formation : g.awayCompetitor.lineups && g.awayCompetitor.lineups.formation] };
      return estado.d365[gid];
    } catch (e) { return viejo || null; }
  }
  // sólo de los partidos cuya cancha está a la vista (tarjeta abierta o ficha)
  async function vivo365() {
    if (document.hidden) return;
    const vistos = new Set([...estado.abiertos].concat(fichaId ? [clavePartido(estado.picks.find((x) => x.id === fichaId) || {})] : []));
    const ps = estado.picks.concat(estado.analisis || []).filter((p) => vistos.has(clavePartido(p)) && p.deporte === 'Fútbol');
    const hechos = new Set();
    let cambio = false;
    for (const p of ps) {
      const k = clavePartido(p); if (hechos.has(k)) continue; hechos.add(k);
      const previo = estado.d365[estado.p365[k]], antes = JSON.stringify((previo || {}).tiros || []);
      const d = await detalle365(p);
      if (d && (!previo || JSON.stringify(d.tiros) !== antes)) cambio = true;      // v431: también al llegar por 1.ª vez
      const v = vivoDe([p]);
      if (estado.p365[k] && v && v.fase === 'in') await stats365(estado.p365[k]);      // v431 — quién ataca ahora
    }
    if (cambio) { pintar(); refrescarFicha(); }
  }

  const JUGADA = { goal: ['⚽', 'Gol', 5], 'penalty---scored': ['⚽', 'Gol de penal', 5], 'shot-on-target': ['🎯', 'Tiro a puerta', 3],
    'shot-off-target': ['↗️', 'Tiro desviado', 2], 'shot-blocked': ['🧱', 'Tiro bloqueado', 1.5], 'corner-awarded': ['🚩', 'Córner', 1],
    foul: ['✋', 'Falta', 0], offside: ['🚩', 'Fuera de lugar', 0.5], 'yellow-card': ['🟨', 'Amarilla', 0], 'red-card': ['🟥', 'Roja', 0] };
  const minuto = (s) => { const m = String(s || '').match(/(\d+)(?:'\s*\+\s*(\d+))?/); return m ? Number(m[1]) + (m[2] ? Number(m[2]) / 10 : 0) : 0; };
  function cancha(v, p) {
    const k = p ? clavePartido(p) : '';
    const d = p ? estado.d365[estado.p365[k]] : null;
    const js = (v && v.jugadas) || [], todos = (d && d.tiros) || [], once = (d && d.once) || [];
    if (!js.length && !todos.length && !once.length) return '';
    const c = (v && v.colores) || { l: '#22c55e', r: '#e879f9' };
    const col = (lado) => (lado === 0 ? c.l : c.r);
    const X = (lado, x) => ((lado === 0 ? x : 100 - x) * 1.05).toFixed(2), Y = (lado, y) => ((lado === 0 ? y : 100 - y) * 0.68).toFixed(2);
    const reloj = minuto((v && (v.reloj || v.detalle)) || '');
    const ahora = Math.max(reloj, ...js.map((j) => j.seg / 60), ...todos.map((t) => minuto(t.min)), 0);
    const pausa = !v || v.fase !== 'in' || /medio|descanso|half|^ht$/i.test(String(v.detalle || ''));
    const letrero = !v || v.fase === 'pre' ? '' : v.terminado || v.fase === 'post' ? 'FINAL' : pausa ? 'MEDIO TIEMPO' : '';
    // sin ruido: los goles siempre; los demás tiros, sólo los de los últimos 15 minutos
    const tiros = todos.filter((t) => t.gol || minuto(t.min) >= ahora - 15);
    let s = '<svg class="cancha-svg" viewBox="0 0 105 68" role="img" aria-label="Cancha en vivo"' + (k ? ' data-motor="' + esc(k) + '"' : '') + '>' +
      '<defs><pattern id="franjas" width="10.5" height="68" patternUnits="userSpaceOnUse"><rect width="5.25" height="68" fill="rgba(255,255,255,.025)"/></pattern>' +
      '<radialGradient id="luz" cx="50%" cy="40%" r="75%"><stop offset="0" stop-color="#1c7a45"/><stop offset="1" stop-color="#0d3b22"/></radialGradient>' +
      '<filter id="brillo"><feGaussianBlur stdDeviation=".7" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>' +
      '<rect width="105" height="68" rx="2.5" fill="url(#luz)"/><rect width="105" height="68" rx="2.5" fill="url(#franjas)"/><g class="lineas">' +
      '<rect x=".6" y=".6" width="103.8" height="66.8" rx="1.6"/><line x1="52.5" y1=".6" x2="52.5" y2="67.4"/><circle cx="52.5" cy="34" r="9.15"/><circle cx="52.5" cy="34" r=".5" class="punto"/>' +
      '<rect x=".6" y="13.85" width="16.5" height="40.3"/><rect x="87.9" y="13.85" width="16.5" height="40.3"/>' +
      '<rect x=".6" y="24.85" width="5.5" height="18.3"/><rect x="98.9" y="24.85" width="5.5" height="18.3"/>' +
      '<path d="M17.1 26.7 A9.15 9.15 0 0 1 17.1 41.3"/><path d="M87.9 26.7 A9.15 9.15 0 0 0 87.9 41.3"/></g>';
    tiros.forEach((t) => {
      const r = (0.8 + 2.6 * Math.min(1, t.xg)).toFixed(2);
      s += '<g class="tiro' + (t.gol ? ' gol' : '') + '"><title>' + esc((t.gol ? '⚽ Gol de ' : 'Tiro de ') + t.jugador + ' · ' + t.min + ' · xG ' + t.xg.toFixed(2) + ' · ' + t.cuerpo + (t.gol ? '' : ' · ' + t.resultado)) + '</title>' +
        '<circle cx="' + X(t.lado, t.x) + '" cy="' + Y(t.lado, t.y) + '" r="' + r + '" stroke="' + col(t.lado) + '" fill="' + (t.gol ? col(t.lado) : 'none') + '"/>' +
        (t.gol ? '<text x="' + X(t.lado, t.x) + '" y="' + (Number(Y(t.lado, t.y)) + 0.9).toFixed(2) + '" class="bal">⚽</text>' : '') + '</g>';
    });
    // los 22 en su formación; el motor los mueve con el juego (data-bx/by = su lugar)
    once.forEach((j) => {
      const x = j.lado === 0 ? 3 + j.prof * 0.45 : 102 - j.prof * 0.45, y = j.lado === 0 ? 5 + j.ancho * 0.58 : 63 - j.ancho * 0.58;
      s += '<g class="jug" data-bx="' + x.toFixed(2) + '" data-by="' + y.toFixed(2) + '" data-pt="' + (j.prof === 0 ? 1 : 0) + '" style="transform: translate(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px)">' +
        '<title>' + esc(j.n + ' ' + j.nombre + (j.nota ? ' · ' + j.nota : '')) + '</title>' +
        '<circle r="2.1" fill="' + col(j.lado) + '"/><text y=".75" class="num">' + esc(j.n) + '</text>' +
        (j.nota ? '<text y="4.4" class="nota' + (j.nota >= 7.5 ? ' alta' : '') + '">' + esc(String(j.nota)) + '</text>' : '') + '</g>';
    });
    s += '<g class="balon" style="transform: translate(52.5px,34px)"><circle r="1.5" class="halo" fill="#fff"/><circle r="1" fill="#fff" filter="url(#brillo)"/></g>';
    if (letrero) s += '<g class="letrero"><rect x="32.5" y="27" width="40" height="14" rx="3"/><text x="52.5" y="36.2">' + letrero + '</text></g>';
    s += '</svg>';
    // las jugadas REALES (ESPN y los tiros de 365Scores) para el motor
    const reales = js.map((j) => ({ id: 'e' + j.seg + j.t, m: j.seg / 60, lado: j.lado, x: X(j.lado, j.x), y: Y(j.lado, j.y),
      w: (JUGADA[j.t] || [0, 0, 0])[2], txt: (JUGADA[j.t] || ['•', ''])[0] + ' <b>' + esc((JUGADA[j.t] || ['', j.t])[1]) + '</b> · ' + esc(j.equipo) + ' · ' + esc(j.min) }))
      .concat(todos.map((t) => ({ id: 't' + t.min + t.x + t.y, m: minuto(t.min), lado: t.lado, x: X(t.lado, t.x), y: Y(t.lado, t.y),
        w: 1.5 + 8 * t.xg, txt: (t.gol ? '⚽ <b>Gol</b>' : '🎯 <b>Tiro</b>') + ' · ' + esc(t.jugador) + ' · ' + esc(t.min) })))
      .sort((a, b) => a.m - b.m);
    if (k) {
      const prev = estado.motor[k];
      // al abrir la cancha, lo ya pasado no se «anuncia» otra vez (sólo lo nuevo)
      const vistas = prev ? prev.vistas : new Set(reales.slice(0, -1).map((q) => q.id));
      estado.motor[k] = Object.assign(prev || {}, { gid: estado.p365[k] || null, pausa, minuto: ahora, reales, vistas });
    }
    const ult = reales.length ? reales[reales.length - 1] : null;
    const xg = [0, 1].map((l) => todos.filter((t) => t.lado === l).reduce((a, t) => a + t.xg, 0));
    const cab = '<div class="cancha-ult"><span class="chip-ult">' + (ult ? ult.txt : '⚽ <b>En vivo</b>') + '</span>' +
      (todos.length ? '<span class="xg"><i style="background:' + c.l + '"></i>xG ' + xg[0].toFixed(2) + ' · ' + xg[1].toFixed(2) + '<i style="background:' + c.r + '"></i></span>' : '') + '</div>';
    // la ola de presión: minuto a minuto, suavizada
    const fin = Math.max(90, ahora);
    const val = new Array(Math.ceil(fin) + 1).fill(0);
    reales.forEach((q) => { const m = Math.floor(q.m); if (val[m] != null) val[m] += (q.lado === 0 ? 1 : -1) * q.w; });
    const suave = val.map((_, i) => val.slice(Math.max(0, i - 3), i + 1).reduce((a, b, kk, arr) => a + b * (kk + 1) / arr.length, 0));
    const tope = Math.max(1, ...suave.map(Math.abs)), W = 100 / (suave.length - 1);
    const pts = (signo) => suave.map((x, i) => (i * W).toFixed(2) + ',' + (12 - signo * 11 * Math.max(0, signo * x) / tope).toFixed(2)).join(' ');
    const ola = '<svg class="presion-svg" viewBox="0 0 100 24" preserveAspectRatio="none" aria-label="Presión minuto a minuto">' +
      '<polygon points="0,12 ' + pts(1) + ' 100,12" fill="' + c.l + '" opacity=".85"/><polygon points="0,12 ' + pts(-1) + ' 100,12" fill="' + c.r + '" opacity=".85"/>' +
      '<line x1="50" y1="2" x2="50" y2="22" class="eje"/><line x1="0" y1="12" x2="100" y2="12" class="eje"/></svg>';
    const form = d && d.formacion && (d.formacion[0] || d.formacion[1]) ? '<small class="tenue">' + esc(d.formacion[0] || '') + ' vs ' + esc(d.formacion[1] || '') + '</small>' : '';
    const leyenda = '<div class="cancha-ley"><span><i class="l-tiro"></i>tiro</span><span><i class="l-gol"></i>gol</span><span>tamaño = peligro (xG)</span>' +
      '<span class="tenue">animación aproximada según el juego</span></div>';
    return '<div class="cancha">' + cab + s + leyenda + '<div class="cancha-tit"><span>Presión minuto a minuto</span>' + form + '</div>' + ola + '</div>';
  }
  // v431 — EL MOTOR: QUE LA CANCHA SE VEA COMO EL PARTIDO. El usuario: «no me
  // gusta que las bolitas se queden estáticas… no se entienden las circunferencias
  // blancas… en el medio tiempo el balón se sigue moviendo». Ninguna fuente gratis
  // da la posición de los 22 en vivo (Sofascore la paga y bloquea su API), así que
  // la animación se ARMA con lo que sí hay, y lo dice:
  //   · quién ataca AHORA: lo que cambió en el último minuto en 365Scores (pases
  //     en el último tercio, posesiones ganadas arriba, remates, grandes ocasiones,
  //     córners) y, si no, la posesión y las jugadas de ESPN;
  //   · el balón anda por esa zona y, cuando llega una jugada REAL con lugar (tiro,
  //     córner, falta…), salta ahí con su etiqueta;
  //   · los 22 se mueven con el balón (el bloque sube o baja, se cierran a su lado);
  //   · en el medio tiempo y al final, todo se detiene y la cancha lo dice.
  const STATS_ATAQUE = { 80: 1, 84: 1.5, 3: 2.5, 4: 3, 24: 4, 8: 2 };     // id de 365Scores → peso
  estado.s365 = {}; estado.motor = {};
  async function stats365(gid) {
    try {
      const r = await fetch(API365 + 'game/stats/?' + P365 + '&games=' + gid);
      const j = r.ok ? await r.json() : null;
      const comp = ((j && j.competitors) || []).map((c) => c.id);
      const fila = {};
      ((j && j.statistics) || []).filter((s) => s.filterId == null || s.filterId === -1).forEach((s) => {
        const lado = comp.indexOf(s.competitorId);
        if (lado < 0) return;
        fila[s.id] = fila[s.id] || [0, 0];
        fila[s.id][lado] = parseFloat(String(s.value).replace('%', '')) || 0;
      });
      const h = estado.s365[gid] = (estado.s365[gid] || []).concat([{ t: Date.now(), v: fila }]).slice(-6);
      return h;
    } catch (e) { return estado.s365[gid] || []; }
  }
  // dominio: de −1 (ataca el visitante) a +1 (ataca el local), con lo del último minuto
  function dominio(k) {
    const m = estado.motor[k] || {};
    const h = m.gid ? estado.s365[m.gid] || [] : [];
    let a = 0, b = 0;
    if (h.length >= 2) {
      const x = h[h.length - 1].v, y = h[Math.max(0, h.length - 3)].v;
      for (const [id, w] of Object.entries(STATS_ATAQUE)) {
        const n = x[id], o = y[id] || [0, 0];
        if (n) { a += w * Math.max(0, n[0] - o[0]); b += w * Math.max(0, n[1] - o[1]); }
      }
    }
    // y las jugadas reales de los últimos 4 minutos
    const ahora = m.minuto || 0;
    (m.reales || []).filter((q) => q.m >= ahora - 4).forEach((q) => { if (q.lado === 0) a += q.w; else b += q.w; });
    if (a + b > 0) return Math.max(-1, Math.min(1, (a - b) / (a + b + 2)));
    const pos = (h.length && h[h.length - 1].v[10]) || null;
    return pos ? Math.max(-0.6, Math.min(0.6, (pos[0] - 50) / 40)) : 0;
  }
  const azar = () => (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;   // ~normal, de −1 a 1
  function moverCanchas() {
    document.querySelectorAll('.cancha-svg[data-motor]').forEach((svg) => {
      const k = svg.dataset.motor, m = estado.motor[k];
      if (!m) return;
      const quieto = m.pausa;                     // medio tiempo / final / aún no empieza
      let bx = 52.5, by = 34;
      if (!quieto) {
        const nueva = (m.reales || []).find((q) => q.id && !m.vistas.has(q.id));
        if (nueva) {                              // una jugada REAL: el balón va ahí y se anuncia
          m.vistas.add(nueva.id); bx = Number(nueva.x); by = Number(nueva.y);
          const et = svg.parentElement && svg.parentElement.querySelector('.chip-ult');
          if (et && nueva.txt) { et.innerHTML = nueva.txt; et.classList.remove('nuevo'); void et.offsetWidth; et.classList.add('nuevo'); }
        } else {
          const d = dominio(k);
          bx = Math.max(8, Math.min(97, 52.5 + d * 30 + azar() * 13));
          by = Math.max(6, Math.min(62, (m.by == null ? 34 : m.by * 0.5 + 17) + azar() * 15));
        }
      }
      m.bx = bx; m.by = by;
      const b = svg.querySelector('.balon');
      if (b) b.style.transform = 'translate(' + bx.toFixed(2) + 'px,' + by.toFixed(2) + 'px)';
      // los 22: el bloque sigue al balón; el portero casi no se mueve
      svg.querySelectorAll('.jug[data-bx]').forEach((j) => {
        const x0 = Number(j.dataset.bx), y0 = Number(j.dataset.by), pt = j.dataset.pt === '1';
        let x = x0, y = y0;
        if (!quieto) {
          x = x0 + (bx - 52.5) * (pt ? 0.06 : 0.32) + (pt ? 0 : azar() * 0.9);
          y = y0 + (by - y0) * (pt ? 0.25 : 0.14) + (pt ? 0 : azar() * 0.9);
        }
        j.style.transform = 'translate(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px)';
      });
    });
  }
  setInterval(moverCanchas, 1500);

  function miniStats(v) {
    if (!v || !v.stats) return '';
    if (v.fase === 'in' && statsVacias(v)) return AVISO_SIN_STATS;
    const q = [['totalShots', 'Tiros'], ['shotsOnTarget', 'A puerta'], ['wonCorners', 'Córners']].filter(([k]) => v.stats[k]);
    if (!q.length && !v.stats.possessionPct) return '';
    return '<div class="mini" style="' + varsColor(v) + '">' + posesion(v) + q.map(([k, n]) => filaStat(n, v.stats[k].v[0], v.stats[k].v[1], true)).join('') + '</div>';
  }
  const SECCIONES_FUT = [
    ['Lo principal', [['totalShots', 'Tiros totales'], ['shotsOnTarget', 'Tiros a puerta'], ['wonCorners', 'Córners'], ['saves', 'Paradas del portero']]],
    ['Ataque y pases', [['accuratePasses', 'Pases buenos'], ['totalPasses', 'Pases'], ['totalCrosses', 'Centros'], ['offsides', 'Fueras de lugar']]],
    ['Disciplina', [['foulsCommitted', 'Faltas'], ['yellowCards', 'Amarillas'], ['redCards', 'Rojas']]],
  ];
  function estadisticas(p, v) {
    if (v.fase === 'in' && statsVacias(v)) return AVISO_SIN_STATS;
    let h = posesion(v);
    if (p.deporte === 'Fútbol') {
      for (const [tit, filas] of SECCIONES_FUT) {
        const f = filas.filter(([k]) => v.stats[k]);
        if (!f.length) continue;
        h += '<div class="seccion"><div class="sec-tit">' + tit + '</div>' + f.map(([k, n]) => filaStat(n, v.stats[k].v[0], v.stats[k].v[1])).join('') + '</div>';
      }
    } else {
      h += '<div class="seccion">' + Object.keys(v.stats).slice(0, 10).map((k) =>
        filaStat(TRAD[v.stats[k].label] || v.stats[k].label, v.stats[k].v[0], v.stats[k].v[1])).join('') + '</div>';
    }
    return h;
  }
  // v379 — UNA TARJETA POR PARTIDO. El usuario: «que no haya partidos
  // repetidos, ni de tenis ni de fútbol ni de ningún deporte». Antes iba una
  // tarjeta por apuesta: un partido con dos apuestas salía dos veces. Ahora
  // el partido sale una vez y sus apuestas van dentro (la mejor primero); si
  // la misma apuesta llegara dos veces, se queda una.
  // los dos nombres en cualquier orden («A vs B» y «B vs A» son el mismo partido)
  const clavePartido = (p) => [p.deporte || '', lados(p).map((x) => x.toLowerCase().trim()).sort().join(' / '), diaDe(p)].join('|');
  function agrupar(lista) {
    const g = new Map();
    for (const p of lista) {
      const k = clavePartido(p);
      if (!g.has(k)) g.set(k, []);
      const ya = g.get(k);
      if (!ya.some((x) => String(x.apuesta).trim() === String(p.apuesta).trim())) ya.push(p);
    }
    for (const ps of g.values()) ps.sort((a, b) => (b.elige - a.elige) || ((b.prob || 0) - (a.prob || 0)));
    return [...g.values()];
  }
  // v430 — «que cada pick tenga su verde o rojo en cuanto acaba el partido».
  // Lo oficial lo pone el servidor al liquidar (cada 1-2 h); mientras, la página
  // lo califica con el marcador en vivo (ESPN / Flashscore) en cuanto se decide
  // (un «Más de» ya cumplido, un «Menos de» ya pasado o el partido terminado).
  // Los marcadores del día siguen contando sólo lo oficial.
  function estadoVisto(p, v) {
    if (['verde', 'roja', 'nula'].includes(p.estado)) return p.estado;
    const pr = progreso(p, v || vivoDe([p]));
    return pr && (pr.e === 'verde' || pr.e === 'roja') ? pr.e : p.estado;
  }
  function estadoPick(p, v) {
    const e = estadoVisto(p, v);
    if (e !== p.estado) return e === 'verde' ? '<span class="et verde" title="Al pitazo; el servidor lo confirma">✅ Verde</span>' : '<span class="et roja" title="Al pitazo; el servidor lo confirma">❌ Roja</span>';
    if (p.estado === 'verde') return '<span class="et verde">✅ Verde</span>';
    if (p.estado === 'roja') return '<span class="et roja">❌ Roja</span>';
    if (p.estado === 'nula') return '<span class="et">Nula</span>';
    return '';
  }
  // v391 — lo que la IA opina de ESTE pick (sólo si está en contra se avisa en la fila)
  function iaDelPick(p) {
    const a = window.SPX && SPX.yo.ia ? SPX.yo.ia[p.partido] : null;
    const v = a && (a.veredictos || []).find((x) => String(x.apuesta).trim() === String((SPX.yo.desbloqueados || {})[p.id] || p.apuesta).trim());
    return v && v.opinion === 'en_contra' ? '<div class="ia-aviso">🤖 La IA lo ve en contra: ' + esc(v.motivo) + '</div>' : '';
  }
  function filaPick(p, v, varias) {
    if (p.solo_analisis) {
      return '<div class="pick-fila analisis"><small class="tenue">📊 Sin pick sugerido' +
        (p.apuesta ? ' · ' + (p.fuente === 'casa' ? 'la casa ve' : 'el modelo ve') + ' <b>' + esc(p.apuesta) + '</b>' + (p.prob ? ' (' + pct(p.prob) + ')' : '') : '') + '</small></div>';
    }
    const pr = progreso(p, v);
    const nv = nivel(p);
    const ev = estadoVisto(p, v);
    return '<div class="pick-fila ' + (ev === 'verde' ? 'verde' : ev === 'roja' ? 'roja' : '') + '">' +
      ((varias || ev === 'verde' || ev === 'roja') ? '<div class="fila"><span class="et nivel ' + nv.c + '">' + nv.i + ' ' + nv.n + '</span>' + estadoPick(p, v) + '</div>' : '') +
      '<div class="apuesta">' + (window.SPX ? SPX.apuesta(p) : esc(p.apuesta)) + '</div>' +
      (pr ? '<div class="progreso ' + pr.e + '">' + esc(pr.t) + '</div>' : '') + iaDelPick(p) +
      '<div class="datos"><div class="dato"><small>Cuota</small><b>' + (p.cuota ? Number(p.cuota).toFixed(2) : '—') + '</b></div>' +
      '<div class="dato"><small>Probabilidad</small><b>' + pct(p.prob) + '</b></div>' +
      '<div class="dato"><small>' + (p.tipo === 'error' ? 'Paga de más' : 'Nivel') + '</small><b>' +
      (p.tipo === 'error' ? '+' + Math.round(100 * (p.ventaja || 0)) + ' %' : grado(p)) + '</b></div></div>' +
      (p.tipo === 'error' && p.porque ? '<div class="porque">' + esc(p.porque) + ' · riesgo alto: apuesta poco</div>' : '') +
      (window.SPX ? SPX.extra(p) : '') + '</div>';
  }
  // ---------- v396: COMBINADAS ----------
  const ICONO_DEP = { 'Fútbol': '⚽', Tenis: '🎾', NFL: '🏈', NBA: '🏀', NHL: '🏒', MLB: '⚾', KBO: '⚾', Mixta: '🔀' };
  const porId = () => { if (!estado._porId || estado._porIdN !== estado.picks.length) { estado._porId = new Map(estado.picks.map((p) => [p.id, p])); estado._porIdN = estado.picks.length; } return estado._porId; };
  function faseCombinada(c) {
    if (c.estado === 'verde' || c.estado === 'roja' || c.estado === 'nula') return 'terminado';
    const empezo = (c.patas || []).some((x) => { const d = aFecha(x.inicio); return d && d <= new Date(); });
    return empezo ? 'vivo' : 'proximo';
  }
  function tarjetaCombinada(c) {
    const m = porId();
    const patas = (c.patas || []).map((x) => {
      const p = m.get(x.id) || x;
      const ev = m.get(x.id) ? estadoVisto(p) : p.estado;          // v430 — al pitazo
      const e = ev === 'verde' ? '✅' : ev === 'roja' ? '❌' : ev === 'nula' ? '➖' : '⏳';
      const txt = window.SPX && m.get(x.id) ? SPX.apuesta(p) : esc(x.apuesta);
      return '<div class="comb-pata"' + (m.get(x.id) ? ' data-ficha="' + esc(x.id) + '" role="button" tabindex="0"' : '') + '><span>' + e + '</span><div><b>' + txt + '</b><small>' + (ICONO_DEP[x.deporte] || '•') + ' ' + esc(x.partido || '') +
        ' · ' + Number(x.cuota || 0).toFixed(2) + ' · ' + pct(x.prob) + (x.ia === 'a_favor' ? ' · 🤖 a favor' : '') + '</small></div>' +
        (m.get(x.id) ? '<i class="comb-ir">›</i>' : '') + '</div>';
    }).join('');
    const evs = (c.patas || []).map((x) => (m.get(x.id) ? estadoVisto(m.get(x.id)) : x.estado));
    const ce = c.estado !== 'pendiente' && c.estado !== 'vivo' ? c.estado
      : evs.includes('roja') ? 'roja' : evs.length && evs.every((e) => e === 'verde' || e === 'nula') && evs.includes('verde') ? 'verde' : c.estado;
    c = Object.assign({}, c, { estado: ce });
    const est = c.estado === 'verde' ? '<span class="et verde">✅ Verde</span>' : c.estado === 'roja' ? '<span class="et roja">❌ Roja</span>'
      : faseCombinada(c) === 'vivo' ? '<span class="et vivo"><i class="punto"></i>En juego</span>' : '<span class="et">⏳ ' + esc(horaCdmx(aFecha(c.inicio))) + '</span>';
    return '<div class="dest comb ' + (c.estado === 'verde' ? 'verde' : c.estado === 'roja' ? 'roja' : '') + '">' +
      '<div class="fila"><span class="et nivel">' + (ICONO_DEP[c.alcance] || '🔗') + ' ' + esc(c.alcance) + (c.tipo === 'alta' ? ' · cuota alta' : '') + '</span>' + est + '</div>' +
      patas + '<div class="dest-pie"><b>' + Number(c.cuota || 0).toFixed(2) + '</b><span>probabilidad ' + pct(c.prob) + '</span></div>' +
      (window.SPX && SPX.extraComb ? SPX.extraComb(c) : '') + '</div>';
  }
  // v421 — «actualiza el historial de las combinadas con la mejora, desde la misma
  // fecha que las demás». Las de 2 patas hasta el 21-oct son la SIMULACIÓN del
  // método nuevo (v420) con esos partidos reales (`combinadas_simuladas.json`);
  // desde el 22-oct, las publicadas. Las de 3 patas, todas reales.
  const DESDE_NUEVO = '2026-10-22';
  function histCombinadas() {
    const sim = (estado.combSim && estado.combSim.combinadas) || [];
    const t = (estado.combinadas || []).filter((c) => (c.estado === 'verde' || c.estado === 'roja') && (c.tipo === 'alta' || c.fecha >= DESDE_NUEVO))
      .concat(sim.filter((c) => c.estado === 'verde' || c.estado === 'roja'));
    if (!t.length) return '<p class="tenue">Aún no termina ninguna combinada. Aquí se van a ver sus verdes y rojas, sin quitar nada.</p>';
    const fila = (titulo, xs) => { const v = xs.filter((c) => c.estado === 'verde').length, r = xs.length - v;
      return '<div class="ia-fila"><span>' + titulo + '</span><b>✅ ' + v + ' ❌ ' + r + '</b><small>' + (xs.length ? pct(v / xs.length) : '—') + '</small></div>'; };
    return fila('🔗 Combinadas (2 patas)', t.filter((c) => c.tipo !== 'alta')) + fila('🔗 Cuota alta (3 patas)', t.filter((c) => c.tipo === 'alta')) +
      fila('🔀 Mixtas', t.filter((c) => c.alcance === 'Mixta')) +
      (sim.length ? '<p class="tenue chico">Las de 2 patas del ' + esc(estado.combSim.desde.slice(8)) + ' al ' + esc(estado.combSim.hasta.slice(8)) +
        ' de oct. son el método nuevo simulado con esos partidos reales; desde el 22, las publicadas.</p>' : '');
  }
  function tarjeta(ps) {
    const p = ps[0];
    const v = vivoDe(ps);
    const nv = nivel(p);
    const [L, V] = lados(p);
    const marc = v && v.fase !== 'pre' ? v.g[0] + ' - ' + v.g[1] : (p.marcador || '');
    const est = ps.map((x) => estadoVisto(x, v));
    const todas = est.every((e) => e === 'verde' || e === 'roja' || e === 'nula');
    const clase = ['tarjeta', nv.c, todas && est.every((e) => e !== 'roja') ? 'verde' : '', todas && est.every((e) => e === 'roja') ? 'roja' : ''].join(' ');
    const cab = todas && !(v && v.fase === 'in') ? '<span class="et">Terminado</span>' : etiquetaEstado(dict(p, { estado: 'pendiente' }), v);
    return '<article class="' + clase + '" data-id="' + esc(p.id) + '">' +
      '<div class="fila"><div class="etiquetas"><span class="et nivel ' + nv.c + '">' + nv.i + ' ' + nv.n + '</span>' +
      '<span class="et">' + esc(p.deporte || '') + '</span>' + (ps.length > 1 ? '<span class="et">' + ps.length + ' apuestas</span>' : '') + '</div>' + cab + '</div>' +
      '<div class="equipos"><div class="eq">' + escudo(p.logo_h, L) + '<span>' + esc(L) + '</span></div>' +
      '<div class="marc">' + (marc ? esc(marc) : 'vs') + '</div>' +
      '<div class="eq der"><span>' + esc(V) + '</span>' + escudo(p.logo_a, V) + '</div></div>' +
      '<div class="liga">' + esc(p.liga || '') + ' · ' + esc(horaCdmx(aFecha(p.inicio))) + '</div>' +
      contextoHtml((ps.find((x) => x.ctx) || {}).ctx, L, V) +
      iaBloque(p, L, V, (ps.find((x) => x.ctx) || {}).ctx) +
      miniStats(v) + (v && v.fase === 'in' ? cancha(v, p) : '') +
      ps.map((x) => filaPick(x, v, ps.length > 1)).join('') +
      (ps.some((x) => x.espn) ? '<button class="ver" data-ficha="' + esc((ps.find((x) => x.espn) || p).id) + '">Ver partido →</button>' : '') +
      '</article>';
  }
  const dict = (a, b) => Object.assign({}, a, b);
  // v384 — «un H2H en las tarjetas por si la gente quiere analizar el partido»
  // v387 — el análisis y la predicción de la IA (Gemini), medida aparte
  const pp = (x) => (x == null ? '' : ' <span class="ia-prob">(' + Math.round(100 * x) + ' %)</span>');
  // v417 — quien no es VIP VE que el partido tiene análisis de la IA, pero
  // bloqueado: al tocarlo va a Planes, al VIP. Sólo se enseña si de verdad hay
  // análisis (`ia_disponibles`: nombre del partido, nunca el contenido).
  function iaBloque(p, L, V, ctx) {
    const a = window.SPX && SPX.yo.ia ? SPX.yo.ia[p.partido] : null;
    if (a) return iaHtml(a, L, V, ctx);
    const hay = window.SPX && SPX.yo.iaHay && SPX.yo.iaHay.has(p.partido);
    if (!hay || (SPX.esVip && SPX.esVip())) return '';
    return '<button class="ctx ia ia-bloq" data-vista-ir="planes" data-foco="plan-vip">🤖 Análisis IA <span class="candado">🔒 VIP</span></button>';
  }
  function iaHtml(a, L, V, ctx) {
    if (!a) return '';
    const res = { local: 'gana ' + L, empate: 'empate', visita: 'gana ' + V }[a.pred_resultado] || '';
    // v407 — el mismo template para todos los deportes, con su unidad
    const dep = a.deporte || 'Fútbol', fut = dep === 'Fútbol';
    const U = { 'Fútbol': 'goles', NHL: 'goles', NBA: 'puntos', NFL: 'puntos', MLB: 'carreras', KBO: 'carreras', Tenis: 'sets' }[dep] || 'puntos';
    const lin = (x) => (x > 0 ? '+' : '') + x;
    const hand = a.linea_handicap == null || !a.pred_handicap ? null
      : (a.pred_handicap === 'local' ? L + ' ' + lin(a.linea_handicap) : V + ' ' + lin(-a.linea_handicap));
    const est = a.evaluado ? (a.ok_resultado ? ' · <b class="txt-verde">✅ acertó</b>' : ' · <b class="txt-rojo">❌ falló</b>') : '';
    return '<details class="ctx ia"><summary>🤖 Análisis IA' + est + '</summary>' +
      '<p class="ia-txt">' + esc(a.analisis || '') + '</p>' +
      '<div class="ia-pred">La IA ve: <b>' + esc(res) + '</b> · ' + L.slice(0, 14) + ' ' + Math.round(100 * (a.p_local || 0)) + ' %' +
      (a.p_empate ? ' · empate ' + Math.round(100 * a.p_empate) + ' %' : '') + ' · ' + V.slice(0, 14) + ' ' + Math.round(100 * (a.p_visita || 0)) + ' %</div>' +
      '<div class="ia-pred">' + (fut && a.pred_goles ? 'Goles: <b>' + (a.pred_goles === 'mas' ? 'más de 2.5' : 'menos de 2.5') + '</b>' + pp(a.prob_goles) + ' · ' : '') +
      'confianza ' + '★'.repeat(a.confianza || 0) + '☆'.repeat(5 - (a.confianza || 0)) + '</div>' +
      // v392 — más precisa: marcador, goles esperados, ambos anotan, córners, tarjetas (con ✅/❌ al terminar)
      '<div class="ia-grid">' + [
        // v396 — con la probabilidad que le da la IA a cada predicción
        a.marcador_ia ? ['⚽ Marcador', a.marcador_ia, a.ok_marcador, a.prob_marcador] : null,
        a.goles_esperados != null ? ['🥅 Goles esperados', String(a.goles_esperados), null, null] : null,
        // v407 — el total y el hándicap, en todos los deportes
        a.linea_total != null && a.pred_total ? ['📊 Total de ' + U, (a.pred_total === 'mas' ? 'Más' : 'Menos') + ' de ' + a.linea_total +
          (a.total_esperado != null ? ' (~' + a.total_esperado + ')' : ''), a.ok_total, a.prob_total] : null,
        hand ? ['⚖️ Hándicap', hand, a.ok_handicap, a.prob_handicap] : null,
        a.btts ? ['🎯 Ambos anotan', a.btts === 'si' ? 'Sí' : 'No', a.ok_btts, a.prob_ambos == null ? null : (a.btts === 'si' ? a.prob_ambos : 1 - a.prob_ambos)] : null,
        a.linea_corners != null ? ['🚩 Córners', (a.pred_corners === 'mas' ? 'Más' : 'Menos') + ' de ' + a.linea_corners + (a.corners_esperados != null ? ' (~' + a.corners_esperados + ')' : ''), a.ok_corners, a.prob_corners] : null,
        a.linea_tarjetas != null ? ['🟨 Tarjetas', (a.pred_tarjetas === 'mas' ? 'Más' : 'Menos') + ' de ' + a.linea_tarjetas + (a.tarjetas_esperadas != null ? ' (~' + a.tarjetas_esperadas + ')' : ''), a.ok_tarjetas, a.prob_tarjetas] : null,
      ].filter(Boolean).map(([t, v, ok, pr]) => '<div><small>' + t + '</small><b>' + esc(v) + (ok === true ? ' ✅' : ok === false ? ' ❌' : '') + '</b>' +
        (pr != null ? '<span class="ia-prob">probabilidad ' + Math.round(100 * pr) + ' %</span>' : '') + '</div>').join('') + '</div>' +
      // v394 — qué metería la IA (cualquier mercado) y los goles de cada equipo
      (a.mejor_apuesta ? '<div class="ia-meter">🧠 Lo que metería la IA: <b>' + esc(a.mejor_apuesta) + '</b>' +
        (a.prob_mejor_apuesta != null ? ' · ' + Math.round(100 * a.prob_mejor_apuesta) + ' %' : '') + '</div>' : '') +
      (a.goles_local_esperados != null && a.goles_visita_esperados != null
        ? filaStat(U.charAt(0).toUpperCase() + U.slice(1) + ' esperados', a.goles_local_esperados, a.goles_visita_esperados, true) : '') +
      (ctx && ctx.sl && ctx.sv ? '<div class="ctx-tit">📊 Lo que usó (promedio de sus últimos partidos)</div>' +
        [['gf', 'Goles a favor'], ['gc', 'Goles en contra'], ['cor', 'Córners'], ['tap', 'Tiros a puerta'], ['tar', 'Amarillas']]
          .filter(([k]) => ctx.sl[k] != null && ctx.sv[k] != null)
          .map(([k, et]) => filaStat(et, ctx.sl[k], ctx.sv[k], true)).join('') : '') +
      (a.pick_ia && a.pick_ia !== 'ninguno' ? '<div class="ia-pred">Su pick favorito: <b>' + esc(a.pick_ia) + '</b> ' + (a.coincide ? '✅ coincide con nuestro análisis' : '⚠️ ve el partido distinto') + '</div>' : '') +
      (a.veredictos && a.veredictos.length ? '<div class="ia-ver">' + a.veredictos.map((v) =>
        '<div class="' + (v.opinion === 'en_contra' ? 'contra' : 'favor') + '">' + (v.opinion === 'en_contra' ? '❌ En contra' : '✅ A favor') +
        ': <b>' + esc(v.apuesta) + '</b> — ' + esc(v.motivo) + (v.estado === 'verde' ? ' · salió ✅' : v.estado === 'roja' ? ' · salió ❌' : '') + '</div>').join('') + '</div>' : '') +
      '<p class="tenue chico">La IA es experimental y la medimos aparte (Historial → 🤖). Nuestros picks NO dependen de ella.</p></details>';
  }
  function formaHtml(f) {
    return String(f || '').split('').map((c) => '<i class="fr ' + ({ G: 'g', E: 'e', P: 'p' }[c] || '') + '">' + c + '</i>').join('');
  }
  function contextoHtml(ctx, L, V) {
    if (!ctx) return '';
    let h = '<details class="ctx"><summary>📋 Antes del partido: forma y H2H</summary>';
    if (ctx.fl || ctx.fv) {
      h += '<div class="ctx-tit">Últimos 5 partidos (el más reciente a la derecha)</div>' +
        '<div class="ctx-f"><span>' + esc(L) + '</span><span>' + formaHtml(ctx.fl) + '</span></div>' +
        '<div class="ctx-f"><span>' + esc(V) + '</span><span>' + formaHtml(ctx.fv) + '</span></div>';
    }
    // v391 — promedios de los últimos 10 de cada uno, con barras (como SofaScore)
    if (ctx.sl && ctx.sv) {
      const pc = (x) => (x == null ? '-' : Math.round(100 * x) + ' %');
      const filas = [['gf', 'Goles a favor', (x) => x], ['gc', 'Goles en contra', (x) => x], ['o25', 'Partidos con +2.5 goles', pc],
        ['btts', 'Ambos anotan', pc], ['cor', 'Córners', (x) => x], ['tap', 'Tiros a puerta', (x) => x], ['tar', 'Amarillas', (x) => x], ['pos', 'Posesión %', (x) => x]]
        .filter(([k]) => ctx.sl[k] != null && ctx.sv[k] != null);
      h += '<div class="ctx-tit">Promedio de sus últimos ' + Math.min(ctx.sl.n, ctx.sv.n) + ' partidos</div><div class="leyenda"><span class="l">' + esc(L) + '</span><span class="r">' + esc(V) + '</span></div>' +
        filas.map(([k, et, f]) => filaStat(et, f(ctx.sl[k]), f(ctx.sv[k]), true)).join('');
    }
    if (ctx.h2h && ctx.h2h.length) {
      h += '<div class="ctx-tit">Últimos enfrentamientos</div>' + ctx.h2h.map((x) =>
        '<div class="ctx-h"><small>' + esc(x[0]) + '</small><span>' + esc(x[1]) + '</span><b>' + esc(x[2]) + '</b><span>' + esc(x[3]) + '</span></div>').join('');
    } else if (ctx.sl || ctx.sv) {
      // v415 — sin H2H se dice (antes la sección desaparecía y parecía un fallo)
      h += '<div class="ctx-tit">Últimos enfrentamientos</div><p class="tenue">No se han enfrentado en nuestros registros.</p>';
    }
    if (ctx.bl || ctx.bv) {
      h += '<div class="ctx-tit">Bajas</div>' +
        (ctx.bl ? '<div class="ctx-b"><b>' + esc(L) + ':</b> ' + ctx.bl.map(esc).join(', ') + '</div>' : '') +
        (ctx.bv ? '<div class="ctx-b"><b>' + esc(V) + ':</b> ' + ctx.bv.map(esc).join(', ') + '</div>' : '');
    }
    return h + '<p class="tenue chico">G = ganó · E = empató · P = perdió. Es información para que analices; el pick ya la toma en cuenta a través del mercado.</p></details>';
  }

  // ---------- FICHA DEL PARTIDO (tipo SofaScore) ----------
  let fichaId = null;
  // v380 — el usuario: «en los terminados, al picarle en Ver partido no se
  // ven las estadísticas». Lo en vivo sólo pide los partidos en juego; uno
  // terminado se pide a ESPN al abrir su ficha (una vez) y se pinta igual.
  async function pedirResumen(p) {
    if (!p.espn || estado.vivo[p.espn]) return;
    const [ruta, id] = p.espn.split(':');
    try {
      const r = await fetch(ESPN + ruta + '/summary?event=' + id);
      if (r.ok) estado.vivo[p.espn] = leerResumen(await r.json(), p);
    } catch (e) { /* sin red: la ficha queda sin estadísticas */ }
  }
  function ficha(id) {
    const p = estado.picks.find((x) => x.id === id); if (!p) return;
    fichaId = id;
    if (p.espn && !estado.vivo[p.espn]) { pedirResumen(p).then(() => { if (fichaId === id) ficha(id); pintar(); }); }
    const v = estado.vivo[p.espn];
    const [L, V] = lados(p);
    const otras = (agrupar(estado.picks.filter((x) => clavePartido(x) === clavePartido(p)))[0]) || [p];
    let h = '<button class="cerrar" data-cerrar>✕</button>' +
      '<div class="equipos grande"><div class="eq">' + escudo(p.logo_h, L) + '<span>' + esc(L) + '</span></div>' +
      '<div class="marc">' + (v && v.fase !== 'pre' ? v.g[0] + ' - ' + v.g[1] : 'vs') + '<small>' + esc(v ? v.detalle : horaCdmx(aFecha(p.inicio))) + '</small></div>' +
      '<div class="eq der"><span>' + esc(V) + '</span>' + escudo(p.logo_a, V) + '</div></div>';
    h += cancha(v, p);                   // v427/v429 — la cancha en vivo
    setTimeout(vivo365, 50);
    h += '<h3>Nuestras apuestas en este partido</h3>' + otras.map((x) => {
      const pr = progreso(x, v);
      return '<div class="linea-ap"><span>' + nivel(x).i + ' ' + (window.SPX ? SPX.apuesta(x) : esc(x.apuesta)) + ' · ' + (x.cuota ? Number(x.cuota).toFixed(2) : '') + '</span>' +
        (pr ? '<span class="progreso ' + pr.e + '">' + esc(pr.t) + '</span>' : '<span class="tenue">' + pct(x.prob) + '</span>') + '</div>';
    }).join('');
    if (v && Object.keys(v.stats).length) {
      h += '<h3>Estadísticas</h3><div class="leyenda"><span class="l">' + esc(L) + '</span><span class="r">' + esc(V) + '</span></div>' + estadisticas(p, v);
    } else {
      h += '<p class="tenue">Las estadísticas aparecen aquí en cuanto empieza el partido.</p>';
    }
    if (v && v.eventos.length) {
      h += '<h3>Lo que ha pasado</h3>' + v.eventos.slice().reverse().slice(0, 25).map((e) =>
        '<div class="evento ' + (e.lado ? 'der' : '') + '"><b>' + esc(e.min) + '</b> ' + e.ico + ' ' + esc(e.texto) + '</div>').join('');
    }
    $('ficha-cuerpo').innerHTML = h;
    $('ficha-cuerpo').setAttribute('style', varsColor(v));
    $('ficha').hidden = false;
  }
  function refrescarFicha() { if (fichaId && !$('ficha').hidden) ficha(fichaId); }

  // ---------- PINTAR ----------
  // ---------- v380: LA PÁGINA COMO APP ----------
  // El usuario: «está muy larga de scrollear, tiene un buen de partidos, es
  // mucho escanear… que sea más fácil, más intuitiva, que no sea aburrida».
  // Antes: una tira con 120 tarjetas grandes. Ahora: barra de abajo con
  // pantallas (Picks · En vivo · Mis picks · Historial · Planes), 💎 Destacados
  // en carrusel, y la lista COMPACTA POR LIGA (una línea por partido, como
  // SofaScore) que se abre al tocarla con la tarjeta completa.
  estado.vista = 'picks';
  estado.fase = 'todos';
  estado.busca = '';
  estado.liga = '';
  estado.abiertos = new Set();
  estado.ligasCerradas = new Set();
  estado.verFinales = false;

  function vivoDe(ps) {
    const x = ps.find((q) => q.espn);
    return (x && estado.vivo[x.espn]) || estado.fsPor[clavePartido(ps[0])] || null;      // v424: o Flashscore
  }
  const DURA = { 'Fútbol': 2.1, NBA: 2.6, NHL: 2.7, NFL: 3.5, MLB: 3.4, KBO: 3.4, 'Béisbol': 3.4, Tenis: 3 };
  const duracion = (dep) => (DURA[dep] || 3) * 3600e3;
  function faseDe(ps) {
    const v = vivoDe(ps);
    const fin = ps.every((x) => ['verde', 'roja', 'nula'].includes(x.estado) || (v && v.terminado && ['verde', 'roja'].includes(estadoVisto(x, v))));
    if (v && v.fase === 'in') return 'vivo';
    // v431 — «datos raros en la hora de la MLS»: ESPN dice que aún NO empieza
    // (su hora real es otra); manda ESPN y se enseña nuestra hora, no su texto
    if (v && v.fase === 'pre' && !fin) return 'proximo';
    if (fin || (v && v.terminado)) return 'terminado';
    const ini = aFecha(ps[0].inicio);
    // v421 — empezado sin dato en vivo: en juego lo que dura ESE deporte; después,
    // terminado (liquidando). Antes eran 3 h 30 min para todos y un partido de
    // fútbol (Pachuca vs Cruz Azul Sub-21) seguía «Vivo» hora y media después.
    if (ini && ini <= new Date()) return Date.now() - ini > duracion(ps[0].deporte) ? 'terminado' : 'vivo';
    return 'proximo';
  }
  function relojFila(ps) {
    const v = vivoDe(ps), f = faseDe(ps);
    if (f === 'vivo') return '<span class="rl vivo"><i class="punto"></i>' + esc(v ? (v.reloj || v.detalle || 'Vivo') : 'Vivo') + '</span>';
    if (f === 'terminado') return '<span class="rl">Final</span>';
    const d = aFecha(ps[0].inicio);
    return '<span class="rl">' + (d ? new Intl.DateTimeFormat('es-MX', { timeZone: ZONA, hour: '2-digit', minute: '2-digit' }).format(d) : '') + '</span>';
  }
  function resumenPicks(ps) {
    const v = ps.filter((x) => x.estado === 'verde').length, r = ps.filter((x) => x.estado === 'roja').length;
    if (v || r) return (v ? '<span class="ok">✅' + (v > 1 ? v : '') + '</span>' : '') + (r ? '<span class="ko">❌' + (r > 1 ? r : '') + '</span>' : '');
    return '';
  }
  // v391 — si un partido trae un dato raro, se salta (antes rompía TODA la lista y los toques ya no hacían nada)
  const seguro = (fn) => (x) => { try { return fn(x); } catch (e) { console.warn('[sharpicks] partido saltado', e); return ''; } };
  function filaPartido(ps) {
    const p = ps[0], nv = nivel(p), [L, V] = lados(p), v = vivoDe(ps);
    const k = clavePartido(p), abierto = estado.abiertos.has(k);
    const marc = v && v.fase !== 'pre' ? v.g : (p.marcador ? String(p.marcador).split('-').map((x) => x.trim()) : null);
    const ap = p.solo_analisis ? '<span class="sin-pick-txt">Sin pick</span>' : window.SPX ? SPX.apuesta(p) : esc(p.apuesta);
    return '<div class="partido-fila ' + nv.c + (abierto ? ' abierto' : '') + '" data-k="' + esc(k) + '">' +
      '<button class="pf" data-abrir="' + esc(k) + '" aria-expanded="' + abierto + '">' +
      relojFila(ps) +
      '<span class="pf-eqs"><span class="pf-eq">' + escudo(p.logo_h, L) + '<b>' + esc(L) + '</b>' + (marc ? '<em>' + esc(marc[0]) + '</em>' : '') + '</span>' +
      '<span class="pf-eq">' + escudo(p.logo_a, V) + '<b>' + esc(V) + '</b>' + (marc ? '<em>' + esc(marc[1]) + '</em>' : '') + '</span></span>' +
      '<span class="pf-pick"><span class="pf-niv">' + nv.i + '</span><span class="pf-ap">' + ap + '</span>' +
      '<span class="pf-cu">' + (p.cuota ? Number(p.cuota).toFixed(2) : '') + '</span>' +
      (ps.length > 1 ? '<span class="pf-mas">+' + (ps.length - 1) + '</span>' : '') + resumenPicks(ps) + '</span>' +
      '</button>' + (abierto ? '<div class="pf-detalle">' + tarjeta(ps) + '</div>' : '') + '</div>';
  }
  // v422 — «✨ PARA TI». Cada pick que aún no empieza (hoy y mañana) se puntúa
  // con lo que el usuario eligió (deportes y ligas) y con sus tendencias (lo que
  // sigue y desbloquea: deporte, liga, nivel y la cuota que suele jugar); entre
  // parecidos gana el más probable. Sin intereses ni señales, no sale nada.
  function paraTi() {
    if (!window.SPX || !SPX.yo.user || !SPX.intereses) return [];
    const it = SPX.intereses(), g = it.gustos || { deporte: {}, liga: {}, nivel: {}, cuotas: [], n: 0 };
    if (!it.deportes.size && !it.ligas.size && !g.n) return [];
    const parte = (m, k) => { const tot = Object.values(m).reduce((s, x) => s + x, 0); return tot ? (m[k] || 0) / tot : 0; };
    const cs = g.cuotas.slice().sort((a, b) => a - b), med = cs.length ? cs[Math.floor(cs.length / 2)] : null;
    const ahora = new Date(), dias = [diaPestana(0), diaPestana(1)];
    const puntos = (p) => {
      let s = 0;
      if (p.liga && it.ligas.has(p.liga)) s += 3;
      if (it.deportes.has(p.deporte)) s += 2;
      s += 2 * parte(g.liga, p.liga) + 1.5 * parte(g.deporte, p.deporte) + parte(g.nivel, nivel(p).n);
      if (med && p.cuota) s += Math.max(0, 1 - Math.abs(Math.log(Number(p.cuota) / med)) * 3);
      return s + Number(p.prob || 0);
    };
    const cand = estado.picks.filter((p) => p.estado === 'pendiente' && dias.includes(diaDe(p)) && (aFecha(p.inicio) || 0) > ahora);
    const mejor = new Map();
    cand.forEach((p) => { const k = clavePartido(p), s = puntos(p); if (!mejor.has(k) || mejor.get(k).s < s) mejor.set(k, { s, p }); });
    const umbral = 2 + 0.8;                       // que encaje en algo más que la probabilidad
    return [...mejor.values()].filter((x) => x.s >= umbral).sort((a, b) => b.s - a.s).slice(0, 8).map((x) => [x.p]);
  }
  // y sus ligas van primero en la lista
  function ordenPreferido(mapa) {
    if (!window.SPX || !SPX.intereses) return mapa;
    const it = SPX.intereses(), g = (it.gustos && it.gustos.liga) || {};
    const peso = (l) => (it.ligas.has(l.replace(/^🎾 /, '')) ? 2 : 0) + (g[l.replace(/^🎾 /, '')] ? 1 : 0);
    return new Map([...mapa.entries()].map((e, i) => [e, i]).sort((a, b) => (peso(b[0][0]) - peso(a[0][0])) || (a[1] - b[1])).map((x) => x[0]));
  }
  function destacado(ps, etiqueta) {
    const p = ps[0], [L, V] = lados(p), v = vivoDe(ps);
    const marc = v && v.fase !== 'pre' ? v.g[0] + ' - ' + v.g[1] : '';
    return '<button class="dest" data-abrir="' + esc(clavePartido(p)) + '" data-ir="1">' +
      '<div class="fila">' + (etiqueta || '<span class="et nivel diamante">💎 Diamante</span>') + relojFila(ps) + '</div>' +
      '<div class="dest-eqs">' + escudo(p.logo_h, L) + '<span>' + esc(marc || 'vs') + '</span>' + escudo(p.logo_a, V) + '</div>' +
      '<div class="dest-nom">' + esc(L) + ' – ' + esc(V) + '</div>' +
      '<div class="dest-ap">' + (window.SPX ? SPX.apuesta(p) : esc(p.apuesta)) + '</div>' +
      '<div class="dest-pie"><b>' + (p.cuota ? Number(p.cuota).toFixed(2) : '') + '</b><span>probabilidad ' + pct(p.prob) + '</span></div></button>';
  }
  function tiraMarcador() {
    const hoy = diaPestana(0), l0 = estado.picks.filter((p) => diaDe(p) === hoy), l = l0.filter((p) => p.tipo !== 'error'),
      t = cuenta(l), e = cuenta(l.filter((p) => p.elige)), er = cuenta(l0.filter((p) => p.tipo === 'error'));
    return '<button class="tira" data-vista-ir="historial">Hoy <b>✅ ' + t.v + ' ❌ ' + t.r + '</b> ' + pct(t.pct) +
      ' · 💎 <b>' + e.v + '-' + e.r + '</b>' + (e.pct == null ? '' : ' ' + pct(e.pct)) +
      (er.v + er.r ? ' · 💰 <b>' + er.v + '-' + er.r + '</b>' : '') + ' <span>Ver historial ›</span></button>';
  }

  // v418 — la lista de la pantalla: los picks y, en Picks y En vivo, las tarjetas de
  // «sólo análisis» de los partidos que no tienen ningún pick ese día
  function listaConAnalisis() {
    const base = listaBase();
    if (!['picks', 'vivo'].includes(estado.vista) || !(estado.analisis || []).length) return base;
    const ya = new Set(base.map(clavePartido));
    const dia = diaPestana(OFFS[estado.dia] || 0);
    const enVivo = (p) => faseDe([p]) === 'vivo';
    return base.concat(estado.analisis.filter((a) => !ya.has(clavePartido(a)) && (estado.vista === 'vivo' ? enVivo(a) && a.estado !== 'final' : diaDe(a) === dia)));
  }
  function listaBase() {
    if (estado.vista === 'mios') return window.SPX ? SPX.filtrarMios(estado.picks) : [];
    if (estado.vista === 'vivo') return estado.picks.filter((p) => faseDe([p]) === 'vivo');
    const dia = diaPestana(OFFS[estado.dia] || 0);
    return estado.picks.filter((p) => diaDe(p) === dia);
  }

  // v414 — «cuando ando analizando con la IA se cierra solita y el scroll se va
  // para abajo». Cada 30 s (marcadores en vivo), cada 3 min (picks) y al
  // renovarse la sesión la lista se vuelve a pintar: las tarjetas abiertas se
  // recordaban, pero NO las secciones de dentro (Análisis IA, forma y H2H), que
  // se cerraban; la página se encogía y el scroll brincaba. Ahora se anota qué
  // secciones estaban abiertas y dónde estaba el usuario, y se restaura.
  function memoriaVista() {
    const abiertas = new Set();
    document.querySelectorAll('[data-k] details[open]').forEach((d) => {
      const c = d.closest('[data-k]'), i = [...c.querySelectorAll('details')].indexOf(d);
      abiertas.add(c.dataset.k + '|' + d.className + '|' + i);
    });
    let ancla = null;
    for (const c of document.querySelectorAll('[data-k]')) {
      const r = c.getBoundingClientRect();
      if (r.bottom > 0 && r.height) { ancla = { k: c.dataset.k, top: r.top }; break; }
    }
    return { abiertas, ancla };
  }
  function restaurarVista(m) {
    if (!m) return;
    if (m.abiertas.size) document.querySelectorAll('[data-k]').forEach((c) => {
      [...c.querySelectorAll('details')].forEach((d, i) => { if (m.abiertas.has(c.dataset.k + '|' + d.className + '|' + i)) d.open = true; });
    });
    if (m.ancla) {
      const c = [...document.querySelectorAll('[data-k]')].find((x) => x.dataset.k === m.ancla.k);
      if (c) { const dy = c.getBoundingClientRect().top - m.ancla.top; if (Math.abs(dy) > 1) window.scrollBy(0, dy); }
    }
  }
  function pintar() {
    const m = memoriaVista();
    try { pintarLista(); } finally { try { restaurarVista(m); } catch (e) { /* nunca tumba la página */ } }
  }
  function pintarLista() {
    document.querySelectorAll('[data-vista]').forEach((s) => { s.hidden = !String(s.dataset.vista).split(' ').includes(estado.vista); });
    document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('activa', b.dataset.vistaIr === estado.vista));
    const hoy = diaPestana(0), ayer = diaPestana(-1);
    $('marcadores').innerHTML = cajaMarcador('Hoy', estado.picks.filter((p) => diaDe(p) === hoy)) +
      cajaMarcador('Ayer', estado.picks.filter((p) => diaDe(p) === ayer));
    $('tira').innerHTML = tiraMarcador();
    if (!['picks', 'vivo', 'mios', 'combinadas'].includes(estado.vista)) return;

    let lista = listaConAnalisis();
    const deps = ['Todos'].concat([...new Set(lista.map((p) => p.deporte).filter(Boolean))].sort());
    // varios a la vez: un conjunto (vacío = todos); lo que ya no hay hoy se suelta
    estado.deportes = new Set([...(estado.deportes || [])].filter((d) => deps.includes(d)));
    estado.niveles = estado.niveles || new Set();
    const ICO = { 'Fútbol': '⚽', 'Tenis': '🎾', 'NBA': '🏀', 'NFL': '🏈', 'NHL': '🏒', 'MLB': '⚾', 'Béisbol': '⚾' };
    const act = (s, v) => (v === 'Todos' ? s.size === 0 : s.has(v));
    $('deportes').innerHTML = deps.map((d) => '<button class="chip' + (act(estado.deportes, d) ? ' activa' : '') + '" data-dep="' + esc(d) + '">' + (ICO[d] ? ICO[d] + ' ' : '') + esc(d) + '</button>').join('');
    $('niveles').innerHTML = ['Todos', 'Diamante', 'Platino', 'Oro', 'Plata', 'Cuota alta'].map((n) => '<button class="chip' + (act(estado.niveles, n) ? ' activa' : '') + '" data-niv="' + n + '">' + ({ Diamante: '💎 ', Platino: '🔷 ', Oro: '🥇 ', Plata: '🥈 ', 'Cuota alta': '💰 ' }[n] || '') + n + '</button>').join('');
    const pasaDep = (p) => estado.deportes.size === 0 || estado.deportes.has(p.deporte);
    if (estado.deportes.size) lista = lista.filter(pasaDep);
    if (estado.niveles.size) lista = lista.filter((p) => estado.niveles.has(nivel(p).n));
    const q = estado.busca.trim().toLowerCase();
    if (q) lista = lista.filter((p) => (String(p.partido) + ' ' + String(p.liga || '')).toLowerCase().includes(q));
    // v380 — «en lugar de escribir, un desplegable con todas las ligas»
    const nomLiga = (p) => p.liga || p.deporte || 'Otros';
    const cuentaLigas = new Map();
    agrupar(lista).forEach((g) => { const l = nomLiga(g[0]); cuentaLigas.set(l, (cuentaLigas.get(l) || 0) + 1); });
    if (estado.liga && !cuentaLigas.has(estado.liga)) estado.liga = '';
    $('liga').innerHTML = '<option value="">🏆 Todas las ligas (' + cuentaLigas.size + ')</option>' +
      [...cuentaLigas.entries()].sort((a, b) => a[0].localeCompare(b[0], 'es'))
        .map(([l, n]) => '<option value="' + esc(l) + '"' + (l === estado.liga ? ' selected' : '') + '>' + esc(l) + ' · ' + n + '</option>').join('');
    if (estado.liga) lista = lista.filter((p) => nomLiga(p) === estado.liga);

    let grupos = agrupar(lista);
    const n = { todos: grupos.length, proximo: 0, vivo: 0, terminado: 0 };
    grupos.forEach((g) => { n[faseDe(g)]++; });
    $('fases').innerHTML = [['todos', 'Todos'], ['proximo', 'Próximos'], ['vivo', '🔴 Vivo'], ['terminado', 'Final']]
      .map(([k, t]) => '<button class="seg' + (estado.fase === k ? ' activa' : '') + '" data-fase="' + k + '">' + t + ' <small>' + n[k] + '</small></button>').join('');
    $('fases').hidden = estado.vista === 'vivo' || estado.vista === 'combinadas';
    if (estado.fase !== 'todos' && estado.vista !== 'vivo') grupos = grupos.filter((g) => faseDe(g) === estado.fase);

    // 💎 Destacados: los Diamante que aún no terminan
    const dest = estado.vista === 'picks' ? agrupar(listaBase().filter(pasaDep)).filter((g) => g[0].elige && (estado.fase === 'todos' ? faseDe(g) !== 'terminado' : faseDe(g) === estado.fase))
      .sort((a, b) => String(a[0].inicio).localeCompare(String(b[0].inicio))).slice(0, 12) : [];
    $('destacados').hidden = !dest.length;
    $('destacados-lista').innerHTML = dest.map(seguro(destacado)).join('');
    // v422 — ✨ Para ti
    const pt = estado.vista === 'picks' ? paraTi() : [];
    if ($('parati')) {
      $('parati').hidden = !pt.length;
      $('parati-lista').innerHTML = pt.map(seguro((g) => { const n = nivel(g[0]); return destacado(g, '<span class="et nivel ' + n.c + '">' + n.i + ' ' + n.n + '</span>'); })).join('');
    }
    // 🔗 Combinadas del día elegido, del deporte elegido (las mixtas siempre)
    const diaC = diaPestana(OFFS[estado.dia] || 0);
    // v398 — tienen su pestaña; en Picks sólo una línea que lleva a ella
    const combs = (estado.combinadas || []).filter((c) => c.fecha === diaC &&
      (estado.deportes.size === 0 || c.alcance === 'Mixta' || estado.deportes.has(c.alcance)));
    if ($('comb-hist')) $('comb-hist').innerHTML = histCombinadas();
    const vivas = combs.filter((c) => faseCombinada(c) !== 'terminado').length;
    $('comb-tira').innerHTML = combs.length ? '<button class="tira comb-tira" data-vista-ir="combinadas"><em>🔗 <b>' + combs.length + '</b> ' +
      (combs.length === 1 ? 'combinada' : 'combinadas') + (vivas ? '' : ' (ya jugadas)') + '</em><span>Ver ›</span></button>' : '';
    if (estado.vista === 'combinadas') {
      const orden = { vivo: 0, proximo: 1, terminado: 2 };
      $('combinadas-lista').innerHTML = combs.length ? combs.sort((a, b) => orden[faseCombinada(a)] - orden[faseCombinada(b)] ||
        (a.alcance === 'Mixta') - (b.alcance === 'Mixta') || String(a.alcance).localeCompare(b.alcance) || (a.tipo === 'alta') - (b.tipo === 'alta'))
        .map(seguro(tarjetaCombinada)).join('')
        : estado.errorCombinadas
          ? '<p class="aviso">No se pudieron consultar las combinadas. No es posible confirmar que no haya; reintenta en un momento.</p>'
          : '<p class="aviso">No hay combinadas para este día con estos filtros. Se arman con las patas de mayor probabilidad: si no hay suficientes, preferimos no darte una floja.</p>';
      return;
    }
    estado.grupos = new Map(agrupar(listaConAnalisis()).map((g) => [clavePartido(g[0]), g]));

    // por liga: en vivo primero, luego por hora; la liga con su partido más temprano
    const orden = { vivo: 0, proximo: 1, terminado: 2 };
    grupos.sort((a, b) => (orden[faseDe(a)] - orden[faseDe(b)]) || String(a[0].inicio).localeCompare(String(b[0].inicio)));
    // en «Todos», lo ya terminado va al final en UN bloque plegado (de noche
    // son la mayoría y obligaban a bajar mucho para ver lo que viene)
    const plegar = estado.fase === 'todos' && estado.vista === 'picks';
    const fin = plegar ? grupos.filter((g) => faseDe(g) === 'terminado') : [];
    if (plegar) grupos = grupos.filter((g) => faseDe(g) !== 'terminado');
    const porLiga = (gs0) => {
      const m = new Map();
      gs0.forEach((g) => { const l = (g[0].deporte === 'Tenis' ? '🎾 ' : '') + (g[0].liga || g[0].deporte || 'Otros'); if (!m.has(l)) m.set(l, []); m.get(l).push(g); });
      return m;
    };
    const ligas = ordenPreferido(porLiga(grupos));
    let finHtml = '';
    if (fin.length) {
      const ps = fin.flat(), v = ps.filter((x) => x.estado === 'verde').length, r = ps.filter((x) => x.estado === 'roja').length;
      finHtml = '<button class="fin-cab" data-ver-fin>' + (estado.verFinales ? '▾' : '▸') + ' Terminados · ' + fin.length + ' partidos · <b>✅ ' + v + ' ❌ ' + r + '</b></button>' +
        (estado.verFinales ? '<div class="fin-lista">' + pintarLigas(porLiga(fin)) + '</div>' : '');
    }
    $('tarjetas').innerHTML = pintarLigas(ligas) + finHtml;
    function pintarLigas(mapa) { return [...mapa.entries()].map(([l, gs]) => {
      const cerrada = estado.ligasCerradas.has(l);
      const dia = gs.filter((g) => g[0].elige).length;
      return '<section class="liga-bloque"><button class="liga-cab" data-liga="' + esc(l) + '"><span>' + esc(l) + '</span>' +
        '<small>' + (dia ? '💎 ' + dia + ' · ' : '') + gs.length + ' ' + (gs.length === 1 ? 'partido' : 'partidos') + ' ' + (cerrada ? '▸' : '▾') + '</small></button>' +
        (cerrada ? '' : gs.map(seguro(filaPartido)).join('')) + '</section>';
    }).join(''); }
    const enVivo = Object.values(estado.vivo).filter((v) => v.fase === 'in').length;
    $('aviso').textContent = grupos.length ? '' :
      estado.vista === 'mios' ? (window.SPX && SPX.yo.user ? 'Todavía no sigues ningún pick: abre un partido y pulsa «☆ Seguir».' : 'Entra con tu correo para guardar tus picks.')
        : estado.vista === 'vivo' ? 'Ahorita no hay partidos en vivo con picks.'
          : estado.errorPicks ? 'No se pudieron consultar los pronósticos. Reintenta en un momento.'
            : !estado.picks.length ? 'La fuente respondió, pero no devolvió pronósticos. Revisa el precálculo o la publicación de datos.'
              : 'Sin partidos con estos filtros.';
    if (estado.respaldoPicks) $('aviso').textContent = '⚠️ La base no respondió; mostramos el archivo de respaldo. Los datos podrían estar desactualizados.';
    const b = $('nav-vivo-n'); if (b) { b.textContent = enVivo || ''; b.hidden = !enVivo; }
    // v384 — «falta béisbol»: si hay partidos de un deporte y ninguno pasó, se dice
    const sp = (estado.meta && estado.meta.sin_pick) || {};
    const conPick = new Set(lista.map((p) => p.deporte));
    const avisos = Object.entries(sp).filter(([dep, n]) => n > 0 && !conPick.has(dep) && estado.vista === 'picks' && estado.dia === 'hoy'
      && (estado.deportes.size === 0 || estado.deportes.has(dep)));
    if (avisos.length) $('tarjetas').insertAdjacentHTML('beforeend', avisos.map(([dep, n]) =>
      '<div class="sin-pick">' + ({ MLB: '⚾', KBO: '⚾', NBA: '🏀', NFL: '🏈', NHL: '🏒', Tenis: '🎾' }[dep] || '•') + ' <b>' + esc(dep) + '</b>: ' + n +
      (n === 1 ? ' partido hoy' : ' partidos hoy') + ', pero ninguno llegó a nuestro mínimo de probabilidad. Preferimos no darte un pick flojo.</div>').join(''));
  }

  window.SP = { nivel, pintar, estado };

  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-vista-ir],[data-dia],[data-dep],[data-niv],[data-fase],[data-abrir],[data-liga],[data-ficha],[data-ver-fin]');
    if (!t) return;
    if (t.hasAttribute('data-ver-fin')) { estado.verFinales = !estado.verFinales; pintar(); return; }
    if (t.dataset.vistaIr) {
      estado.vista = t.dataset.vistaIr; window.scrollTo({ top: 0 }); pintar();
      const foco = t.dataset.foco && document.getElementById(t.dataset.foco);   // v417 — directo al plan VIP
      if (foco) setTimeout(() => { foco.scrollIntoView({ behavior: 'smooth', block: 'start' }); foco.classList.add('resalta'); setTimeout(() => foco.classList.remove('resalta'), 2000); }, 80);
      return;
    }
    if (t.dataset.dia) { estado.dia = t.dataset.dia; document.querySelectorAll('#pestanas button').forEach((x) => x.classList.toggle('activa', x === t)); pintar(); return; }
    // tocar uno lo prende o lo apaga; «Todos» limpia
    const alterna = (s, v) => { if (v === 'Todos') s.clear(); else if (s.has(v)) s.delete(v); else s.add(v); };
    if (t.dataset.dep) { alterna(estado.deportes, t.dataset.dep); pintar(); return; }
    if (t.dataset.niv) { alterna(estado.niveles, t.dataset.niv); pintar(); return; }
    if (t.dataset.fase) { estado.fase = t.dataset.fase; pintar(); return; }
    if (t.dataset.ficha) { ficha(t.dataset.ficha); return; }
    if (t.dataset.liga) { const l = t.dataset.liga; estado.ligasCerradas.has(l) ? estado.ligasCerradas.delete(l) : estado.ligasCerradas.add(l); pintar(); return; }
    if (t.dataset.abrir) {
      const k = t.dataset.abrir;
      if (t.dataset.ir) { estado.abiertos.add(k); estado.fase = 'todos'; estado.niveles = new Set(); }
      else {
        if (estado.abiertos.has(k)) estado.abiertos.delete(k); else estado.abiertos.add(k);
        const fila = t.closest('.partido-fila'), g = estado.grupos && estado.grupos.get(k);
        if (fila && g) { try { fila.outerHTML = filaPartido(g); setTimeout(vivo365, 50); return; } catch (e) { /* abajo, repinta todo */ } }
      }
      pintar();
      const el = [...document.querySelectorAll('.pf')].find((x) => x.dataset.abrir === k);
      if (el && t.dataset.ir) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  $('busca').addEventListener('input', (e) => { estado.busca = e.target.value; pintar(); });
  $('liga').addEventListener('change', (e) => { estado.liga = e.target.value; pintar(); });
  $('ficha').addEventListener('click', (e) => { if (e.target.id === 'ficha' || e.target.closest('[data-cerrar]')) { $('ficha').hidden = true; fichaId = null; } });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { $('ficha').hidden = true; fichaId = null; } });
  setInterval(() => { $('reloj').textContent = new Intl.DateTimeFormat('es-MX', { timeZone: ZONA, hour: '2-digit', minute: '2-digit' }).format(new Date()) + ' CDMX'; }, 1000);
  cargar();
  setInterval(cargar, 3 * 60 * 1000);   // picks nuevos y verdes/rojas oficiales
  setInterval(vivo, 30 * 1000);         // marcador y estadísticas
  setInterval(vivoFs, 45 * 1000);       // v424 — y lo que ESPN no cubre
  setInterval(vivo365, 30 * 1000);      // v429 — la alineación y los tiros de las canchas a la vista
  setTimeout(vivoFs, 4000);
})();
