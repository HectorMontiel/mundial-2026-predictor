// v377-v378 — El sitio sólo LEE: los picks de Supabase (o de datos/hoy.json)
// y, EN VIVO, el marcador y las estadísticas directo de ESPN (permite leerlo
// desde la página), cada 30 s, sólo de los partidos que se están jugando.
(function () {
  const C = window.CONFIG || {};
  const ZONA = 'America/Mexico_City';
  const ESPN = 'https://site.api.espn.com/apis/site/v2/sports/';
  const $ = (id) => document.getElementById(id);
  const estado = { dia: 'hoy', deporte: 'Todos', nivel: 'Todos', soloElige: false, orden: 'hora', picks: [], vivo: {} };

  const diaCdmx = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: ZONA }).format(d);
  const aFecha = (s) => s ? new Date(String(s).replace(' ', 'T') + (/[zZ+]/.test(String(s).slice(10)) ? '' : 'Z')) : null;
  const horaCdmx = (d) => d ? new Intl.DateTimeFormat('es-MX', { timeZone: ZONA, weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(d) : '';
  const pct = (x) => x == null ? '—' : Math.round(100 * x) + ' %';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const lados = (p) => { const t = String(p.partido || ''); const i = t.indexOf(' vs '); return i < 0 ? [t, ''] : [t.slice(0, i), t.slice(i + 4)]; };

  function diaDe(p) { const d = aFecha(p.inicio); return d ? diaCdmx(d) : String(p.fecha || ''); }
  function diaPestana(n) { const d = new Date(); d.setUTCDate(d.getUTCDate() + n); return diaCdmx(d); }
  const OFFS = { ayer: -1, hoy: 0, manana: 1, pasado: 2 };

  // Niveles (como los «stakes» de BetFlipAi), pero con lo MEDIDO de verdad
  function nivel(p) {
    if (p.elige) return { n: 'Diamante', c: 'diamante', i: '💎' };
    if ((p.prob || 0) >= 0.85) return { n: 'Platino', c: 'platino', i: '🔷' };
    if ((p.prob || 0) >= 0.80) return { n: 'Oro', c: 'oro', i: '🥇' };
    return { n: 'Plata', c: 'plata', i: '🥈' };
  }

  async function cargar() {
    try {
      if (C.SUPABASE_URL && C.SUPABASE_ANON_KEY) {
        const desde = diaPestana(-2);
        const r = await fetch(C.SUPABASE_URL.replace(/\/$/, '') + '/rest/v1/picks?select=*&fecha=gte.' + desde + '&order=inicio.asc&limit=5000',
          { headers: { apikey: C.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + C.SUPABASE_ANON_KEY } });
        if (!r.ok) throw new Error('base de datos ' + r.status);
        estado.picks = await r.json();
        if (!estado.picks.length) throw new Error('la base aún está vacía');
        $('actualizado').textContent = 'Datos de la base · ' + horaCdmx(new Date());
      } else { throw new Error('sin base'); }
    } catch (e) {
      try {
        const r = await fetch('datos/hoy.json?t=' + Date.now());
        const d = await r.json();
        estado.picks = d.picks || [];
        $('actualizado').textContent = 'Actualizado: ' + horaCdmx(new Date(d.generado));
      } catch (e2) {
        $('aviso').textContent = 'No se pudieron cargar los pronósticos. Reintenta en un momento.';
        estado.picks = [];
      }
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
    return {
      fase: st.state || 'pre', terminado: !!st.completed, detalle: ({ FT: 'Final', HT: 'Medio tiempo', AET: 'Final (prórroga)', 'FT-Pens': 'Final (penales)', Final: 'Final' })[st.shortDetail] || st.shortDetail || st.detail || '',
      reloj: (comp.status || {}).displayClock || '', g: [Number(nos1.score || 0), Number(nos2.score || 0)],
      stats, eventos, nombres: [((nos1.team || {}).displayName) || '', ((nos2.team || {}).displayName) || ''],
      colores: coloresEquipos(nos1.team || {}, nos2.team || {}),
    };
  }

  async function vivo() {
    const ahora = Date.now();
    const ids = {};
    for (const p of estado.picks) {
      const ini = aFecha(p.inicio);
      if (!p.espn || !ini) continue;
      const desde = ini.getTime() - 10 * 60e3, hasta = ini.getTime() + 4 * 3600e3;
      const yaFin = (estado.vivo[p.espn] || {}).terminado;
      if (ahora >= desde && ahora <= hasta && !yaFin) ids[p.espn] = p;
    }
    const lista = Object.entries(ids).slice(0, 40);
    await Promise.all(lista.map(async ([k, p]) => {
      const [ruta, id] = k.split(':');
      try {
        const r = await fetch(ESPN + ruta + '/summary?event=' + id);
        if (r.ok) estado.vivo[k] = leerResumen(await r.json(), p);
      } catch (e) { /* sin red: se reintenta en 30 s */ }
    }));
    if (lista.length) { pintar(); refrescarFicha(); }
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
  function cajaMarcador(titulo, lista) {
    const t = cuenta(lista), e = cuenta(lista.filter((p) => p.elige));
    const pend = lista.filter((p) => p.estado === 'pendiente' || p.estado === 'vivo').length;
    return '<div class="caja"><div class="tit">' + titulo + '</div>' +
      '<div class="num">✅ ' + t.v + ' &nbsp;❌ ' + t.r + ' <span class="pct">' + pct(t.pct) + '</span></div>' +
      '<div class="barra"><i style="width:' + (t.pct == null ? 0 : 100 * t.pct) + '%"></i></div>' +
      '<div class="sub">💎 Diamante: ✅ ' + e.v + ' ❌ ' + e.r + (e.pct == null ? '' : ' · ' + pct(e.pct)) + ' · por jugar ' + pend + '</div>' +
      '<div class="sub">Apostando $100 a cada una: <b class="' + (t.din >= 0 ? 'txt-verde' : 'txt-rojo') + '">' + (t.din >= 0 ? '+' : '−') + '$' + Math.abs(Math.round(100 * t.din)) + '</b></div></div>';
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
  function miniStats(v) {
    if (!v || !v.stats) return '';
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
  function estadoPick(p) {
    if (p.estado === 'verde') return '<span class="et verde">✅ Verde</span>';
    if (p.estado === 'roja') return '<span class="et roja">❌ Roja</span>';
    if (p.estado === 'nula') return '<span class="et">Nula</span>';
    return '';
  }
  function filaPick(p, v, varias) {
    const pr = progreso(p, v);
    const nv = nivel(p);
    return '<div class="pick-fila ' + (p.estado === 'verde' ? 'verde' : p.estado === 'roja' ? 'roja' : '') + '">' +
      ((varias || p.estado === 'verde' || p.estado === 'roja') ? '<div class="fila"><span class="et nivel ' + nv.c + '">' + nv.i + ' ' + nv.n + '</span>' + estadoPick(p) + '</div>' : '') +
      '<div class="apuesta">' + (window.SPX ? SPX.apuesta(p) : esc(p.apuesta)) + '</div>' +
      (pr ? '<div class="progreso ' + pr.e + '">' + esc(pr.t) + '</div>' : '') +
      '<div class="datos"><div class="dato"><small>Cuota</small><b>' + (p.cuota ? Number(p.cuota).toFixed(2) : '—') + '</b></div>' +
      '<div class="dato"><small>Acierta (medido)</small><b>' + pct(p.prob) + '</b></div>' +
      '<div class="dato"><small>Cuota justa</small><b>' + (p.prob ? (1 / p.prob).toFixed(2) : '—') + '</b></div></div>' +
      (window.SPX ? SPX.extra(p) : '') + '</div>';
  }
  function tarjeta(ps) {
    const p = ps[0];
    const v = (ps.find((x) => x.espn) || {}).espn ? estado.vivo[ps.find((x) => x.espn).espn] : null;
    const nv = nivel(p);
    const [L, V] = lados(p);
    const marc = v && v.fase !== 'pre' ? v.g[0] + ' - ' + v.g[1] : (p.marcador || '');
    const todas = ps.every((x) => x.estado === 'verde' || x.estado === 'roja' || x.estado === 'nula');
    const clase = ['tarjeta', nv.c, todas && ps.every((x) => x.estado !== 'roja') ? 'verde' : '', todas && ps.every((x) => x.estado === 'roja') ? 'roja' : ''].join(' ');
    const cab = todas && !(v && v.fase === 'in') ? '<span class="et">Terminado</span>' : etiquetaEstado(dict(p, { estado: 'pendiente' }), v);
    return '<article class="' + clase + '" data-id="' + esc(p.id) + '">' +
      '<div class="fila"><div class="etiquetas"><span class="et nivel ' + nv.c + '">' + nv.i + ' ' + nv.n + '</span>' +
      '<span class="et">' + esc(p.deporte || '') + '</span>' + (ps.length > 1 ? '<span class="et">' + ps.length + ' apuestas</span>' : '') + '</div>' + cab + '</div>' +
      '<div class="equipos"><div class="eq">' + escudo(p.logo_h, L) + '<span>' + esc(L) + '</span></div>' +
      '<div class="marc">' + (marc ? esc(marc) : 'vs') + '</div>' +
      '<div class="eq der"><span>' + esc(V) + '</span>' + escudo(p.logo_a, V) + '</div></div>' +
      '<div class="liga">' + esc(p.liga || '') + ' · ' + esc(horaCdmx(aFecha(p.inicio))) + '</div>' +
      miniStats(v) +
      ps.map((x) => filaPick(x, v, ps.length > 1)).join('') +
      (ps.some((x) => x.espn) ? '<button class="ver" data-ficha="' + esc((ps.find((x) => x.espn) || p).id) + '">Ver partido →</button>' : '') +
      '</article>';
  }
  const dict = (a, b) => Object.assign({}, a, b);

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

  // ---------- SIMULADOR DE BANCA ----------
  function simular() {
    const banca0 = Math.max(1, Number($('sim-banca').value) || 1000);
    const pctA = Math.min(50, Math.max(0.5, Number($('sim-pct').value) || 5)) / 100;
    const solo = $('sim-nivel').value;
    const jug = estado.picks.filter((p) => (p.estado === 'verde' || p.estado === 'roja') && p.cuota &&
      (solo === 'Todos' || nivel(p).n === solo)).sort((a, b) => String(a.inicio).localeCompare(String(b.inicio)));
    let b = banca0, max = banca0, caida = 0;
    const serie = [b];
    for (const p of jug) {
      const ap = b * pctA;
      b += p.estado === 'verde' ? ap * (p.cuota - 1) : -ap;
      max = Math.max(max, b); caida = Math.max(caida, 1 - b / max); serie.push(b);
    }
    const w = 300, hgt = 70, mn = Math.min(...serie), mx = Math.max(...serie) || 1;
    const pts = serie.map((y, i) => (i * w / Math.max(1, serie.length - 1)).toFixed(1) + ',' + (hgt - (y - mn) / ((mx - mn) || 1) * hgt).toFixed(1)).join(' ');
    $('sim-res').innerHTML = jug.length
      ? '<div class="num ' + (b >= banca0 ? 'txt-verde' : 'txt-rojo') + '">$' + Math.round(b).toLocaleString('es-MX') + '</div>' +
        '<div class="sub">' + jug.length + ' apuestas jugadas · ' + (b >= banca0 ? '+' : '') + (100 * (b / banca0 - 1)).toFixed(1) + ' % · peor caída ' + (100 * caida).toFixed(1) + ' %</div>' +
        '<svg viewBox="0 0 ' + w + ' ' + hgt + '" class="curva"><polyline fill="none" stroke="currentColor" stroke-width="2" points="' + pts + '"/></svg>'
      : '<div class="sub">Todavía no hay apuestas terminadas con estos filtros.</div>';
  }

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

  function vivoDe(ps) { const x = ps.find((q) => q.espn); return x ? estado.vivo[x.espn] : null; }
  function faseDe(ps) {
    const v = vivoDe(ps);
    const fin = ps.every((x) => x.estado === 'verde' || x.estado === 'roja' || x.estado === 'nula');
    if (v && v.fase === 'in') return 'vivo';
    if (fin || (v && v.terminado)) return 'terminado';
    const ini = aFecha(ps[0].inicio);
    // empezado sin dato en vivo: en juego las primeras 3 h y media; después, terminado (liquidando)
    if (ini && ini <= new Date()) return Date.now() - ini > 3.5 * 3600e3 ? 'terminado' : 'vivo';
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
  function filaPartido(ps) {
    const p = ps[0], nv = nivel(p), [L, V] = lados(p), v = vivoDe(ps);
    const k = clavePartido(p), abierto = estado.abiertos.has(k);
    const marc = v && v.fase !== 'pre' ? v.g : (p.marcador ? String(p.marcador).split('-').map((x) => x.trim()) : null);
    const ap = window.SPX ? SPX.apuesta(p) : esc(p.apuesta);
    return '<div class="partido-fila ' + nv.c + (abierto ? ' abierto' : '') + '">' +
      '<button class="pf" data-abrir="' + esc(k) + '" aria-expanded="' + abierto + '">' +
      relojFila(ps) +
      '<span class="pf-eqs"><span class="pf-eq">' + escudo(p.logo_h, L) + '<b>' + esc(L) + '</b>' + (marc ? '<em>' + esc(marc[0]) + '</em>' : '') + '</span>' +
      '<span class="pf-eq">' + escudo(p.logo_a, V) + '<b>' + esc(V) + '</b>' + (marc ? '<em>' + esc(marc[1]) + '</em>' : '') + '</span></span>' +
      '<span class="pf-pick"><span class="pf-niv">' + nv.i + '</span><span class="pf-ap">' + ap + '</span>' +
      '<span class="pf-cu">' + (p.cuota ? Number(p.cuota).toFixed(2) : '') + '</span>' +
      (ps.length > 1 ? '<span class="pf-mas">+' + (ps.length - 1) + '</span>' : '') + resumenPicks(ps) + '</span>' +
      '</button>' + (abierto ? '<div class="pf-detalle">' + tarjeta(ps) + '</div>' : '') + '</div>';
  }
  function destacado(ps) {
    const p = ps[0], [L, V] = lados(p), v = vivoDe(ps);
    const marc = v && v.fase !== 'pre' ? v.g[0] + ' - ' + v.g[1] : '';
    return '<button class="dest" data-abrir="' + esc(clavePartido(p)) + '" data-ir="1">' +
      '<div class="fila"><span class="et nivel diamante">💎 Diamante</span>' + relojFila(ps) + '</div>' +
      '<div class="dest-eqs">' + escudo(p.logo_h, L) + '<span>' + esc(marc || 'vs') + '</span>' + escudo(p.logo_a, V) + '</div>' +
      '<div class="dest-nom">' + esc(L) + ' – ' + esc(V) + '</div>' +
      '<div class="dest-ap">' + (window.SPX ? SPX.apuesta(p) : esc(p.apuesta)) + '</div>' +
      '<div class="dest-pie"><b>' + (p.cuota ? Number(p.cuota).toFixed(2) : '') + '</b><span>acierta ' + pct(p.prob) + '</span></div></button>';
  }
  function tiraMarcador() {
    const hoy = diaPestana(0), l = estado.picks.filter((p) => diaDe(p) === hoy), t = cuenta(l), e = cuenta(l.filter((p) => p.elige));
    return '<button class="tira" data-vista-ir="historial">Hoy <b>✅ ' + t.v + ' ❌ ' + t.r + '</b> ' + pct(t.pct) +
      ' · 💎 <b>' + e.v + '-' + e.r + '</b>' + (e.pct == null ? '' : ' ' + pct(e.pct)) + ' <span>Ver historial ›</span></button>';
  }

  function listaBase() {
    if (estado.vista === 'mios') return window.SPX ? SPX.filtrarMios(estado.picks) : [];
    if (estado.vista === 'vivo') return estado.picks.filter((p) => { const d = aFecha(p.inicio); return d && d <= new Date() && Date.now() - d < 5 * 3600e3; });
    const dia = diaPestana(OFFS[estado.dia] || 0);
    return estado.picks.filter((p) => diaDe(p) === dia);
  }

  function pintar() {
    document.querySelectorAll('[data-vista]').forEach((s) => { s.hidden = !String(s.dataset.vista).split(' ').includes(estado.vista); });
    document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('activa', b.dataset.vistaIr === estado.vista));
    const hoy = diaPestana(0), ayer = diaPestana(-1);
    $('marcadores').innerHTML = cajaMarcador('Hoy', estado.picks.filter((p) => diaDe(p) === hoy)) +
      cajaMarcador('Ayer', estado.picks.filter((p) => diaDe(p) === ayer));
    $('tira').innerHTML = tiraMarcador();
    if (!['picks', 'vivo', 'mios'].includes(estado.vista)) { simular(); return; }

    let lista = listaBase();
    const deps = ['Todos'].concat([...new Set(lista.map((p) => p.deporte).filter(Boolean))].sort());
    if (!deps.includes(estado.deporte)) estado.deporte = 'Todos';
    const ICO = { 'Fútbol': '⚽', 'Tenis': '🎾', 'NBA': '🏀', 'NFL': '🏈', 'NHL': '🏒', 'MLB': '⚾' };
    $('deportes').innerHTML = deps.map((d) => '<button class="chip' + (d === estado.deporte ? ' activa' : '') + '" data-dep="' + esc(d) + '">' + (ICO[d] ? ICO[d] + ' ' : '') + esc(d) + '</button>').join('');
    $('niveles').innerHTML = ['Todos', 'Diamante', 'Platino', 'Oro', 'Plata'].map((n) => '<button class="chip' + (n === estado.nivel ? ' activa' : '') + '" data-niv="' + n + '">' + ({ Diamante: '💎 ', Platino: '🔷 ', Oro: '🥇 ', Plata: '🥈 ' }[n] || '') + n + '</button>').join('');
    if (estado.deporte !== 'Todos') lista = lista.filter((p) => p.deporte === estado.deporte);
    if (estado.nivel !== 'Todos') lista = lista.filter((p) => nivel(p).n === estado.nivel);
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
    $('fases').hidden = estado.vista === 'vivo';
    if (estado.fase !== 'todos' && estado.vista !== 'vivo') grupos = grupos.filter((g) => faseDe(g) === estado.fase);

    // 💎 Destacados: los Diamante que aún no terminan
    const dest = estado.vista === 'picks' ? agrupar(listaBase()).filter((g) => g[0].elige && faseDe(g) !== 'terminado')
      .sort((a, b) => String(a[0].inicio).localeCompare(String(b[0].inicio))).slice(0, 12) : [];
    $('destacados').hidden = !dest.length;
    $('destacados-lista').innerHTML = dest.map(destacado).join('');

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
    const ligas = porLiga(grupos);
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
        (cerrada ? '' : gs.map(filaPartido).join('')) + '</section>';
    }).join(''); }
    const enVivo = Object.values(estado.vivo).filter((v) => v.fase === 'in').length;
    $('aviso').textContent = grupos.length ? '' :
      estado.vista === 'mios' ? (window.SPX && SPX.yo.user ? 'Todavía no sigues ningún pick: abre un partido y pulsa «☆ Seguir».' : 'Entra con tu correo para guardar tus picks.')
        : estado.vista === 'vivo' ? 'Ahorita no hay partidos en vivo con picks.' : 'Sin partidos con estos filtros.';
    const b = $('nav-vivo-n'); if (b) { b.textContent = enVivo || ''; b.hidden = !enVivo; }
    simular();
  }

  window.SP = { nivel, pintar, estado };

  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-vista-ir],[data-dia],[data-dep],[data-niv],[data-fase],[data-abrir],[data-liga],[data-ficha],[data-ver-fin]');
    if (!t) return;
    if (t.hasAttribute('data-ver-fin')) { estado.verFinales = !estado.verFinales; pintar(); return; }
    if (t.dataset.vistaIr) { estado.vista = t.dataset.vistaIr; window.scrollTo({ top: 0 }); pintar(); return; }
    if (t.dataset.dia) { estado.dia = t.dataset.dia; document.querySelectorAll('#pestanas button').forEach((x) => x.classList.toggle('activa', x === t)); pintar(); return; }
    if (t.dataset.dep) { estado.deporte = t.dataset.dep; pintar(); return; }
    if (t.dataset.niv) { estado.nivel = t.dataset.niv; pintar(); return; }
    if (t.dataset.fase) { estado.fase = t.dataset.fase; pintar(); return; }
    if (t.dataset.ficha) { ficha(t.dataset.ficha); return; }
    if (t.dataset.liga) { const l = t.dataset.liga; estado.ligasCerradas.has(l) ? estado.ligasCerradas.delete(l) : estado.ligasCerradas.add(l); pintar(); return; }
    if (t.dataset.abrir) {
      const k = t.dataset.abrir;
      if (t.dataset.ir) { estado.abiertos.add(k); estado.fase = 'todos'; estado.nivel = 'Todos'; }
      else if (estado.abiertos.has(k)) estado.abiertos.delete(k); else estado.abiertos.add(k);
      pintar();
      const el = [...document.querySelectorAll('.pf')].find((x) => x.dataset.abrir === k);
      if (el && t.dataset.ir) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  $('busca').addEventListener('input', (e) => { estado.busca = e.target.value; pintar(); });
  $('liga').addEventListener('change', (e) => { estado.liga = e.target.value; pintar(); });
  $('ficha').addEventListener('click', (e) => { if (e.target.id === 'ficha' || e.target.closest('[data-cerrar]')) { $('ficha').hidden = true; fichaId = null; } });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { $('ficha').hidden = true; fichaId = null; } });
  ['sim-banca', 'sim-pct', 'sim-nivel'].forEach((i) => $(i).addEventListener('input', simular));
  $('nombre').textContent = C.NOMBRE || 'SharPicks';
  setInterval(() => { $('reloj').textContent = new Intl.DateTimeFormat('es-MX', { timeZone: ZONA, hour: '2-digit', minute: '2-digit' }).format(new Date()) + ' CDMX'; }, 1000);
  cargar();
  setInterval(cargar, 3 * 60 * 1000);   // picks nuevos y verdes/rojas oficiales
  setInterval(vivo, 30 * 1000);         // marcador y estadísticas
})();
