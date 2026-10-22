// v379 — SharPicks: la CUENTA del usuario (Supabase Auth), «Mis picks»,
// monedas, desbloquear con «No Win, No Pay» y el historial público.
// Lo que manda (saldo, quién ve un pick premium, la devolución si falla) lo
// decide la BASE (`negocio.sql`), no esta página: aquí sólo se pide y se pinta.
(function () {
  const C = window.CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // v426 — ¿se llegó desde el enlace de «restablecer contraseña»?
  const DESDE_RECUPERACION = /type=recovery/.test(location.hash + location.search);
  let sb = null;
  try {
    sb = (window.supabase && C.SUPABASE_URL && C.SUPABASE_ANON_KEY)
      ? window.supabase.createClient(C.SUPABASE_URL, C.SUPABASE_ANON_KEY, {
          // v390 — el usuario: «tras un rato, pico en mi nombre y no se abre». El
          // candado del navegador que usa Supabase para la sesión se queda trabado
          // en el celular (al volver a la app) y TODA consulta espera para siempre.
          // Sin candado: una sola pestaña de SharPicks no lo necesita.
          auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, lock: async (_n, _t, fn) => await fn() },
        }) : null;
  } catch (e) { sb = null; }          // un navegador que no deja guardar la sesión no rompe la página
  const yo = { user: null, perfil: null, seguidos: new Set(), desbloqueados: {}, conteo: {}, precios: {} };
  // v412 — «cuando compré se me cerró sesión»: NO se cerraba. Al volver de
  // Stripe, «Mi cuenta» se abría a los 1,5 s y, si el celular aún no había
  // leído la sesión guardada, enseñaba «Entrar» (y lo mismo la cabecera al
  // abrir la app). Ahora la sesión guardada en ESTE dispositivo se lee al
  // instante, y nada pide entrar hasta que la primera carga termina.
  function sesionGuardada() {
    try {
      const ref = String(C.SUPABASE_URL || '').split('//')[1].split('.')[0];
      const s = JSON.parse(localStorage.getItem('sb-' + ref + '-auth-token') || 'null');
      return (s && s.user && s.refresh_token) ? s.user : null;
    } catch (e) { return null; }
  }
  if (sb) yo.user = sesionGuardada();
  // v414 — «al volver tras un rato sale mi correo en vez de mi usuario y no
  // salen mis derechos hasta unos segundos después»: el perfil llegaba de la
  // red después de la sesión. Se guarda una copia en el dispositivo SÓLO para
  // pintar al instante (lo que se puede hacer lo decide siempre el servidor).
  const PERFIL_GUARDADO = 'sharpicks-perfil';
  function perfilGuardado(id) {
    try { const p = JSON.parse(localStorage.getItem(PERFIL_GUARDADO) || 'null'); return p && p.id === id ? p : null; } catch (e) { return null; }
  }
  function guardarPerfil(p) {
    try { if (p && p.id) localStorage.setItem(PERFIL_GUARDADO, JSON.stringify(p)); else localStorage.removeItem(PERFIL_GUARDADO); } catch (e) { /* sin almacenamiento */ }
  }
  if (yo.user) yo.perfil = perfilGuardado(yo.user.id);
  let listo = null;                       // la primera carga de la sesión
  try { navigator.storage && navigator.storage.persist && navigator.storage.persist(); } catch (e) { /* opcional */ }
  // v455 — los íconos de app.js (Lucide/Tabler) en vez de emojis
  const ico = (n, x) => (window.SP && window.SP.ico ? window.SP.ico(n, x) : '');
  const OK = () => ico('circle-check'), MAL = () => ico('circle-x');
  // v457 — AVISOS PROPIOS en vez del alert/confirm del navegador (el usuario: «que sean
  // del estilo de la app, sin emojis, con íconos»). Devuelven una promesa.
  function ventanaApp({ tipo, titulo, texto, si, no, peligro }) {
    return new Promise((listo) => {
      const ICONO = { ok: ['circle-check', 'ok'], aviso: ['triangle-alert', 'aviso'], pregunta: ['circle-help', 'acento'] }[tipo] || ['circle-help', 'acento'];
      const caja = document.createElement('div');
      caja.className = 'modal-app';
      caja.setAttribute('role', 'dialog');
      caja.setAttribute('aria-modal', 'true');
      caja.innerHTML = '<div class="modal-caja"><div class="modal-ico ' + ICONO[1] + '">' + ico(ICONO[0]) + '</div>' +
        (titulo ? '<h3>' + esc(titulo) + '</h3>' : '') + (texto ? '<p>' + esc(texto) + '</p>' : '') +
        '<div class="modal-botones">' + (no ? '<button class="modal-no">' + esc(no) + '</button>' : '') +
        '<button class="modal-si' + (peligro ? ' peligro' : '') + '">' + esc(si || 'Entendido') + '</button></div></div>';
      const cerrar = (v) => { caja.classList.add('sale'); setTimeout(() => caja.remove(), 160); document.removeEventListener('keydown', tecla); listo(v); };
      const tecla = (e) => { if (e.key === 'Escape') cerrar(false); };
      caja.addEventListener('click', (e) => { if (e.target === caja) cerrar(false); });
      caja.querySelector('.modal-si').addEventListener('click', () => cerrar(true));
      const nb = caja.querySelector('.modal-no'); if (nb) nb.addEventListener('click', () => cerrar(false));
      document.addEventListener('keydown', tecla);
      document.body.appendChild(caja);
      caja.querySelector('.modal-si').focus();
    });
  }
  const ESQ = '<div class="esq-lineas" aria-hidden="true"><i class="esq w90"></i><i class="esq w70"></i><i class="esq w50"></i></div>';   // v458 — la silueta mientras carga
  const avisoApp = (texto, tipo, titulo) => ventanaApp({ tipo: tipo || 'aviso', titulo, texto });
  const confirmarApp = (titulo, texto, si, no) => ventanaApp({ tipo: 'pregunta', titulo, texto, si, no: no || 'No', peligro: true });
  window.SPX = { yo, sb, extra, apuesta, filtrarMios, refrescar, extraComb, esVip: () => esVip(), intereses: () => intereses(), votoIA: (id) => votoIA(id) };
  window.SPX.avisoApp = avisoApp; window.SPX.confirmarApp = confirmarApp;   // v457

  // ---------- precios (de la base; 0 = gratis en el lanzamiento) ----------
  // v389 — el precio de un pick premium depende de su CUOTA (tabla `precios_cuota`);
  // 🥇 y 🥈 son gratis; el administrador no paga. Lo que cobra de verdad lo
  // decide la base (`precio_pick`); esto sólo lo enseña.
  function precio(p) {
    if (yo.perfil && yo.perfil.admin) return 0;
    const n = window.SP.nivel(p).n;
    if (!p._forzar && !['Diamante', 'Platino', 'Plata', 'Cuota alta'].includes(n)) return 0;   // v420: 🥈 Plata a monedas
    const c = Number(p.cuota || 1), b = (yo.bandas || []).find((x) => c >= Number(x.desde) && c < Number(x.hasta));
    return b ? Number(b.monedas) : 10;
  }

  function apuesta(p) {
    if (!p.premium) return esc(p.apuesta);
    const real = yo.desbloqueados[p.id];
    return real ? '🔓 ' + esc(real) : '<span class="bloqueado">🔒 Pick ' + esc(window.SP.nivel(p).n) + '</span>';
  }

  function extra(p) {
    let h = '<div class="acciones">';
    if (p.premium && !yo.desbloqueados[p.id] && !esVip()) {             // v445: al VIP (y al admin) nunca se le ofrece desbloquear
      const pr = precio(p);
      // v381 — lanzamiento: con cuenta (gratis) se ven todos; sin cuenta, candado
      if (!yo.user) h += '<button class="desbloquear" data-entrar>🔓 Entra gratis y desbloquéalo</button>';
      else h += '<button class="desbloquear" data-desbloquear="' + esc(p.id) + '">' +
        (pr ? 'Desbloquear por ' + pr + ' 🪙' : 'Desbloquear gratis') + '</button>' +
        '<small class="nwnp">Si sale roja, se te devuelve</small>';
    }
    // v428 — «➕ Combinada»: sólo lo que el usuario puede ver, pendiente y sin empezar
    const ini = new Date(String(p.inicio || '').replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(String(p.inicio)) ? '' : 'Z'));
    const visible = !p.premium || yo.desbloqueados[p.id] || esVip();
    if (yo.user && visible && p.estado === 'pendiente' && Number(p.cuota) > 1 && ini > new Date() && !p.solo_analisis && p.tipo !== 'combinada') {
      const en = boleto().includes(p.id);
      h += '<button class="seguir' + (en ? ' si' : '') + '" data-a-comb="' + esc(p.id) + '">' + (en ? '✓ En tu combinada' : '➕ Combinada') + '</button>';
    }
    const sigo = yo.seguidos.has(p.id);
    h += '<button class="seguir' + (sigo ? ' si' : '') + '" data-seguir="' + esc(p.id) + '">' + (sigo ? '★ Siguiendo' : '☆ Seguir') + '</button>';
    const n = yo.conteo[p.id];
    const otros = (n || 0) - (sigo ? 1 : 0);            // v421 — tú no cuentas como «más gente»
    if (otros > 0) h += '<span class="siguen" title="Otras personas siguen este pick">👥 ' + otros + '</span>';
    return h + '</div>';
  }

  // v397 — DESBLOQUEAR UNA COMBINADA ENTERA: el precio de su cuota total (la
  // misma tabla), menos si ya tenías alguna pata; si sale roja, se devuelve
  function extraComb(c) {
    const m = (window.SP && window.SP.estado.picks) || [];
    const premium = (c.patas || []).map((x) => m.find((p) => p.id === x.id)).filter((p) => p && p.premium);
    const faltan = premium.filter((p) => !yo.desbloqueados[p.id]);
    if (!faltan.length || esVip()) return '';
    const empezo = (c.patas || []).some((x) => new Date(String(x.inicio).replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(String(x.inicio)) ? '' : 'Z')) <= new Date());
    if (empezo) return '';
    if (!yo.user) return '<button class="desbloquear" data-entrar>🔓 Entra gratis y desbloquéala</button>';
    const cu = Number(c.cuota || 1), b = (yo.bandas || []).find((x) => cu >= Number(x.desde) && cu < Number(x.hasta));
    const total = b ? Number(b.monedas) : 10;
    const suelto = faltan.reduce((s, p) => s + precio(dict2(p, { _forzar: 1 })), 0);
    const pr = esAdmin() ? 0 : Math.min(total, suelto || total);
    return '<div class="acciones"><button class="desbloquear" data-desb-comb="' + esc(c.id) + '">' +
      (pr ? 'Desbloquear la combinada por ' + pr + ' 🪙' : 'Desbloquear gratis') + '</button>' +
      '<small class="nwnp">Si sale roja, se te devuelve</small></div>';
  }
  const dict2 = (a, b) => Object.assign({}, a, b);

  function filtrarMios(lista) { return lista.filter((p) => yo.seguidos.has(p.id)); }

  // v445 — el usuario (VIP y admin) veía «🔒 Pick Plata» y «Desbloquear gratis».
  // La base tiene 1023 textos premium y Supabase entrega 1000 por petición: los
  // más nuevos se quedaban fuera. Ahora se piden sólo los de los últimos 45 días
  // y por páginas; si algo falla, se queda lo que ya había (nunca se borra).
  async function textosPremium() {
    const out = {}, desde = new Date(Date.now() - 45 * 864e5).toISOString();
    const pagina = (i, conFecha) => (conFecha ? sb.from('picks_premium').select('id,apuesta,picks!inner(inicio)').gte('picks.inicio', desde)
      : sb.from('picks_premium').select('id,apuesta')).order('id').range(i * 1000, i * 1000 + 999);
    for (const conFecha of [true, false]) {
      let ok = true;
      for (let i = 0; i < 30; i++) {
        const { data, error } = await pagina(i, conFecha);
        if (error) { ok = false; break; }
        (data || []).forEach((x) => { out[x.id] = x.apuesta; });
        if (!data || data.length < 1000) break;
      }
      if (ok) return out;
    }
    return null;
  }

  // ---------- sesión ----------
  const aTiempo = (p, ms, porDefecto) => Promise.race([Promise.resolve(p).catch(() => porDefecto),
    new Promise((r) => setTimeout(() => r(porDefecto), ms || 5000))]);
  async function refrescar() {
    if (!sb) return;
    try { pintarCabecera(); } catch (e) { /* se repinta al final */ }   // v412: con la sesión guardada, sin esperar a la red
    try {
      const { data } = await aTiempo(sb.auth.getSession(), 5000, { data: { session: yo.user ? { user: yo.user } : null } });
      yo.user = data && data.session ? data.session.user : null;
    } catch (e) { /* se queda la sesión que había */ }
    if (yo.user && (!yo.perfil || yo.perfil.id !== yo.user.id)) yo.perfil = perfilGuardado(yo.user.id);
    try { pintarCabecera(); } catch (e) { /* se repinta al final */ }   // v412: «Entrar» no se queda en pantalla mientras carga
    const tareas = [
      sb.from('ajustes').select('clave,valor').then(({ data }) => { (data || []).forEach((x) => { yo.precios[x.clave] = x.valor; }); }),
      sb.from('precios_cuota').select('*').order('desde').then(({ data }) => { yo.bandas = data || []; }),
      sb.from('paquetes').select('*').order('orden').then(({ data }) => { yo.paquetes = data || []; }),
      sb.from('seguidores').select('pick,n').then(({ data }) => { yo.conteo = {}; (data || []).forEach((x) => { yo.conteo[x.pick] = x.n; }); }),
      // v417 — qué partidos tienen análisis de la IA (para el 🔒 de quien no es VIP)
      sb.from('ia_disponibles').select('partido').limit(3000).then(({ data, error }) => { if (!error) yo.iaHay = new Set((data || []).map((x) => x.partido)); }),
    ];
    if (yo.user) {
      tareas.push(sb.from('perfiles').select('*').eq('id', yo.user.id).maybeSingle().then(({ data, error }) => {
        if (error) return;                       // sin red: se queda el que había
        // v416 — vacío al volver a la app (la sesión se está renovando y la
        // consulta sale sin ella): se queda la copia; nunca se borra por esto
        if (!data) { if (!yo.perfil) yo.perfil = perfilGuardado(yo.user.id); return; }
        yo.perfil = data; guardarPerfil(data);
        try { pintarCabecera(); } catch (e) { /* al final se repinta */ }
      }));
      tareas.push(sb.from('seguidos').select('pick').then(({ data }) => { yo.seguidos = new Set((data || []).map((x) => x.pick)); }));
      tareas.push(sb.from('ia_analisis').select('*').gte('fecha', new Date(Date.now() - 2 * 864e5).toISOString().slice(0, 10)).limit(2000)
        .then(({ data }) => { yo.ia = {}; (data || []).forEach((x) => { yo.ia[x.partido] = x; }); }));
      tareas.push(sb.from('suscripciones').select('*').eq('usuario', yo.user.id).order('actualizado', { ascending: false }).limit(10)
        .then(({ data }) => { yo.subs = data || []; }));
      tareas.push(textosPremium().then((t) => { if (t) yo.desbloqueados = t; }));
      // v446 — sus 👍/👎 a la IA (si la tabla aún no existe, no pasa nada)
      tareas.push(sb.from('ia_calificaciones').select('analisis,voto,motivo').then(({ data, error }) => {
        if (!error) { yo.votosIA = {}; (data || []).forEach((x) => { yo.votosIA[x.analisis] = x; }); } }));
    } else { yo.perfil = null; yo.seguidos = new Set(); yo.desbloqueados = {}; yo.subs = []; }
    await Promise.all(tareas.map((t) => aTiempo(t, 6000, null)));
    if (yo.user) await aTiempo(cargarGustos(), 6000, null);
    try { avisoRenovacion(); } catch (e) { /* el aviso nunca tumba la página */ }
    try { pintarBoleto(); misCombinadas(); miHistorial(); } catch (e) { /* v428: nunca tumba la página */ }
    try { pintarCabecera(); } catch (e) {
      // pase lo que pase, la cabecera dice algo (y se reintenta en 20 s)
      const c = $('cuenta');
      if (c) c.innerHTML = yo.user ? '<button class="entrar" data-mi-cuenta>Mi cuenta ▾</button>' : '<button class="entrar" data-entrar>Entrar</button>';
      setTimeout(refrescar, 20000);
    }
    if (window.SP) window.SP.pintar();
  }

  // ---------- v383: CUENTA CON USUARIO, MI CUENTA, CÓDIGOS Y VIP ----------
  const FN = (C.SUPABASE_URL || '').replace(/\/$/, '') + '/functions/v1/';
  const esAdmin = () => !!(yo.perfil && yo.perfil.admin);
  const esVip = () => esAdmin() || !!(yo.perfil && yo.perfil.plan === 'pro' && (!yo.perfil.plan_hasta || new Date(yo.perfil.plan_hasta) > new Date()));
  const RE_USUARIO = /^[A-Za-z0-9_.]{3,20}$/;
  const fecha = (s) => s ? new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(s)) : '';

  // v395 — la suscripción que manda (la más reciente que siga viva) y su aviso
  const DIAS_AVISO = 7;
  function miSub() {
    return (yo.subs || []).find((s) => ['authorized', 'cancela_al_final', 'cancelled', 'pagado'].includes(s.estado) &&
      (s.estado !== 'cancelled' || esVip())) || null;
  }
  function renuevaPronto(s) {
    if (!s || !s.renueva || s.estado !== 'authorized' || !s.proximo_cobro) return false;
    const f = new Date(s.proximo_cobro).getTime();
    return f > Date.now() && f - Date.now() <= DIAS_AVISO * 864e5;
  }
  const porQuien = (s) => String(s.id || '').startsWith('stripe') ? 'Stripe' : 'Mercado Pago';
  // aviso arriba de la página los 7 días antes de cada cobro (además del correo)
  function avisoRenovacion() {
    let b = document.getElementById('aviso-renovacion');
    const s = miSub();
    const clave = s && s.proximo_cobro ? 'sp_aviso_' + s.id + '_' + String(s.proximo_cobro).slice(0, 10) : '';
    let visto = false;
    try { visto = !!(clave && localStorage.getItem(clave)); } catch (e) { /* sin almacenamiento: se enseña */ }
    if (!renuevaPronto(s) || visto) { if (b) b.remove(); return; }
    if (!b) {
      b = document.createElement('div'); b.id = 'aviso-renovacion'; b.className = 'aviso-renovacion';
      document.body.insertBefore(b, document.body.firstChild);
    }
    b.innerHTML = '⏰ Tu VIP se renueva el <b>' + esc(fecha(s.proximo_cobro)) + '</b> por <b>$' + Math.round(s.precio) + '</b> (' + porQuien(s) + '). ' +
      '<button class="ver" data-mi-cuenta>Ver o cancelar</button> <button class="cerrar-aviso" data-cerrar-aviso="' + esc(clave) + '">✕</button>';
  }
  function cajaSuscripcion() {
    const s = miSub(); const p = yo.perfil || {};
    if (!s || esAdmin()) return '';
    let h = '<div class="caja"><div class="tit">🔁 Mi suscripción</div>';
    if (s.estado === 'authorized' && s.renueva) {
      h += '<p class="sub">VIP ' + esc(s.tipo) + ' con ' + porQuien(s) + '. Se renueva <b>automáticamente</b> el <b>' + esc(fecha(s.proximo_cobro)) +
        '</b> por <b>$' + Math.round(s.precio) + '</b>. Te avisamos ' + DIAS_AVISO + ' días antes.</p>' +
        '<button class="vip-btn sec" data-sus="cancelar">Cancelar renovación</button>' +
        '<p class="tenue chico">Si cancelas, sigues siendo VIP hasta el ' + esc(fecha(p.plan_hasta || s.proximo_cobro)) + ' y no se te vuelve a cobrar.</p>';
    } else if (s.estado === 'cancela_al_final') {
      h += '<p class="sub">Cancelaste la renovación: eres VIP hasta el <b>' + esc(fecha(p.plan_hasta || s.proximo_cobro)) + '</b> y no se te volverá a cobrar.</p>' +
        '<button class="vip-btn sec" data-sus="reactivar">Volver a renovar automáticamente</button>';
    } else if (s.estado === 'pagado') {
      h += '<p class="sub">Pago único, <b>sin renovación automática</b>: eres VIP hasta el <b>' + esc(fecha(p.plan_hasta)) + '</b>. Al terminar no se cobra nada.</p>';
    } else {
      h += '<p class="sub">Renovación cancelada: eres VIP hasta el <b>' + esc(fecha(p.plan_hasta)) + '</b> y no se te volverá a cobrar.</p>';
    }
    if (String(s.id).startsWith('stripe:')) h += '<button class="ver" data-portal>💳 Cambiar tarjeta o ver mis recibos (Stripe)</button>';
    return h + '</div>';
  }
  function metodoPago() {
    const m = yo.metodo || 'stripe';
    return '<div class="metodo"><span class="tenue chico">Pagar con:</span>' +
      '<button class="seg' + (m === 'stripe' ? ' activa' : '') + '" data-metodo="stripe"> Pay · tarjeta</button>' +
      '<button class="seg' + (m === 'mp' ? ' activa' : '') + '" data-metodo="mp">Mercado Pago · OXXO</button></div>';
  }

  function pintarCabecera() {
    const c = $('cuenta'); if (!c) return;
    if (!sb) { c.innerHTML = ''; return; }
    if (!yo.user) { c.innerHTML = '<button class="entrar" data-entrar>Entrar</button>'; return; }
    // v416 — mientras el perfil no llega NO se inventa: ni el correo como
    // nombre ni «0 monedas» (al admin le salía su correo de Google y 0 🪙)
    if (!yo.perfil) { c.innerHTML = '<span class="saldo" title="Tus monedas">🪙 …</span><button class="entrar" data-mi-cuenta>Mi cuenta ▾</button>'; return; }
    const nom = yo.perfil.usuario || yo.perfil.nombre || String(yo.user.email || 'Mi cuenta').split('@')[0];
    c.innerHTML = '<span class="saldo" title="Tus monedas">🪙 ' + (esAdmin() ? '∞' : ((yo.perfil && yo.perfil.monedas) || 0)) + '</span>' +
      (esVip() ? '<span class="et nivel diamante">' + (esAdmin() ? 'ADMIN' : 'VIP') + '</span>' : '') +
      '<button class="entrar" data-mi-cuenta>' + esc(nom) + ' ▾</button>';
    // con Google no se eligió usuario: se pide una vez
    if (yo.perfil && !yo.perfil.usuario && $('elegir').hidden) $('elegir').hidden = false;
    // v422 — los intereses: a quien nunca los eligió, una vez (y no si dijo «ahora no» hace menos de 7 días)
    else if (yo.perfil && yo.perfil.usuario && yo.perfil.deportes == null && $('intereses').hidden && !yo.intPreguntado) {
      let no = 0; try { no = Number(localStorage.getItem('sharpicks-intereses-no-' + yo.user.id) || 0); } catch (e) { /* nada */ }
      if (Date.now() - no > 7 * 864e5) { yo.intPreguntado = true; setTimeout(abrirIntereses, 1200); }
    }
  }

  function abrirAcceso(msg, modo) {
    verModo(modo || 'entrar');
    $('acceso-msg').textContent = msg || '';
    const g = document.querySelector('[data-google]'); if (g) g.hidden = !C.LOGIN_GOOGLE;
    $('acceso').hidden = false;
    captchaListo();
  }
  function verModo(m) {
    document.querySelectorAll('[data-modo]').forEach((x) => { x.hidden = x.dataset.modo !== m; });
    document.querySelectorAll('[data-ir-modo]').forEach((x) => x.classList.toggle('activa', x.dataset.irModo === m));
  }

  // v414 — CAPTCHA (Cloudflare Turnstile) contra robots en registro, entrada y
  // enlace por correo. Casi nunca le pide nada a una persona («interaction-only»).
  let captchaId = null;
  function captchaListo() {
    try {
      if (captchaId != null || !C.TURNSTILE_SITE_KEY || !window.turnstile || !$('captcha')) return;
      captchaId = window.turnstile.render('#captcha', { sitekey: C.TURNSTILE_SITE_KEY, theme: 'dark', size: 'flexible', appearance: 'interaction-only', language: 'es' });
    } catch (e) { captchaId = null; }
  }
  function tokenCaptcha() {
    try { return (captchaId != null && window.turnstile.getResponse(captchaId)) || undefined; } catch (e) { return undefined; }
  }
  async function esperarCaptcha(ms = 6000) {
    if (captchaId == null) return undefined;
    for (let t = 0; t < ms; t += 200) { const k = tokenCaptcha(); if (k) return k; await new Promise((r) => setTimeout(r, 200)); }
    return tokenCaptcha();
  }
  // el botón con su animación mientras trabaja
  function ocupado(b, texto) {
    if (!b) return () => {};
    const antes = b.textContent; b.disabled = true; b.classList.add('cargando'); b.textContent = texto;
    return () => { b.disabled = false; b.classList.remove('cargando'); b.textContent = antes; };
  }
  function reiniciarCaptcha() { try { if (captchaId != null) window.turnstile.reset(captchaId); } catch (e) { /* nada */ } }
  // v413 — la misma regla que exige Supabase (8+ caracteres, letras y números)
  function contraDebil(c) {
    if (String(c).length < 8) return 'La contraseña debe tener al menos 8 caracteres.';
    if (!/[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]/.test(c) || !/\d/.test(c)) return 'La contraseña debe tener letras y números.';
    return '';
  }
  async function entrarConUsuario(u, contra) {
    if (u.includes('@')) {
      const { data, error } = await sb.auth.signInWithPassword({ email: u, password: contra, options: { captchaToken: await esperarCaptcha() } });
      reiniciarCaptcha();
      if (!error && data && data.user) yo.user = data.user;
      if (error && /captcha/i.test(error.message)) return 'Completa la verificación de abajo y vuelve a intentar.';
      if (error && (error.status === 429 || /rate limit/i.test(error.message))) return 'Demasiados intentos. Espera unos minutos.';
      return error ? 'Correo o contraseña incorrectos.' : '';
    }
    const r = await fetch(FN + 'entrar', { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: C.SUPABASE_ANON_KEY },
      body: JSON.stringify({ usuario: u, contrasena: contra, captcha: await esperarCaptcha() }) });
    reiniciarCaptcha();
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.access_token) return d.error || 'No se pudo entrar.';
    const { data: ses, error } = await sb.auth.setSession({ access_token: d.access_token, refresh_token: d.refresh_token });
    if (!error && ses && ses.user) yo.user = ses.user;
    return error ? 'No se pudo entrar.' : '';
  }

  async function abrirMiCuenta(msg) {
    if (!yo.user && listo) await aTiempo(listo, 8000, null);
    if (!yo.user) { abrirAcceso(); return; }
    const p = yo.perfil || {};
    // se abre YA con lo básico (y «Cerrar sesión»); lo que tarda se agrega después
    if ($('micuenta').hidden) {
      $('micuenta-cuerpo').innerHTML = '<button class="cerrar" data-cerrar-cuenta>✕</button><h3>Mi cuenta</h3>' +
        '<div class="cuenta-cab"><b>@' + esc(p.usuario || '—') + '</b><span class="tenue">' + esc(yo.user.email || '') + '</span></div>' +
        ESQ + '<button class="salir" data-salir>Cerrar sesión</button>';
      $('micuenta').hidden = false;
    }
    const [r1, r2] = await Promise.all([
      aTiempo(sb.rpc('lugares_fundador'), 5000, { data: 0 }),
      aTiempo(sb.rpc('enlace_vip'), 5000, { data: null }),
    ]);
    const lugares = (r1 && r1.data) || 0, vipUrl = r2 && r2.data;
    const pm = Number(yo.precios.precio_mensual || 149), pf = Number(yo.precios.precio_fundador || 99), ps = Number(yo.precios.precio_semestral || 749);
    let h = '<button class="cerrar" data-cerrar-cuenta>✕</button><h3>Mi cuenta</h3>' +
      '<div class="cuenta-cab"><b>@' + esc(p.usuario || '—') + '</b><span class="tenue">' + esc(yo.user.email || '') + '</span></div>' +
      '<div class="cuenta-plan">' + (esAdmin() ? '👑 <b>Administrador</b> · monedas y VIP ilimitados'
        : esVip() ? '💎 <b>VIP</b> hasta el ' + esc(fecha(p.plan_hasta)) : 'Plan <b>Gratis</b>') +
      '<span>🪙 ' + (esAdmin() ? '∞' : (p.monedas || 0)) + '</span></div>';
    if (msg) h += '<p class="aviso-ok">' + esc(msg) + '</p>';
    if (vipUrl) h += '<a class="tg vip bloque" href="' + esc(vipUrl) + '" target="_blank" rel="noopener">💎 Entrar al grupo VIP de Telegram</a>';
    h += cajaSuscripcion();
    if (!esVip()) {
      h += '<div class="caja vip-caja"><div class="tit">Hazte VIP</div>' +
        '<p class="sub">Todos los 💎 y 🔷 sin gastar monedas y el grupo VIP de Telegram con avisos al momento. Cancelas cuando quieras.</p>' +
        metodoPago() +
        ((yo.metodo || 'stripe') === 'mp' ? '<label class="campo">Correo de tu cuenta de Mercado Pago<input type="email" id="mp-correo" value="' + esc(yo.user.email || '') + '"></label>' : '') +
        '<label class="renovar"><input type="checkbox" id="vip-renovar" checked> <span>🔁 <b>Renovar automáticamente</b> cada periodo. ' +
        'Te avisamos ' + DIAS_AVISO + ' días antes de cada cobro y cancelas cuando quieras. Sin marcar: pagas sólo este periodo.</span></label>' +
        '<button class="vip-btn" data-vip="mensual">' + (lugares > 0 ? '⭐ Fundador: $' + pf + ' al mes <small>quedan ' + lugares + ' de 50 · después $' + pm + '</small>' : 'Mensual: $' + pm + ' al mes') + '</button>' +
        '<button class="vip-btn sec" data-vip="semestral">Semestral: $' + ps + ' cada 6 meses <small>≈ $' + Math.round(ps / 6) + ' al mes</small></button>' +
        '<p class="tenue chico">Precios en pesos con IVA incluido. El cobro lo hace Stripe o Mercado Pago; nosotros nunca vemos tu tarjeta.</p></div>';
    }
    if (!esAdmin()) {
      h += '<div class="caja"><div class="tit">🪙 Comprar monedas</div>' + (esVip() ? metodoPago() : '') + '<div class="paquetes">' +
        (yo.paquetes || []).map((k) => '<button class="paquete' + (k.id === 'popular' ? ' top' : '') + '" data-comprar="' + esc(k.id) + '"><b>' + k.monedas +
          ' 🪙</b><span>$' + Math.round(k.precio) + '</span><small>' + esc(k.nombre) + (k.id === 'popular' ? ' · el más pedido' : '') + '</small></button>').join('') +
        '</div><p class="tenue chico">💎 🔷 🥈 💰 cuestan de 5 a 25 🪙 según su cuota. Si el pick sale rojo, te regresamos tus monedas solas.</p></div>';
    }
    h += '<div class="caja"><div class="tit">👤 Nombre de usuario</div><div class="fila-form"><input id="mi-usuario" value="' + esc(p.usuario || '') +
      '" placeholder="3-20 letras, números, _ o ." autocapitalize="off"><button class="ver" data-mi-usuario>Guardar</button></div></div>';
    h += '<div class="caja"><div class="tit">🎯 Mis intereses</div><p class="tenue chico">Tus deportes y ligas van primero y arman tu «✨ Para ti».</p>' +
      '<button class="ver" data-intereses>Elegir deportes y ligas</button></div>';
    // v446 — sus reportes de errores (y, al administrador, los que faltan por revisar)
    h += '<div class="caja"><div class="tit">⚠️ ' + (esAdmin() ? 'Reportes' : 'Mis reportes') + '</div><div id="mis-reportes">' + ESQ + '</div></div>';
    h += '<div class="caja"><div class="tit">🎁 Canjear código</div><div class="fila-form"><input id="codigo" placeholder="SHARP-XXXX-XXXX" autocomplete="off"><button class="ver" data-canjear>Canjear</button></div></div>' +
      '<div class="caja"><div class="tit">🔑 ' + (yo.user.app_metadata && yo.user.app_metadata.provider === 'google' ? 'Crear contraseña (para entrar con tu usuario)' : 'Cambiar contraseña') + '</div>' +
      '<div class="fila-form"><input type="password" id="nueva-contra" placeholder="8+ caracteres, letras y números" autocomplete="new-password"><button class="ver" data-contra>Guardar</button></div></div>' +
      '<button class="salir" data-salir>Cerrar sesión</button>';
    $('micuenta-cuerpo').innerHTML = h;
    $('micuenta').hidden = false;
    pintarReportes();
  }

  // ---------- v446 — LO QUE APORTAN LOS USUARIOS ----------
  // 1) «⚠️ Reportar un error»: lo revisa el administrador y, si es real, el
  //    servidor le da 5 🪙 (`resolver_reporte`; a lo más 3 pagados por día).
  // 2) «¿Te sirvió el análisis de la IA? 👍/👎»: SÓLO se mide; no da monedas ni
  //    cambia cómo trabaja la IA.
  const TIPOS_REP = [['resultado', 'Resultado mal'], ['equipo', 'Equipo equivocado'], ['dato', 'Dato raro'], ['otro', 'Otro']];
  const ESTADO_REP = { pendiente: '⏳ En revisión', aceptado: '✅ Era un error', rechazado: '❌ No era error' };
  function abrirReporte(partido, pick) {
    if (!yo.user) { abrirAcceso('Entra para reportar un error.'); return; }
    let caja = $('reporte');
    if (!caja) { caja = document.createElement('div'); caja.className = 'ficha'; caja.id = 'reporte'; document.body.appendChild(caja); }
    caja.dataset.partido = partido; caja.dataset.pick = pick || '';
    caja.innerHTML = '<div class="ficha-caja acceso"><button class="cerrar" data-cerrar-reporte>✕</button><h3>⚠️ Reportar un error</h3>' +
      '<p class="tenue chico">' + esc(partido) + '</p><div class="chips">' +
      TIPOS_REP.map(([k, t], i) => '<button class="chip' + (i ? '' : ' activa') + '" data-rep-tipo="' + k + '">' + t + '</button>').join('') + '</div>' +
      '<textarea id="rep-detalle" class="rep-detalle" maxlength="400" rows="4" placeholder="¿Qué está mal? Ej.: quedó 2-1 y aquí salió 1-1."></textarea>' +
      '<button class="vip-btn" data-enviar-reporte>Enviar</button><p class="sub" id="rep-msg">Si es real, te damos 5 🪙 cuando lo confirmemos.</p></div>';
    caja.hidden = false;
  }
  async function pintarReportes() {
    const caja = $('mis-reportes'); if (!caja || !yo.user) return;
    const { data, error } = await aTiempo(sb.from('reportes').select('*').order('creado', { ascending: false }).limit(60), 6000, { data: null, error: true });
    const vacio = '<p class="tenue chico">¿Viste algo mal? Toca «⚠️ Reportar un error» dentro del partido. Si es real, +5 🪙.</p>';
    if (error || !data) { caja.innerHTML = vacio; return; }
    const mios = data.filter((r) => r.usuario === yo.user.id), revisar = esAdmin() ? data.filter((r) => r.estado === 'pendiente') : [];
    const item = (r, botones) => '<div class="rep-item"><div><b>' + esc(r.partido) + '</b><small>' +
      esc((TIPOS_REP.find(([k]) => k === r.tipo) || ['', r.tipo])[1]) + ' · ' + esc(fecha(r.creado)) + (botones ? '' : ' · ' + ESTADO_REP[r.estado] + (r.monedas ? ' · +' + r.monedas + ' 🪙' : '')) +
      '</small></div><p>' + esc(r.detalle) + '</p>' + (botones ? '<div class="fila-form"><button class="ver" data-resolver="' + esc(r.id) + '" data-aceptar="1">✅ Es real (+5 🪙)</button>' +
      '<button class="ver" data-resolver="' + esc(r.id) + '" data-aceptar="0">❌ No</button></div>' : '') + '</div>';
    let h = '';
    if (esAdmin()) h += '<div class="rep-sub">Por revisar (' + revisar.length + ')</div>' + (revisar.length ? revisar.map((r) => item(r, true)).join('') : '<p class="tenue chico">Nada pendiente.</p>');
    h += (esAdmin() ? '<div class="rep-sub">Los tuyos</div>' : '') + (mios.length ? mios.map((r) => item(r, false)).join('') : vacio);
    caja.innerHTML = h;
  }
  function votoIA(id) {
    if (!id || !yo.user) return '';
    const v = (yo.votosIA || {})[id] || {};
    return '<div class="ia-voto" data-ia-id="' + esc(id) + '"><span>¿Te sirvió?</span>' +
      '<button class="' + (v.voto === 1 ? 'si' : '') + '" data-ia-voto="1" aria-label="Me sirvió">👍</button>' +
      '<button class="' + (v.voto === -1 ? 'si' : '') + '" data-ia-voto="-1" aria-label="No me sirvió">👎</button>' +
      (v.voto ? '<small class="tenue">¡Gracias!</small>' : '') + '</div>';
  }
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-reportar],[data-cerrar-reporte],[data-rep-tipo],[data-enviar-reporte],[data-resolver],[data-ia-voto],[data-ia-motivo]');
    if (!t) return;
    if (t.dataset.reportar) { abrirReporte(t.dataset.reportar, t.dataset.pick); return; }
    if (t.hasAttribute('data-cerrar-reporte')) { $('reporte').hidden = true; return; }
    if (t.dataset.repTipo) { document.querySelectorAll('[data-rep-tipo]').forEach((b) => b.classList.toggle('activa', b === t)); return; }
    if (t.hasAttribute('data-enviar-reporte')) {
      const caja = $('reporte'), m = $('rep-msg'), det = ($('rep-detalle').value || '').trim();
      const tipo = (document.querySelector('[data-rep-tipo].activa') || { dataset: {} }).dataset.repTipo || 'otro';
      if (det.length < 5) { m.textContent = 'Cuéntanos un poco más.'; return; }
      const listo = ocupado(t, 'Enviando…');
      const { error } = await aTiempo(sb.rpc('reportar', { p_partido: caja.dataset.partido, p_pick: caja.dataset.pick || null, p_tipo: tipo, p_detalle: det }),
        8000, { error: { message: 'No se pudo enviar: revisa tu conexión.' } });
      listo();
      if (error) { m.textContent = /function|schema|exist/i.test(error.message || '') ? 'Muy pronto: estamos activando los reportes.' : error.message; return; }
      caja.hidden = true;
      avisoFlotante('¡Gracias! Lo revisamos y te avisamos aquí, en «Mi cuenta».');
      return;
    }
    if (t.dataset.resolver) {
      const listo = ocupado(t, '…');
      const { data, error } = await aTiempo(sb.rpc('resolver_reporte', { p_id: t.dataset.resolver, p_aceptar: t.dataset.aceptar === '1' }), 8000, { error: { message: 'Sin conexión.' } });
      listo();
      if (error) { avisoFlotante(error.message || 'No se pudo.'); return; }
      avisoFlotante(t.dataset.aceptar === '1' ? (data ? 'Aceptado: +' + data + ' 🪙 al usuario' : 'Aceptado (ya llevaba 3 pagados hoy)') : 'Rechazado');
      pintarReportes();
      return;
    }
    if (t.dataset.iaVoto || t.dataset.iaMotivo) {
      if (!yo.user) { abrirAcceso(); return; }
      const cont = t.closest('[data-ia-id]'), id = cont.dataset.iaId, antes = (yo.votosIA || {})[id];
      const voto = t.dataset.iaVoto ? Number(t.dataset.iaVoto) : -1;
      const motivo = voto === 1 ? null : (t.dataset.iaMotivo || null);
      yo.votosIA = yo.votosIA || {};
      yo.votosIA[id] = { analisis: id, voto, motivo };
      cont.outerHTML = votoIA(id);
      const { error } = await aTiempo(sb.from('ia_calificaciones').upsert({ usuario: yo.user.id, analisis: id, voto, motivo }, { onConflict: 'usuario,analisis' }),
        6000, { error: { message: 'tiempo' } });
      if (error) {
        if (antes) yo.votosIA[id] = antes; else delete yo.votosIA[id];
        const c2 = document.querySelector('[data-ia-id="' + CSS.escape(id) + '"]'); if (c2) c2.outerHTML = votoIA(id);
        avisoFlotante('Muy pronto podrás calificar la IA.');
      }
    }
  });

  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-entrar],[data-salir],[data-seguir],[data-desbloquear],[data-cerrar-acceso],[data-google],[data-ir-modo],[data-mi-cuenta],[data-cerrar-cuenta],[data-canjear],[data-contra],[data-vip],[data-enlace],[data-ayuda],[data-cerrar-ayuda],[data-mi-usuario],[data-comprar],[data-metodo],[data-sus],[data-portal],[data-cerrar-aviso],[data-desb-comb]');
    if (!t) return;
    if (t.hasAttribute('data-ayuda')) { $('ayuda').hidden = false; return; }
    if (t.hasAttribute('data-cerrar-ayuda')) { $('ayuda').hidden = true; return; }
    if (t.hasAttribute('data-google')) {
      const { error } = await sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: location.origin + location.pathname } });
      if (error) $('acceso-msg').textContent = 'Google no respondió; intenta con tu usuario.';
      return;
    }
    if (t.dataset.irModo) { verModo(t.dataset.irModo); $('acceso-msg').textContent = ''; return; }
    if (t.hasAttribute('data-cerrar-acceso')) { $('acceso').hidden = true; return; }
    if (t.hasAttribute('data-cerrar-cuenta')) { $('micuenta').hidden = true; return; }
    if (t.hasAttribute('data-entrar')) { abrirAcceso(); return; }
    if (t.hasAttribute('data-mi-cuenta')) { abrirMiCuenta(); return; }
    if (t.hasAttribute('data-salir')) {
      // v421 — «al cerrar sesión tarda en actualizarse»: se esperaba a Supabase
      // (hasta 4 s) ANTES de limpiar. Ahora la pantalla se limpia al instante.
      $('micuenta').hidden = true;
      try { Object.keys(localStorage).filter((k) => k.startsWith('sb-')).forEach((k) => localStorage.removeItem(k)); } catch (e) {}
      guardarPerfil(null);
      yo.user = null; yo.perfil = null; yo.seguidos = new Set(); yo.desbloqueados = {}; yo.ia = {}; yo.subs = [];
      pintarCabecera(); if (window.SP) window.SP.pintar();
      aTiempo(sb.auth.signOut({ scope: 'local' }), 4000, null).then(() => refrescar());
      return;
    }
    if (t.hasAttribute('data-enlace')) {
      // v425 — «me pide a fuerza el correo; con el usuario también debería»
      const quien = $('e-usuario').value.trim();
      if (!quien) { $('acceso-msg').textContent = 'Escribe arriba tu usuario o tu correo para mandarte el enlace.'; return; }
      const listo = ocupado(t, 'Enviando…');
      let msg;
      // v426 — «cuando le pico sólo inicia sesión; no me dice que restablezca la
      // contraseña»: era un enlace para ENTRAR. Ahora es el de restablecer.
      if (quien.includes('@')) {
        const { error } = await sb.auth.resetPasswordForEmail(quien, { redirectTo: location.origin + location.pathname, captchaToken: await esperarCaptcha() });
        msg = error ? (/captcha/i.test(error.message) ? 'Completa la verificación de abajo y vuelve a intentar.' : 'No se pudo enviar el correo. Intenta en unos minutos.')
          : 'Listo: te mandamos el enlace para elegir tu contraseña nueva (revisa también «spam»).';
      } else {
        const r = await fetch(FN + 'entrar', { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: C.SUPABASE_ANON_KEY },
          body: JSON.stringify({ usuario: quien, accion: 'recuperar', captcha: await esperarCaptcha() }) }).catch(() => null);
        const d = r ? await r.json().catch(() => ({})) : {};
        msg = d.ok ? d.mensaje : (d.error && !/contraseña/.test(d.error) ? d.error : 'Escribe tu correo arriba para mandarte el enlace.');
      }
      reiniciarCaptcha(); listo();
      $('acceso-msg').textContent = msg;
      return;
    }
    if (t.dataset.cerrarAviso != null) {
      try { localStorage.setItem(t.dataset.cerrarAviso, '1'); } catch (e2) { /* sin almacenamiento */ }
      const b = document.getElementById('aviso-renovacion'); if (b) b.remove();
      return;
    }
    if (!yo.user) { abrirAcceso('Inicia sesión para seguir y desbloquear picks.'); return; }
    if (t.dataset.metodo) { yo.metodo = t.dataset.metodo; abrirMiCuenta(); return; }
    if (t.dataset.sus || t.hasAttribute('data-portal')) {
      if (t.dataset.sus === 'cancelar' && !(await confirmarApp('¿Cancelar la renovación automática?', 'Sigues siendo VIP hasta el final de lo ya pagado.', 'Sí, cancelar'))) return;
      t.disabled = true;
      const { data: s } = await sb.auth.getSession();
      const r = await fetch(FN + (t.dataset.sus ? 'suscripcion' : 'stripe'), { method: 'POST', headers: { 'Content-Type': 'application/json',
        apikey: C.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + (s.session ? s.session.access_token : '') },
        body: JSON.stringify({ accion: t.dataset.sus || 'portal' }) });
      const d = await r.json().catch(() => ({}));
      if (d.url) { location.href = d.url; return; }
      await refrescar();
      abrirMiCuenta(d.error || (t.dataset.sus === 'cancelar' ? '✅ Renovación cancelada. Sigues siendo VIP hasta el ' + fecha(d.hasta) + '.'
        : '✅ Listo: tu VIP se volverá a renovar automáticamente.'));
      return;
    }
    if (t.dataset.comprar) {
      t.disabled = true;
      const { data: s } = await sb.auth.getSession();
      const conStripe = (yo.metodo || 'stripe') === 'stripe';
      const r = await fetch(FN + (conStripe ? 'stripe' : 'monedas'), { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: C.SUPABASE_ANON_KEY,
        Authorization: 'Bearer ' + (s.session ? s.session.access_token : '') },
        body: JSON.stringify(conStripe ? { accion: 'monedas', paquete: t.dataset.comprar } : { paquete: t.dataset.comprar }) });
      const d = await r.json().catch(() => ({}));
      if (d.url) { location.href = d.url; return; }
      t.disabled = false;
      abrirMiCuenta(d.error || 'No se pudo iniciar el pago.');
      return;
    }
    if (t.hasAttribute('data-mi-usuario')) {
      const u = $('mi-usuario').value.trim();
      if (!RE_USUARIO.test(u)) { abrirMiCuenta('El usuario: de 3 a 20 letras, números, «_» o «.», sin espacios.'); return; }
      if (yo.perfil && (yo.perfil.usuario || '').toLowerCase() !== u.toLowerCase()) {
        const { data: libre } = await sb.rpc('usuario_libre', { u });
        if (!libre) { abrirMiCuenta('Ese usuario ya existe. Prueba otro.'); return; }
      }
      const { error } = await sb.from('perfiles').update({ usuario: u, nombre: u }).eq('id', yo.user.id);
      await refrescar();
      abrirMiCuenta(error ? 'No se pudo guardar. Prueba otro.' : '👤 Listo: ahora eres @' + u + '.');
      return;
    }
    if (t.hasAttribute('data-canjear')) {
      const { data } = await sb.rpc('canjear_codigo', { c: $('codigo').value });
      await refrescar();
      abrirMiCuenta(data === 'ok' ? '🎉 ¡Listo! Ya eres VIP.' : data === 'ya usado' ? 'Ese código ya se usó.' : 'Ese código no existe. Revísalo.');
      return;
    }
    if (t.hasAttribute('data-contra')) {
      const c1 = $('nueva-contra').value;
      if (contraDebil(c1)) { abrirMiCuenta(contraDebil(c1)); return; }
      const { error } = await sb.auth.updateUser({ password: c1 });
      abrirMiCuenta(error ? 'No se pudo guardar: ' + error.message : '🔑 Contraseña guardada. Ya puedes entrar con tu usuario.');
      return;
    }
    if (t.dataset.vip) {
      t.disabled = true;
      const { data: s } = await sb.auth.getSession();
      const renovar = !$('vip-renovar') || $('vip-renovar').checked;
      const conStripe = (yo.metodo || 'stripe') === 'stripe';
      const r = await fetch(FN + (conStripe ? 'stripe' : 'vip'), { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: C.SUPABASE_ANON_KEY,
        Authorization: 'Bearer ' + (s.session ? s.session.access_token : '') },
        body: JSON.stringify(conStripe ? { accion: 'vip', tipo: t.dataset.vip, renovar } : { tipo: t.dataset.vip, correo: ($('mp-correo') || {}).value, renovar }) });
      const d = await r.json().catch(() => ({}));
      if (d.url) { location.href = d.url; return; }
      t.disabled = false;
      abrirMiCuenta(d.error || 'No se pudo iniciar el pago.');
      return;
    }
    if (t.dataset.seguir) {
      // v421 — «al darle seguir se buguea y cuenta mis toques como si fueran más
      // personas»: cada toque sumaba al instante y, con toques seguidos, el
      // «dejar de seguir» podía llegar antes que el «seguir». Ahora: un toque a
      // la vez por pick (los demás se ignoran mientras la base responde), la
      // estrella cambia YA y el número se vuelve a leer de la base al terminar.
      const id = t.dataset.seguir, sigo = yo.seguidos.has(id);
      yo.siguiendoAhora = yo.siguiendoAhora || new Set();
      if (yo.siguiendoAhora.has(id)) return;
      yo.siguiendoAhora.add(id);
      if (sigo) yo.seguidos.delete(id); else yo.seguidos.add(id);
      document.querySelectorAll('[data-seguir="' + CSS.escape(id) + '"]').forEach((b) => { b.classList.toggle('si', !sigo); b.textContent = !sigo ? '★ Siguiendo' : '☆ Seguir'; });
      const q = sigo ? sb.from('seguidos').delete().eq('pick', id).eq('usuario', yo.user.id)
        : sb.from('seguidos').upsert({ pick: id, usuario: yo.user.id }, { onConflict: 'usuario,pick', ignoreDuplicates: true });
      aTiempo(q, 6000, { error: 'tiempo' }).then(async (res) => {
        if (res && res.error) { if (sigo) yo.seguidos.add(id); else yo.seguidos.delete(id); }
        const { data } = await aTiempo(sb.from('seguidores').select('pick,n').eq('pick', id), 6000, { data: null });
        if (data) yo.conteo[id] = data[0] ? data[0].n : 0;
        yo.siguiendoAhora.delete(id);
        window.SP.pintar();
      });
      return;
    }
    if (t.dataset.desbComb) {
      t.disabled = true;
      const { data, error } = await sb.rpc('desbloquear_combinada', { comb_id: t.dataset.desbComb });
      if (error || data !== 'ok') { avisoApp(data === 'sin monedas' ? 'Consigue más en «Planes» o acertando tus combinadas.' : data === 'ya empezó' ? 'Uno de sus partidos ya empezó.' : 'Intenta de nuevo en un momento.', 'aviso', data === 'sin monedas' ? 'No te alcanzan las monedas' : 'No se pudo desbloquear'); t.disabled = false; return; }
      await refrescar();
      return;
    }
    if (t.dataset.desbloquear) {
      t.disabled = true;
      const { data, error } = await sb.rpc('desbloquear', { pick_id: t.dataset.desbloquear });
      if (error || data !== 'ok') { avisoApp(data === 'sin monedas' ? 'Consigue más en «Planes» o acertando tus combinadas.' : data === 'ya empezó' ? 'Ese partido ya empezó.' : 'Intenta de nuevo en un momento.', 'aviso', data === 'sin monedas' ? 'No te alcanzan las monedas' : 'No se pudo desbloquear'); t.disabled = false; return; }
      await refrescar();
    }
  });

  // entrar con usuario (o correo) y contraseña
  $('f-entrar') && $('f-entrar').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = $('e-usuario').value.trim(), c1 = $('e-contra').value;
    if (!u || !c1) { $('acceso-msg').textContent = 'Escribe tu usuario y tu contraseña.'; return; }
    $('acceso-msg').textContent = '';
    const listo = ocupado(e.target.querySelector('button[type=submit]'), 'Entrando…');
    const err = await entrarConUsuario(u, c1);
    listo();
    if (err) { $('acceso-msg').textContent = err; return; }
    $('acceso').hidden = true;
    if (yo.user) { yo.perfil = perfilGuardado(yo.user.id) || yo.perfil; pintarCabecera(); }
    refrescar();                       // lo demás carga detrás
  });
  // crear cuenta: usuario + correo + contraseña
  $('f-crear') && $('f-crear').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = $('c-usuario').value.trim(), correo = $('c-correo').value.trim(), c1 = $('c-contra').value, c2 = $('c-contra2').value;
    const msg = (x) => { $('acceso-msg').textContent = x; };
    if (!RE_USUARIO.test(u)) return msg('El usuario: de 3 a 20 letras, números, «_» o «.», sin espacios.');
    if (contraDebil(c1)) return msg(contraDebil(c1));
    if (c1 !== c2) return msg('Las contraseñas no coinciden.');
    msg('Creando tu cuenta…');
    const { data: libre } = await sb.rpc('usuario_libre', { u });
    if (!libre) return msg('Ese usuario ya existe. Prueba otro.');
    const listo = ocupado(e.target.querySelector('button[type=submit]'), 'Creando…');
    const { data, error } = await sb.auth.signUp({ email: correo, password: c1, options: { data: { usuario: u }, captchaToken: await esperarCaptcha(), emailRedirectTo: location.origin + location.pathname } });
    listo();
    reiniciarCaptcha();
    if (error && /captcha/i.test(error.message)) return msg('Completa la verificación de abajo y vuelve a intentar.');
    if (error) return msg(/registered|exists/i.test(error.message) ? 'Ese correo ya tiene cuenta: entra con él.' : 'No se pudo crear: ' + error.message);
    if (!data.session) return msg('Cuenta creada. Revisa tu correo para confirmarla.');
    $('acceso').hidden = true;
    await refrescar();
  });
  // elegir usuario (la primera vez con Google)
  $('f-elegir') && $('f-elegir').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = $('u-nuevo').value.trim();
    if (!RE_USUARIO.test(u)) { $('elegir-msg').textContent = 'De 3 a 20 letras, números, «_» o «.», sin espacios.'; return; }
    const { data: libre } = await sb.rpc('usuario_libre', { u });
    if (!libre) { $('elegir-msg').textContent = 'Ese usuario ya existe. Prueba otro.'; return; }
    const { error } = await sb.from('perfiles').update({ usuario: u, nombre: u }).eq('id', yo.user.id);
    if (error) { $('elegir-msg').textContent = 'No se pudo guardar. Prueba otro.'; return; }
    $('elegir').hidden = true;
    await refrescar();
  });
  // v389 — de regreso de comprar monedas
  if (/[?&]monedas=/.test(location.search)) {
    const ok = /monedas=ok/.test(location.search), pend = /monedas=pendiente/.test(location.search);
    history.replaceState(null, '', location.pathname);
    setTimeout(async () => { if (!yo.user && listo) await aTiempo(listo, 8000, null); abrirMiCuenta(ok ? '🎉 ¡Gracias! Tus monedas llegan en unos segundos.' : pend ? 'Tu pago está en proceso; las monedas llegan en cuanto se apruebe.' : 'El pago no se completó.'); }, 1500);
    if (ok || pend) { let n = 0; const t2 = setInterval(async () => { await refrescar(); if (++n > 12) clearInterval(t2); }, 5000); }
  }
  if (/[?&]cuenta=1/.test(location.search)) {
    history.replaceState(null, '', location.pathname);
    setTimeout(() => abrirMiCuenta(), 1500);
  }
  // v401 — «¿Qué mejorarías?»: se guarda en `comentarios` (nadie lo puede leer
  // desde la página) y el bot lo manda al correo de SharPicks
  let comTipo = 'idea';
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-com-tipo],[data-ir-comentarios]');
    if (!t) return;
    if (t.dataset.comTipo) {
      comTipo = t.dataset.comTipo;
      document.querySelectorAll('[data-com-tipo]').forEach((b) => b.classList.toggle('activa', b === t));
      return;
    }
    $('ayuda').hidden = true;
    const ir = document.querySelector('[data-vista-ir="planes"]'); if (ir) ir.click();
    setTimeout(() => { const c = $('comentarios'); if (c) c.scrollIntoView({ behavior: 'smooth' }); const x = $('com-texto'); if (x) x.focus(); }, 250);
  });
  $('f-comentario') && $('f-comentario').addEventListener('submit', async (e) => {
    e.preventDefault();
    const texto = $('com-texto').value.trim(), correo = $('com-correo').value.trim() || (yo.user && yo.user.email) || null;
    if (texto.length < 3) { $('com-msg').textContent = 'Escribe un poco más, por favor.'; return; }
    const b = e.target.querySelector('button[type=submit]'); b.disabled = true;
    try {
      const { data: authData } = await sb.auth.getSession();
      const token = authData && authData.session ? authData.session.access_token : C.SUPABASE_ANON_KEY;
      const r = await fetch(FN + 'comentario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', apikey: C.SUPABASE_ANON_KEY, Authorization: 'Bearer ' + token },
        body: JSON.stringify({ tipo: comTipo, texto, correo, pagina: location.pathname + location.search }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.status === 429) { $('com-msg').textContent = d.error || 'Has enviado varios comentarios recientemente. Espera un rato.'; return; }
      if (!r.ok || !d.ok) { $('com-msg').textContent = d.error || 'No se pudo enviar. Intenta de nuevo en un momento.'; return; }
      $('com-texto').value = '';
      $('com-msg').textContent = '🙌 ¡Gracias! Ya nos llegó tu comentario.';
    } catch (err) {
      console.warn('[sharpicks] falló el envío de comentarios', err);
      $('com-msg').textContent = 'No se pudo conectar para enviar el comentario. Intenta de nuevo.';
    } finally {
      b.disabled = false;
    }
  });

  // de regreso de Mercado Pago o de Stripe
  if (/[?&]vip=ok/.test(location.search)) {
    history.replaceState(null, '', location.pathname);
    let n = 0;
    const t = setInterval(async () => {
      await refrescar();
      if (esVip() || ++n > 24) { clearInterval(t); if (esVip()) abrirMiCuenta('🎉 ¡Bienvenido al VIP!'); }
    }, 5000);
    setTimeout(() => abrirMiCuenta('Gracias: en cuanto se confirme el pago se activa tu VIP (unos segundos).'), 1500);
  }

  // ---------- historial público (verdes, rojas y porcentaje) ----------
  // v428 — «MIS COMBINADAS»: el usuario arma la suya con los picks de la app.
  // El boleto vive en su dispositivo hasta que la guarda; al guardarla la base
  // valida todo (crear_combinada) y, si acierta, le da sus monedillas
  // (liquidar_combinadas_usuario, lo corre el servidor).
  const PREMIO = (c) => (c >= 5 ? 5 : c >= 3 ? 3 : c >= 2 ? 2 : 0);
  function boleto() {
    try { return JSON.parse(localStorage.getItem('sharpicks-boleto-' + (yo.user && yo.user.id)) || '[]'); } catch (e) { return []; }
  }
  function guardarBoleto(ids) {
    try { localStorage.setItem('sharpicks-boleto-' + (yo.user && yo.user.id), JSON.stringify(ids)); } catch (e) { /* nada */ }
    pintarBoleto();
  }
  const pickDe = (id) => ((window.SP && window.SP.estado.picks) || []).find((x) => x.id === id);
  function pintarBoleto() {
    const caja = $('mi-boleto'); if (!caja) return;
    const ids = yo.user ? boleto() : [];
    const ps = ids.map(pickDe).filter(Boolean);
    if (!ps.length) { caja.hidden = true; return; }
    const cuota = ps.reduce((s, p) => s * Number(p.cuota || 1), 1), prob = ps.reduce((s, p) => s * Number(p.prob || 0), 1), pr = PREMIO(cuota);
    caja.hidden = false;
    caja.innerHTML = '<button class="boleto-cab" data-ver-boleto><span>🔗 <b>Tu combinada</b> · ' + ps.length + (ps.length === 1 ? ' pick' : ' picks') +
      ' · cuota <b>' + cuota.toFixed(2) + '</b></span><small>' + (ps.length < 2 ? 'agrega otro' : (pr ? 'si acierta: +' + pr + ' 🪙' : 'premio desde cuota 2,00')) + ' ▾</small></button>' +
      (yo.verBoleto ? '<div class="boleto-cuerpo">' + ps.map((p) => '<div class="boleto-pata"><span>' + apuesta(p) + '<small>' + esc(p.partido) + '</small></span><b>' +
        Number(p.cuota).toFixed(2) + '</b><button class="cerrar-mini" data-quitar-comb="' + esc(p.id) + '" aria-label="Quitar">✕</button></div>').join('') +
        '<div class="boleto-pie"><small>Probabilidad ~' + Math.round(100 * prob) + ' % · premio: 2 🪙 desde cuota 2,00, 3 🪙 desde 3,00, 5 🪙 desde 5,00 (una premiada por día)</small>' +
        '<button class="vip-btn" data-guardar-comb' + (ps.length < 2 ? ' disabled' : '') + '>Guardar combinada</button><p class="sub" id="boleto-msg"></p></div></div>' : '');
  }
  // v437 — el usuario: «hice una, cerré la app, volví a abrirla y mi combinada
  // desapareció». Estaba guardada (en la base): al volver, la página la pide
  // varias veces mientras renueva la sesión y una petición vieja SIN sesión
  // terminaba al último y la pintaba vacía. Ahora sólo pinta la más reciente,
  // un error nunca borra lo que ya se veía (se reintenta) y una copia en el
  // dispositivo la enseña al instante (sólo para pintar: manda la base).
  let turnoComb = 0;
  const COMB_GUARDADAS = () => 'sharpicks-comb-' + (yo.user && yo.user.id);
  async function misCombinadas(intento) {
    const caja = $('mis-comb'); if (!caja || !sb) return;
    if (!yo.user) { caja.innerHTML = '<p class="tenue">Entra para armar tus combinadas y ganar 🪙 cuando aciertan.</p>'; return; }
    const turno = ++turnoComb;
    let copia = null; try { copia = JSON.parse(localStorage.getItem(COMB_GUARDADAS()) || 'null'); } catch (e) { /* sin almacenamiento */ }
    if (copia && copia.length && !caja.dataset.pintada) { yo.hist = { combs: copia, extra: {} }; pintarCombinadas(caja); pintarHistorial($('mi-hist')); }
    const { data, error } = await sb.from('combinadas_usuario').select('*').order('creado', { ascending: false }).limit(300);
    if (turno !== turnoComb) return;                                  // ya hay una petición más nueva
    if (error) {
      if ((intento || 0) < 4) setTimeout(() => { if (turno === turnoComb) misCombinadas((intento || 0) + 1); }, 3000);
      if (!caja.dataset.pintada) caja.innerHTML = ESQ;
      return;
    }
    try { localStorage.setItem(COMB_GUARDADAS(), JSON.stringify(data || [])); } catch (e) { /* sin almacenamiento */ }
    const faltan = [...new Set((data || []).flatMap((c) => c.patas))].filter((id) => !pickDe(id));
    const extra = {};
    for (let i = 0; i < faltan.length; i += 300) {
      const { data: ps } = await sb.from('picks').select('id,partido,apuesta,cuota,estado,inicio,deporte,premium,marcador').in('id', faltan.slice(i, i + 300));
      (ps || []).forEach((p) => { extra[p.id] = p; });
    }
    if (turno !== turnoComb) return;
    yo.hist = { combs: data || [], extra };
    pintarCombinadas(caja);
    pintarHistorial($('mi-hist'));
  }
  // v439 — «MI HISTORIAL». v442 — el usuario: «sólo las combinadas que yo haga, no
  // las que siga». Es el registro de SUS combinadas ya terminadas (las de «Mis
  // combinadas» son las que están por jugar o en juego): cuántas acertó, de qué
  // cuota fue cada una y cómo le fue a cada pick.
  let rangoHist = 30;
  const ICO_HIST = new Proxy({}, { get: (_, d) => (window.SP && window.SP.icoDep ? window.SP.icoDep(d) : '') });
  const DIA_MX = (f) => new Intl.DateTimeFormat('es-MX', { timeZone: 'America/Mexico_City', weekday: 'short', day: 'numeric', month: 'short' }).format(f);
  const aFechaP = (s) => new Date(String(s || '').replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(String(s)) ? '' : 'Z'));
  function miHistorial() { pintarHistorial($('mi-hist')); }
  // v459 — el usuario: «la de 2 picks ya está en verde, ¿por qué no se sumó a mi historial?».
  // El historial sólo contaba lo que el servidor ya liquidó (pasa cada ~2 h). Ahora
  // «Mis combinadas» y «Mi historial» usan el MISMO resultado al pitazo: en cuanto se
  // decide, pasa al historial (y el servidor después lo confirma y paga las monedas).
  const vistoPick = (p) => (p && p.id && pickDe(p.id) && window.SP && window.SP.estadoVisto ? window.SP.estadoVisto(pickDe(p.id)) : p && p.estado);
  function estadoCombVisto(c, extra) {
    if (c.estado !== 'pendiente') return c.estado;
    const es = c.patas.map((id) => vistoPick(pickDe(id) || (extra || {})[id]));
    if (es.some((e) => e === 'roja')) return 'roja';
    if (es.every((e) => e === 'verde' || e === 'nula') && es.some((e) => e === 'verde')) return 'verde';
    return 'pendiente';
  }
  function pintarHistorial(caja) {
    if (!caja) return;
    if (!yo.user) { caja.innerHTML = '<p class="tenue">Entra para llevar el registro de tus combinadas.</p>'; return; }
    const h = yo.hist; if (!h) return;
    const desde = rangoHist ? Date.now() - rangoHist * 864e5 : 0;
    const combs = h.combs.filter((c) => estadoCombVisto(c, h.extra) !== 'pendiente' && aFechaP(c.inicio).getTime() >= desde)
      .sort((a, b) => aFechaP(b.inicio) - aFechaP(a.inicio));
    const rangos = [[7, '7 días'], [30, '30 días'], [0, 'Todo']].map(([n, t]) => '<button class="chip' + (rangoHist === n ? ' activa' : '') + '" data-hist-rango="' + n + '">' + t + '</button>').join('');
    let html = '<div class="chips">' + rangos + '</div>';
    if (!combs.length) { caja.innerHTML = html + '<p class="tenue">Aquí quedan tus combinadas cuando terminan.</p>'; return; }
    const cv = combs.filter((c) => estadoCombVisto(c, h.extra) === 'verde').length, cr = combs.filter((c) => estadoCombVisto(c, h.extra) === 'roja').length;
    const pct = cv + cr ? Math.round(100 * cv / (cv + cr)) : null, mon = combs.reduce((a, c) => a + (c.premio || 0), 0);
    // cada pick de esas combinadas, con su resultado (y por deporte)
    const patas = combs.flatMap((c) => c.patas.map((id) => pickDe(id) || h.extra[id])).filter(Boolean).map((p) => Object.assign({}, p, { _e: vistoPick(p) }));
    const pv = patas.filter((p) => p._e === 'verde').length, pr = patas.filter((p) => p._e === 'roja').length;
    const dep = {};
    patas.forEach((p) => { if (p._e !== 'verde' && p._e !== 'roja') return; const k = p.deporte || 'Otro'; (dep[k] = dep[k] || [0, 0])[p._e === 'verde' ? 0 : 1]++; });
    html += '<div class="num">✅ ' + cv + ' ❌ ' + cr + (pct != null ? ' <span class="pct">' + pct + ' %</span>' : '') + '</div>' +
      '<p class="tenue chico">Picks: ✅ ' + pv + ' ❌ ' + pr + (mon ? ' · +' + mon + ' 🪙 ganadas' : '') + '</p>' +
      (Object.keys(dep).length ? '<div class="hist-dep">' + Object.entries(dep).map(([k, [a, b]]) => '<span>' + (ICO_HIST[k] ? ICO_HIST[k] + ' ' : '') + esc(k) + ' <b>' + a + '-' + b + '</b> ' + Math.round(100 * a / (a + b)) + ' %</span>').join('') + '</div>' : '');
    let dia = '';
    combs.slice(0, 60).forEach((c) => {
      const dd = DIA_MX(aFechaP(c.inicio)); if (dd !== dia) { dia = dd; html += '<div class="hist-dia">' + esc(dd) + '</div>'; }
      html += filaComb(c, h.extra);
    });
    caja.innerHTML = html;
  }
  // v440 — quitar de «Mis picks» (deslizando la fila), con «Deshacer» unos segundos
  async function quitarSeguidos(ids, volver) {
    ids = ids.filter(Boolean); if (!ids.length || !yo.user) return;
    ids.forEach((id) => (volver ? yo.seguidos.add(id) : yo.seguidos.delete(id)));
    if (window.SP) { window.SP.estado.deslizado = null; window.SP.pintar(); }
    const q = volver ? sb.from('seguidos').upsert(ids.map((pick) => ({ pick, usuario: yo.user.id })), { onConflict: 'usuario,pick', ignoreDuplicates: true })
      : sb.from('seguidos').delete().in('pick', ids).eq('usuario', yo.user.id);
    const res = await aTiempo(q, 6000, { error: 'tiempo' });
    if (res && res.error) { ids.forEach((id) => (volver ? yo.seguidos.delete(id) : yo.seguidos.add(id))); if (window.SP) window.SP.pintar(); avisoFlotante('No se pudo: revisa tu conexión.'); return; }
    if (!volver) avisoFlotante('Quitado de Mis picks', 'Deshacer', () => quitarSeguidos(ids, true));
  }
  function avisoFlotante(txt, boton, fn) {
    document.querySelectorAll('.aviso-flot').forEach((x) => x.remove());
    const d = document.createElement('div'); d.className = 'aviso-flot'; d.setAttribute('role', 'status');
    d.innerHTML = '<span>' + esc(txt) + '</span>' + (boton ? '<button>' + esc(boton) + '</button>' : '');
    if (boton) d.querySelector('button').addEventListener('click', () => { d.remove(); fn(); });
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 5000);
  }
  document.addEventListener('click', (e) => {
    const q = e.target.closest('[data-dejar]');
    if (q) { e.stopPropagation(); quitarSeguidos(q.dataset.dejar.split(',')); return; }
    const t = e.target.closest('[data-hist-rango]'); if (!t) return;
    rangoHist = Number(t.dataset.histRango); pintarHistorial($('mi-hist'));
  });
  function pintarCombinadas(caja) {
    const h = yo.hist || { combs: [], extra: {} };
    caja.dataset.pintada = '1';
    const vivas = h.combs.filter((c) => estadoCombVisto(c, h.extra) === 'pendiente');
    caja.innerHTML = vivas.length ? vivas.map((c) => filaComb(c, h.extra)).join('')
      : '<p class="tenue">' + (h.combs.length ? 'Ninguna en juego. ' : '') + 'Toca «➕ Combinada» en los picks que te gusten (de 2 a 20).</p>';
  }
  setInterval(() => {                                   // v452 — con el marcador en vivo, sin esperar al servidor
    const caja = $('mis-comb');
    if (caja && caja.offsetParent && yo.hist && !document.hidden) { pintarCombinadas(caja); pintarHistorial($('mi-hist')); }
  }, 20000);
  function filaComb(c, extra) {
    // v441 — «En juego» sólo si ya empezó alguno; si no, «Por jugar» con la hora. Cada pata abre su partido.
    // v452 — el usuario: «cuando ya se cumple algo, que se ponga en verde; no esperar al
    // final del partido (salvo que el pick sí lo necesite)». Cada pata usa lo mismo que la
    // pestaña Combinadas (`estadoVisto`): verde en cuanto se cumple, roja en cuanto ya no
    // puede, y al pitazo el resultado, sin esperar al servidor (que luego lo confirma).
    const visto = (p) => (p.id && pickDe(p.id) && window.SP && window.SP.estadoVisto ? window.SP.estadoVisto(pickDe(p.id)) : p.estado);
    const ps = c.patas.map((id) => { const p = pickDe(id) || extra[id] || { id: null }; return Object.assign({}, p, { _visto: visto(p) }); });
    const empezo = (p) => p.inicio && aFechaP(p.inicio) <= new Date();
    const yaRoja = c.estado === 'pendiente' && ps.some((p) => p._visto === 'roja');
    const yaVerde = c.estado === 'pendiente' && !yaRoja && ps.length && ps.every((p) => p._visto === 'verde' || p._visto === 'nula') && ps.some((p) => p._visto === 'verde');
    const hora = (p) => p.inicio ? new Intl.DateTimeFormat('es-MX', { timeZone: 'America/Mexico_City', hour: '2-digit', minute: '2-digit' }).format(aFechaP(p.inicio)) : '';
    const prox = ps.filter((p) => p.inicio && !empezo(p)).sort((a, b) => aFechaP(a.inicio) - aFechaP(b.inicio))[0];
    const chip = c.estado === 'verde' ? '<span class="et verde">' + OK() + ' Verde' + (c.premio ? ' · +' + c.premio + ' 🪙' : '') + '</span>' : c.estado === 'roja' ? '<span class="et roja">' + MAL() + ' Roja</span>'
      : c.estado === 'nula' ? '<span class="et">↩️ Nula</span>'
      : yaRoja ? '<span class="et roja" title="Al pitazo; el servidor lo confirma">' + MAL() + ' Roja</span>'
      : yaVerde ? '<span class="et verde" title="Al pitazo; el servidor lo confirma y paga">' + OK() + ' Verde</span>'
      : ps.some(empezo) ? '<span class="et vivo">🔴 En juego</span>' : '<span class="et">🕒 Por jugar' + (prox ? ' · ' + hora(prox) : '') + '</span>';
    // v443 — lo que puede ganar si acierta (la misma tabla que usa el servidor: una premiada por día)
    const pr = PREMIO(Number(c.cuota));
    const premio = c.estado === 'pendiente' && !yaRoja && (pr || !yaVerde) ? '<div class="comb-premio' + (pr ? '' : ' tenue') + '" title="Se paga una combinada premiada por día">' +
      (pr ? (yaVerde ? '🪙 Ganaste <b>+' + pr + '</b> · se acredita al confirmarse' : '🪙 Si acierta: <b>+' + pr + '</b>') : 'Sin premio: desde cuota 2,00') + '</div>' : '';
    return '<div class="tg-item ' + c.estado + '"><div class="fila"><span>🔗 ' + c.patas.length + ' picks · <b>' + Number(c.cuota).toFixed(2) + '</b></span>' + chip + '</div>' + premio +
      ps.map((p) => {
        const ico = p._visto === 'verde' ? '✅' : p._visto === 'roja' ? '❌' : p._visto === 'nula' ? '↩️' : empezo(p) ? '🔴' : '🕒';
        const txt = ico + ' ' + apuesta(p.id ? p : { apuesta: '—' }) + ' <span class="tenue">· ' + esc(p.partido || '') + (p.estado === 'pendiente' && !empezo(p) && p.inicio ? ' · ' + hora(p) : '') +
          (p.cuota ? ' · ' + Number(p.cuota).toFixed(2) : '') + '</span>' +
          (p.id && window.SP && window.SP.realDe && window.SP.realDe(p) ? '<small class="real">' + esc(window.SP.realDe(p)) + '</small>' : '');
        return pickDe(p.id) ? '<button class="tg-pata ir-partido" data-ficha="' + esc(p.id) + '">' + txt + ' <span class="ir">›</span></button>' : '<div class="tg-pata">' + txt + '</div>';
      }).join('') + '</div>';
  }
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-a-comb],[data-quitar-comb],[data-ver-boleto],[data-guardar-comb]');
    if (!t) return;
    if (t.dataset.aComb || t.dataset.quitarComb) {
      const id = t.dataset.aComb || t.dataset.quitarComb, ids = boleto();
      if (ids.includes(id)) guardarBoleto(ids.filter((x) => x !== id));
      else {
        const p = pickDe(id), otros = ids.map(pickDe).filter(Boolean);
        if (otros.some((o) => o.partido === (p && p.partido))) { avisoApp('Cada pick de tu combinada tiene que ser de un partido distinto.', 'aviso', 'Ya tienes un pick de ese partido'); return; }
        if (ids.length >= 20) { avisoApp('Una combinada lleva de 2 a 20 picks.', 'aviso', 'Ya tienes 20 picks'); return; }
        guardarBoleto(ids.concat(id)); yo.verBoleto = ids.length === 0 ? false : yo.verBoleto;
      }
      if (window.SP) window.SP.pintar();
      return;
    }
    if (t.hasAttribute('data-ver-boleto')) { yo.verBoleto = !yo.verBoleto; pintarBoleto(); return; }
    if (t.hasAttribute('data-guardar-comb')) {
      const listo = ocupado(t, 'Guardando…');
      const { error } = await sb.rpc('crear_combinada', { p_patas: boleto() });
      listo();
      if (error) { const m = $('boleto-msg'); if (m) m.textContent = error.message || 'No se pudo guardar.'; return; }
      guardarBoleto([]); yo.verBoleto = false; pintarBoleto();
      if (window.SP) window.SP.pintar();
      misCombinadas();
      avisoApp('La ves en «Mis picks». Si acierta, te damos tus monedas.', 'ok', 'Combinada guardada');
    }
  });

  // v426 — la contraseña nueva, al volver del enlace del correo
  function abrirNuevaContra() {
    if (!$('nueva-clave') || !$('nueva-clave').hidden) return;
    $('acceso').hidden = true;
    $('nc-1').value = ''; $('nc-2').value = ''; $('nc-msg').textContent = '';
    $('nueva-clave').hidden = false;
  }
  $('f-nueva-clave') && $('f-nueva-clave').addEventListener('submit', async (e) => {
    e.preventDefault();
    const c1 = $('nc-1').value, c2 = $('nc-2').value;
    if (contraDebil(c1)) { $('nc-msg').textContent = contraDebil(c1); return; }
    if (c1 !== c2) { $('nc-msg').textContent = 'Las contraseñas no coinciden.'; return; }
    const listo = ocupado(e.target.querySelector('button[type=submit]'), 'Guardando…');
    const { error } = await sb.auth.updateUser({ password: c1 });
    listo();
    if (error) { $('nc-msg').textContent = /session|sesi/i.test(error.message) ? 'El enlace venció. Pide otro desde «Olvidé mi contraseña».' : 'No se pudo guardar: ' + error.message; return; }
    $('nueva-clave').hidden = true;
    history.replaceState(null, '', location.pathname);
    refrescar();
    setTimeout(() => abrirMiCuenta('🔑 ¡Listo! Tu contraseña nueva quedó guardada.'), 400);
  });

  // v422 — «UN ALGORITMO QUE MUESTRE QUÉ PICK LE INTERESA AL USUARIO DE ACUERDO
  // A SUS TENDENCIAS». Las señales son suyas y se quedan en su sesión: lo que
  // sigue y lo que desbloquea (deporte, liga, nivel y la cuota que juega), y
  // los deportes y ligas que eligió. `app.js` (paraTi) puntúa con esto.
  let gustosDe = '';
  async function cargarGustos() {
    const ids = [...new Set([...yo.seguidos, ...Object.keys(yo.desbloqueados || {})])].slice(-200);
    const firma = ids.join(',');
    if (firma === gustosDe) return;
    gustosDe = firma;
    const g = { deporte: {}, liga: {}, nivel: {}, cuotas: [], n: 0 };
    if (ids.length) {
      const { data } = await sb.from('picks').select('id,deporte,liga,cuota,prob,elige,tipo').in('id', ids);
      (data || []).forEach((p) => {
        const nv = window.SP ? window.SP.nivel(p).n : '';
        g.deporte[p.deporte] = (g.deporte[p.deporte] || 0) + 1;
        if (p.liga) g.liga[p.liga] = (g.liga[p.liga] || 0) + 1;
        g.nivel[nv] = (g.nivel[nv] || 0) + 1;
        if (p.cuota) g.cuotas.push(Number(p.cuota));
        g.n++;
      });
    }
    yo.gustos = g;
  }
  function intereses() {
    const p = yo.perfil || {};
    let ligas = p.ligas;
    if (!Array.isArray(ligas)) { try { ligas = JSON.parse(localStorage.getItem('sharpicks-ligas-' + (yo.user && yo.user.id)) || '[]'); } catch (e) { ligas = []; } }
    return { deportes: new Set(p.deportes || []), ligas: new Set(ligas || []), gustos: yo.gustos || null };
  }
  // la pregunta de intereses: chips de deportes y de las ligas con más partidos
  const DEPORTES_INT = ['Fútbol', 'Tenis', 'NBA', 'NFL', 'NHL', 'MLB'];
  function abrirIntereses() {
    const it = intereses();
    const conteo = {};
    ((window.SP && window.SP.estado.picks) || []).concat((window.SP && window.SP.estado.analisis) || []).forEach((x) => {
      if (x.liga) conteo[x.liga] = (conteo[x.liga] || 0) + 1;
    });
    const ligas = [...new Set([...it.ligas, ...Object.entries(conteo).sort((a, b) => b[1] - a[1]).map(([l]) => l)])].slice(0, 30);
    const chip = (v, sel, k) => '<button type="button" class="chip' + (sel ? ' activa' : '') + '" data-int-' + k + '="' + esc(v) + '">' + esc(v) + '</button>';
    $('int-deportes').innerHTML = DEPORTES_INT.map((d) => chip(d, it.deportes.has(d), 'dep')).join('');
    $('int-ligas').innerHTML = ligas.map((l) => chip(l, it.ligas.has(l), 'liga')).join('');
    $('int-msg').textContent = '';
    $('intereses').hidden = false;
  }
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-int-dep],[data-int-liga],[data-guardar-intereses],[data-cerrar-intereses],[data-intereses]');
    if (!t) return;
    if (t.hasAttribute('data-intereses')) { $('micuenta').hidden = true; abrirIntereses(); return; }
    if (t.dataset.intDep != null || t.dataset.intLiga != null) { t.classList.toggle('activa'); return; }
    if (t.hasAttribute('data-cerrar-intereses')) {
      $('intereses').hidden = true;
      try { localStorage.setItem('sharpicks-intereses-no-' + (yo.user && yo.user.id), String(Date.now())); } catch (e2) { /* nada */ }
      return;
    }
    if (!yo.user) return;
    const deportes = [...document.querySelectorAll('[data-int-dep].activa')].map((b) => b.dataset.intDep);
    const ligas = [...document.querySelectorAll('[data-int-liga].activa')].map((b) => b.dataset.intLiga);
    t.disabled = true;
    let { error } = await sb.from('perfiles').update({ deportes, ligas }).eq('id', yo.user.id);
    if (error) ({ error } = await sb.from('perfiles').update({ deportes }).eq('id', yo.user.id));   // sin la columna de ligas
    try { localStorage.setItem('sharpicks-ligas-' + yo.user.id, JSON.stringify(ligas)); } catch (e2) { /* nada */ }
    t.disabled = false;
    if (error) { $('int-msg').textContent = 'No se pudo guardar. Intenta de nuevo.'; return; }
    yo.perfil = Object.assign({}, yo.perfil, { deportes, ligas }); guardarPerfil(yo.perfil);
    $('intereses').hidden = true;
    if (window.SP) window.SP.pintar();
  });

  // v417 — LOS PLANES CON SUS NÚMEROS REALES. El usuario: «que vengan los
  // mejores números del historial… los diamantes con sus números reales, y de
  // la IA únicamente donde mejor acertamos». Todo sale de la base (30 días,
  // las vistas `historial_niveles`, `ia_medicion` e `ia_aciertos`); con poca
  // muestra (menos de 30) no se presume nada.
  async function numerosPlanes() {
    if (!sb || !$('plan-vip')) return;
    const [nv, med, ac] = await Promise.all([
      sb.from('historial_niveles').select('*'), sb.from('ia_medicion').select('*'), sb.from('ia_aciertos').select('*').maybeSingle()]);
    const N = {}; ((nv && nv.data) || []).forEach((x) => { N[x.nivel] = x; });
    const linea = (ico, nombre, v, r) => (v + r >= 30 ? '<li class="num-real">' + ico + ' ' + nombre + ': <b>' + Math.round(100 * v / (v + r)) + ' %</b> <small>✅ ' + v + ' ❌ ' + r + '</small></li>' : '');
    // sólo los niveles que de verdad presumen (75 %+): «los mejores números»
    const nivel = (n, ico) => (N[n] && N[n].verdes / Math.max(1, N[n].verdes + N[n].rojas) >= 0.75 ? linea(ico, n, N[n].verdes, N[n].rojas) : '');
    const pon = (id, h) => { const c = $(id); if (c) c.innerHTML = h ? '<ul class="numeros">' + h + '</ul><small class="tenue">Últimos 30 días, verdes y rojas reales.</small>' : ''; };
    // v420 — 💰 Cuota alta acierta ~55 % a cuota ~2,3: lo que presume es lo que GANA
    const gana = (n, ico) => (N[n] && N[n].gana_por_100 > 0 && N[n].verdes + N[n].rojas >= 30
      ? '<li class="num-real">' + ico + ' ' + n + ': <b>+' + Math.round(N[n].gana_por_100) + ' por cada $100</b> <small>✅ ' + N[n].verdes + ' ❌ ' + N[n].rojas + '</small></li>' : '');
    pon('numeros-gratis', nivel('Oro', '🥇'));
    pon('numeros-monedas', nivel('Diamante', '💎') + nivel('Platino', '🔷') + nivel('Plata', '🥈') + gana('Cuota alta', '💰'));
    // la tabla de precios, de la base (lo que cobra `precio_pick`, nunca otra cosa)
    const tp = $('tabla-precios');
    if (tp && (yo.bandas || []).length) tp.innerHTML = '<tr><th>Cuota del pick</th><th>Cuesta</th></tr>' + yo.bandas.map((b) =>
      '<tr><td>' + Number(b.desde).toFixed(2) + (Number(b.hasta) >= 50 ? ' o más' : ' – ' + (Number(b.hasta) - 0.01).toFixed(2)) + '</td><td>' + b.monedas + ' 🪙</td></tr>').join('');
    // la IA: sólo lo mejor (la apuesta que metería, en su banda más alta con 30+ partidos, y su «a favor»)
    const DEP = { 'Fútbol': '⚽', Tenis: '🎾', NBA: '🏀', NFL: '🏈', NHL: '🏒', MLB: '⚾' };
    const mejores = ((med && med.data) || []).filter((x) => x.que === 'mejor' && x.total >= 30)
      .sort((a, b) => b.ok / b.total - a.ok / a.total).slice(0, 2)
      .map((x) => linea('🧠', 'IA, lo que metería ' + (DEP[x.deporte] || '') + ' (confianza ' + x.banda + ')', x.ok, x.total - x.ok)).join('');
    const a = ac && ac.data;
    const favor = a ? linea('🤖', 'IA «a favor» de nuestro pick', Number(a.favor_bien || 0), Number(a.favor_mal || 0)) : '';
    // v420 — «muestra también el % del ganador que predice la IA» (sin presumir: se dice tal cual)
    const ganador = a ? linea('🏆', 'IA, el ganador del partido', Number(a.resultado_ok || 0), Number(a.resultado_mal || 0)) : '';
    pon('numeros-vip', nivel('Diamante', '💎') + nivel('Platino', '🔷') + nivel('Plata', '🥈') + mejores + favor + ganador);
  }
  // v453 — «LO QUE DIJIMOS VS LO QUE SALIÓ»: por cada grupo de probabilidad, cuánto
  // salió de verdad (con TODOS los picks terminados, rojas incluidas)
  async function calibracionPicks() {
    const caja = $('calibracion'); if (!caja || !sb) return;
    const { data, error } = await aTiempo(sb.from('calibracion_picks').select('*').order('orden'), 8000, { data: null, error: true });
    if (error || !data || !data.length) { caja.innerHTML = '<p class="tenue">Todavía no hay suficientes picks terminados.</p>'; return; }
    const n = data.reduce((a, x) => a + x.n, 0), desde = data.map((x) => x.desde).sort()[0];
    caja.innerHTML = '<div class="calib">' + data.map((x) => '<div class="calib-fila"><span class="calib-b">' + esc(x.banda) + '</span>' +
      '<div class="calib-barra"><i class="dijo" style="left:' + x.dijimos + '%"></i><b style="width:' + x.salio + '%"></b></div>' +
      '<span class="calib-n">dijimos <b>' + x.dijimos + ' %</b> · salió <b>' + x.salio + ' %</b><small>' + x.n + ' picks</small></span></div>').join('') + '</div>' +
      '<p class="tenue chico">' + n + ' picks terminados desde el ' + esc(String(desde || '').slice(0, 10)) + ', rojas incluidas. La rayita es lo que dijimos; la barra, lo que salió.</p>';
  }
  async function historial() {
    calibracionPicks();
    const caja = $('historial'); if (!caja || !sb) return;
    const { data, error } = await sb.from('historial').select('*').limit(30);
    if (error) {
      console.error('[sharpicks] no se pudo consultar el historial', error);
      caja.innerHTML = '<p class="aviso">No se pudo consultar el historial. No podemos confirmar los resultados; reintenta en un momento.</p>';
      const iaError = $('ia-hist'); if (iaError) iaError.innerHTML = '<p class="aviso">No se pudieron consultar las mediciones de la IA desde Supabase.</p>';
      const tgError = $('tg-hist'); if (tgError) tgError.innerHTML = '<p class="aviso">No se pudo consultar lo publicado en Telegram.</p>';
      return;
    }
    const filas = (data || []).filter((d) => d.verdes + d.rojas + (d.verdes_error || 0) + (d.rojas_error || 0) > 0);
    if (!filas.length) caja.innerHTML = '<p class="tenue">Todavía no hay resultados liquidados para mostrar.</p>';
    const tv = filas.reduce((s, d) => s + (Number(d.verdes) || 0), 0), tr = filas.reduce((s, d) => s + (Number(d.rojas) || 0), 0);
    const ev = filas.reduce((s, d) => s + d.verdes_elige, 0), er = filas.reduce((s, d) => s + d.rojas_elige, 0);
    const xv = filas.reduce((s, d) => s + (d.verdes_error || 0), 0), xr = filas.reduce((s, d) => s + (d.rojas_error || 0), 0);
    const { data: ia, error: iaError } = await sb.from('ia_aciertos').select('*').maybeSingle();
    if (iaError) console.error('[sharpicks] no se pudo consultar ia_aciertos', iaError);
    const { data: med, error: medError } = await sb.from('ia_medicion').select('*');
    const p100 = (a, b) => (Number(a || 0) + Number(b || 0) ? Math.round(100 * Number(a || 0) / (Number(a || 0) + Number(b || 0))) + ' %' : '—');
    if (medError) console.error('[sharpicks] no se pudo consultar la calibración de la IA', medError);
    if (filas.length) caja.innerHTML = '<div class="num">✅ ' + tv + ' ❌ ' + tr + ' <span class="pct">' + p100(tv, tr) + '</span></div>' +
      '<div class="sub">💎 Diamante: ✅ ' + ev + ' ❌ ' + er + (ev + er ? ' · ' + Math.round(100 * ev / (ev + er)) + ' %' : '') + '</div>' +
      (xv + xr ? '<div class="sub">💰 Cuota alta (errores de cuota): ✅ ' + xv + ' ❌ ' + xr + ' · ' + p100(xv, xr) + '</div>' : '') +
      ''; caja.innerHTML += '';
    // v391 — el bloque de la IA sale SIEMPRE (aunque aún no haya partidos terminados)
    const iaCaja = $('ia-hist');
    if (iaCaja) iaCaja.innerHTML = iaError ? '<p class="aviso">No se pudieron consultar las mediciones de la IA. Reintenta en un momento.</p>' : !ia ? '<p class="tenue">Sin datos de la IA todavía.</p>' :
      '<div class="ia-fila"><span>Partidos analizados</span><b>' + (ia.analizados || 0) + '</b><small>' + (ia.pendientes || 0) + ' esperando resultado</small></div>' +
      '<div class="ia-fila"><span>🤖 Acierta el ganador</span><b>✅ ' + ia.resultado_ok + ' ❌ ' + ia.resultado_mal + '</b><small>' + p100(ia.resultado_ok, ia.resultado_mal) + '</small></div>' +
      '<div class="ia-fila"><span>✅ Cuando dijo «a favor», el pick salió</span><b>' + ia.favor_bien + ' de ' + (ia.favor_bien + ia.favor_mal) + '</b><small>' + p100(ia.favor_bien, ia.favor_mal) + '</small></div>' +
      mejorIA(med) +
      '<p class="tenue chico">La IA es experimental y se mide aparte: nuestros picks no dependen de ella.</p>';
    // v420 — el historial POR DEPORTE (el modelo) y, al lado, lo mejor de la IA en ese deporte
    porDeporte(med);
    // v421 — sólo los días con picks liquidados (del 9 al 14-oct sólo se guardaban los 💰:
    // salían «0-0» y parecía que no hubo nada; los 💰 siguen sumados arriba)
    const conPicks = filas.filter((d) => (Number(d.verdes) || 0) + (Number(d.rojas) || 0) > 0);
    if (conPicks.length) caja.innerHTML +=
      '<table class="tabla"><tr><th>Día</th><th>✅</th><th>❌</th><th>%</th><th>💎</th><th>💰</th></tr>' +
      conPicks.map((d) => '<tr><td>' + esc(d.fecha) + '</td><td>' + d.verdes + '</td><td>' + d.rojas + '</td><td>' +
        esc(p100(d.verdes, d.rojas).replace(' %', '')) + '</td><td>' + d.verdes_elige + '-' + d.rojas_elige +
        '</td><td>' + (d.verdes_error || 0) + '-' + (d.rojas_error || 0) + '</td></tr>').join('') + '</table>';
  }

  // v399 — «lo que metería la IA» con ✅/❌, y si sus probabilidades son
  // honestas: cuando dijo 70-80 %, ¿cuánto salió de verdad? (`ia_medicion`)
  function filaMejor(med) {
    const xs = (med || []).filter((m) => m.que === 'mejor');
    const ok = xs.reduce((s, m) => s + m.ok, 0), tot = xs.reduce((s, m) => s + m.total, 0);
    return '<div class="ia-fila"><span>🧠 Lo que metería la IA</span><b>✅ ' + ok + ' ❌ ' + (tot - ok) + '</b><small>' +
      (tot ? Math.round(100 * ok / tot) + ' %' : '—') + '</small></div>';
  }
  // v420 — «es mucho texto: deja sólo lo mejor, nivelado entre porcentaje y
  // cantidad (el hándicap de 80 %+ con n=2 no cuenta)». Cada predicción en su
  // mejor banda, ordenadas por el piso de confianza de Wilson (95 %): premia
  // un acierto alto CON muestra. Sólo con 20+ partidos y si salió 65 %+.
  function wilson(ok, n) {
    if (!n) return 0;
    const z = 1.96, p = ok / n;
    return (p + z * z / (2 * n) - z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n);
  }
  function mejorIA(med) {
    const junto = {};
    (med || []).filter((m) => m.total > 0).forEach((m) => {
      const k = m.que + '|' + m.banda;
      junto[k] = junto[k] || { que: m.que, banda: m.banda, ok: 0, total: 0 };
      junto[k].ok += m.ok; junto[k].total += m.total;
    });
    const mejor = {};
    Object.values(junto).filter((m) => m.total >= 20 && m.ok / m.total >= 0.65).forEach((m) => {
      m.lb = wilson(m.ok, m.total);
      if (!mejor[m.que] || m.lb > mejor[m.que].lb) mejor[m.que] = m;
    });
    const xs = Object.values(mejor).sort((a, b) => b.lb - a.lb).slice(0, 5);
    if (!xs.length) return '';
    const N = { goles: '⚽ Goles 2.5', ambos: '🎯 Ambos anotan', corners: '🚩 Córners', tarjetas: '🟨 Tarjetas', total: '📊 Total', handicap: '⚖️ Hándicap', mejor: '🧠 Lo que metería' };
    return '<div class="ctx-tit">🏆 Donde mejor acierta la IA</div>' + xs.map((m) =>
      '<div class="ia-fila"><span>' + (N[m.que] || esc(m.que)) + ' <small>(confianza ' + esc(m.banda) + ')</small></span><b>✅ ' + m.ok + ' ❌ ' + (m.total - m.ok) + '</b><small>' + Math.round(100 * m.ok / m.total) + ' %</small></div>').join('');
  }
  async function porDeporte(med) {
    const caja = $('dep-hist'); if (!caja || !sb) return;
    const { data, error } = await sb.from('historial_deportes').select('*');
    if (error || !(data || []).length) { caja.innerHTML = ''; return; }
    const ICO = new Proxy({}, { get: (_, d) => (window.SP && window.SP.icoDep ? window.SP.icoDep(d) : '') });
    const ia = {};
    (med || []).filter((m) => m.que === 'mejor').forEach((m) => { const x = ia[m.deporte] = ia[m.deporte] || [0, 0]; x[0] += m.ok; x[1] += m.total; });
    caja.innerHTML = '<table class="tabla"><tr><th>Deporte</th><th>Modelo</th><th>%</th><th>🧠 IA</th></tr>' +
      data.filter((d) => d.verdes + d.rojas >= 10).sort((a, b) => (b.verdes + b.rojas) - (a.verdes + a.rojas)).map((d) => {
        const n = d.verdes + d.rojas, x = ia[d.deporte];
        return '<tr><td>' + (ICO[d.deporte] || '•') + ' ' + esc(d.deporte) + '</td><td>✅ ' + d.verdes + ' ❌ ' + d.rojas + '</td><td><b>' + Math.round(100 * d.verdes / n) + ' %</b></td><td>' +
          (x && x[1] >= 20 ? Math.round(100 * x[0] / x[1]) + ' % <small>(' + x[1] + ')</small>' : '—') + '</td></tr>';
      }).join('') + '</table><p class="tenue chico">Últimos 30 días. «🧠 IA»: lo que metería la IA en ese deporte (con 20+ partidos).</p>';
  }
  function calibracion(med) {
    // v407 — una fila por predicción y banda, sumando los deportes
    const junto = {};
    (med || []).filter((m) => m.total > 0).forEach((m) => {
      const k = m.que + '|' + m.banda;
      junto[k] = junto[k] || { que: m.que, banda: m.banda, ok: 0, total: 0 };
      junto[k].ok += m.ok; junto[k].total += m.total;
    });
    const xs = Object.values(junto);
    if (!xs.length) return '<p class="tenue chico">¿Sus probabilidades son honestas? Aquí se va a ver: cuando dice 70 %, cuánto sale de verdad (aún sin partidos calificados).</p>';
    const N = { goles: '⚽ Goles 2.5', ambos: '🎯 Ambos anotan', corners: '🚩 Córners', tarjetas: '🟨 Tarjetas', total: '📊 Total', handicap: '⚖️ Hándicap', mejor: '🧠 Lo que metería' };
    const orden = ['50-60 %', '60-70 %', '70-80 %', '80 % o más'];
    xs.sort((a, b) => Object.keys(N).indexOf(a.que) - Object.keys(N).indexOf(b.que) || orden.indexOf(a.banda) - orden.indexOf(b.banda));
    return '<div class="ctx-tit">¿Sus probabilidades son honestas?</div><table class="tabla"><tr><th>Predicción</th><th>Dijo</th><th>Salió</th><th>N</th></tr>' +
      xs.map((m) => '<tr><td>' + (N[m.que] || esc(m.que)) + '</td><td>' + esc(m.banda) + '</td><td>' + Math.round(100 * m.ok / m.total) + ' %</td><td>' + m.total + '</td></tr>').join('') +
      '</table><p class="tenue chico">Si «salió» queda muy por debajo de «dijo», la IA promete de más.</p>';
  }

  // ---------- v380: LO QUE MANDAMOS POR TELEGRAM, CON SU RESULTADO ----------
  // El usuario: «saber de los picks que mandamos gratis y VIP, combinados e
  // individuales, cuáles salieron verdes; la combinada, verde hasta que
  // termine el último partido». De `telegram_publicados` (lo enviado) y el
  // estado de cada pick en la base; la combinada es ❌ en cuanto falla una
  // pata, ✅ cuando todas terminan bien, y ⏳ «1 de 2 ✅» mientras tanto.
  const tg = { canal: 'gratis', items: [] };
  function estadoItem(ps) {
    if (ps.some((p) => p.estado === 'roja')) return 'roja';
    if (ps.every((p) => p.estado === 'verde' || p.estado === 'nula') && ps.some((p) => p.estado === 'verde')) return 'verde';
    return 'pendiente';
  }
  async function telegramHist() {
    const caja = $('tg-hist'); if (!caja || !sb) return;
    const desde = new Date(Date.now() - 30 * 864e5).toISOString();
    const { data } = await sb.from('telegram_publicados').select('*').gte('enviado', desde).order('enviado', { ascending: false }).limit(1000);
    const filas = data || [];
    const ids = [...new Set(filas.flatMap((f) => f.clave.startsWith('comb:') ? f.clave.slice(5).split('+') : [f.clave]))];
    const picks = {};
    for (let i = 0; i < ids.length; i += 100) {
      const r = await sb.from('picks').select('id,partido,apuesta,cuota,estado,marcador,inicio,prob').in('id', ids.slice(i, i + 100));
      (r.data || []).forEach((p) => { picks[p.id] = p; });
    }
    tg.items = filas.map((f) => {
      const ps = (f.clave.startsWith('comb:') ? f.clave.slice(5).split('+') : [f.clave]).map((i) => picks[i]).filter(Boolean);
      return { canal: f.canal, enviado: f.enviado, comb: f.clave.startsWith('comb:'), ps, est: ps.length ? estadoItem(ps) : 'pendiente' };
    }).filter((x) => x.ps.length);
    pintarTg();
  }
  function pintarTg() {
    const caja = $('tg-hist'); if (!caja) return;
    const it = tg.items.filter((x) => x.canal === tg.canal);
    const v = it.filter((x) => x.est === 'verde').length, r = it.filter((x) => x.est === 'roja').length;
    const comb = it.filter((x) => x.comb), cv = comb.filter((x) => x.est === 'verde').length, cr = comb.filter((x) => x.est === 'roja').length;
    const tab = (c, t) => '<button class="seg' + (tg.canal === c ? ' activa' : '') + '" data-tg-canal="' + c + '">' + t + '</button>';
    let h = '<div class="segmentos dos">' + tab('gratis', '📢 Gratis') + tab('vip', '💎 VIP') + '</div>';
    if (!it.length) { caja.innerHTML = h + '<p class="tenue">Todavía no hay envíos en este canal.</p>'; return; }
    h += '<div class="num">✅ ' + v + ' ❌ ' + r + (v + r ? ' <span class="pct">' + Math.round(100 * v / (v + r)) + ' %</span>' : '') + '</div>' +
      (comb.length ? '<div class="sub">🔗 Combinadas: ✅ ' + cv + ' ❌ ' + cr + ' · ⏳ ' + (comb.length - cv - cr) + '</div>' : '') +
      '<div class="tg-items">' + it.slice(0, 40).map((x) => {
        const hechas = x.ps.filter((p) => p.estado === 'verde').length;
        const chip = x.est === 'verde' ? '<span class="et verde">' + OK() + ' Verde</span>' : x.est === 'roja' ? '<span class="et roja">' + MAL() + ' Roja</span>'
          : '<span class="et vivo">⏳ ' + (x.comb ? hechas + ' de ' + x.ps.length + ' ✅' : 'Pendiente') + '</span>';
        const cuota = x.ps.reduce((s, p) => s * Number(p.cuota || 1), 1);
        return '<div class="tg-item ' + x.est + '"><div class="fila"><span>' + (x.comb ? '🔗 Combinada' : (tg.canal === 'vip' ? '💎 Pick' : '🎯 Pick del día')) +
          ' · <b>' + cuota.toFixed(2) + '</b></span>' + chip + '</div>' +
          x.ps.map((p) => '<div class="tg-pata">' + (p.estado === 'verde' ? '✅' : p.estado === 'roja' ? '❌' : '⏳') + ' ' + esc(p.apuesta) +
            ' <span class="tenue">· ' + esc(p.partido) + (p.marcador ? ' ' + esc(p.marcador) : '') + '</span></div>').join('') + '</div>';
      }).join('') + '</div>';
    caja.innerHTML = h;
  }
  document.addEventListener('click', (e) => { const b = e.target.closest('[data-tg-canal]'); if (b) { tg.canal = b.dataset.tgCanal; pintarTg(); } });

  // ---------- Telegram ----------
  // v383 — el enlace del VIP ya no es público: se da en «Mi cuenta» a quien le toca
  function telegram() {
    const c = $('telegram'); if (!c) return;
    const g = C.TELEGRAM_GRATIS;
    c.innerHTML = (g ? '<a class="tg" href="' + esc(g) + '" target="_blank" rel="noopener">📢 Canal gratis de Telegram</a>' : '') +
      '<button class="tg vip" data-mi-cuenta>💎 Grupo VIP de Telegram</button>';
  }

  if (sb) {
    // v425 — «iniciar sesión tarda ~10 s». Supabase ESPERA a lo que haga este
    // aviso antes de terminar el inicio de sesión, y aquí se recargaba todo
    // (perfil, desbloqueos, la IA, las tendencias). Ahora se recarga detrás.
    sb.auth.onAuthStateChange((evento) => {
      if (evento === 'PASSWORD_RECOVERY') setTimeout(abrirNuevaContra, 300);      // v426
      setTimeout(refrescar, 0);
    });
    if (DESDE_RECUPERACION) setTimeout(abrirNuevaContra, 1500);
    listo = refrescar();
    // al volver a la app (otra pestaña, Stripe, el celular en reposo) se pone al día
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refrescar(); });
    historial();
    telegramHist();
    numerosPlanes();
    setInterval(() => { historial(); telegramHist(); }, 10 * 60 * 1000);
  }
  telegram();
})();
