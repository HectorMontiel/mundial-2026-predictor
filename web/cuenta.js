// v379 — SharPicks: la CUENTA del usuario (Supabase Auth), «Mis picks»,
// monedas, desbloquear con «No Win, No Pay» y el historial público.
// Lo que manda (saldo, quién ve un pick premium, la devolución si falla) lo
// decide la BASE (`negocio.sql`), no esta página: aquí sólo se pide y se pinta.
(function () {
  const C = window.CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
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
  window.SPX = { yo, sb, extra, apuesta, filtrarMios, refrescar, extraComb };

  // ---------- precios (de la base; 0 = gratis en el lanzamiento) ----------
  // v389 — el precio de un pick premium depende de su CUOTA (tabla `precios_cuota`);
  // 🥇 y 🥈 son gratis; el administrador no paga. Lo que cobra de verdad lo
  // decide la base (`precio_pick`); esto sólo lo enseña.
  function precio(p) {
    if (yo.perfil && yo.perfil.admin) return 0;
    const n = window.SP.nivel(p).n;
    if (!p._forzar && !['Diamante', 'Platino', 'Cuota alta'].includes(n)) return 0;
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
    if (p.premium && !yo.desbloqueados[p.id]) {
      const pr = precio(p);
      // v381 — lanzamiento: con cuenta (gratis) se ven todos; sin cuenta, candado
      if (!yo.user) h += '<button class="desbloquear" data-entrar>🔓 Entra gratis y desbloquéalo</button>';
      else h += '<button class="desbloquear" data-desbloquear="' + esc(p.id) + '">' +
        (pr ? 'Desbloquear por ' + pr + ' 🪙' : 'Desbloquear gratis') + '</button>' +
        '<small class="nwnp">Si sale roja, se te devuelve</small>';
    }
    const sigo = yo.seguidos.has(p.id);
    h += '<button class="seguir' + (sigo ? ' si' : '') + '" data-seguir="' + esc(p.id) + '">' + (sigo ? '★ Siguiendo' : '☆ Seguir') + '</button>';
    const n = yo.conteo[p.id];
    if (n) h += '<span class="siguen">👥 ' + n + '</span>';
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

  // ---------- sesión ----------
  const aTiempo = (p, ms, porDefecto) => Promise.race([Promise.resolve(p).catch(() => porDefecto),
    new Promise((r) => setTimeout(() => r(porDefecto), ms || 5000))]);
  async function refrescar() {
    if (!sb) return;
    try {
      const { data } = await aTiempo(sb.auth.getSession(), 5000, { data: { session: yo.user ? { user: yo.user } : null } });
      yo.user = data && data.session ? data.session.user : null;
    } catch (e) { /* se queda la sesión que había */ }
    const tareas = [
      sb.from('ajustes').select('clave,valor').then(({ data }) => { (data || []).forEach((x) => { yo.precios[x.clave] = x.valor; }); }),
      sb.from('precios_cuota').select('*').order('desde').then(({ data }) => { yo.bandas = data || []; }),
      sb.from('paquetes').select('*').order('orden').then(({ data }) => { yo.paquetes = data || []; }),
      sb.from('seguidores').select('pick,n').then(({ data }) => { yo.conteo = {}; (data || []).forEach((x) => { yo.conteo[x.pick] = x.n; }); }),
    ];
    if (yo.user) {
      tareas.push(sb.from('perfiles').select('*').eq('id', yo.user.id).maybeSingle().then(({ data }) => { yo.perfil = data; }));
      tareas.push(sb.from('seguidos').select('pick').then(({ data }) => { yo.seguidos = new Set((data || []).map((x) => x.pick)); }));
      tareas.push(sb.from('ia_analisis').select('*').gte('fecha', new Date(Date.now() - 2 * 864e5).toISOString().slice(0, 10)).limit(2000)
        .then(({ data }) => { yo.ia = {}; (data || []).forEach((x) => { yo.ia[x.partido] = x; }); }));
      tareas.push(sb.from('suscripciones').select('*').eq('usuario', yo.user.id).order('actualizado', { ascending: false }).limit(10)
        .then(({ data }) => { yo.subs = data || []; }));
      tareas.push(sb.from('picks_premium').select('id,apuesta').then(({ data }) => { yo.desbloqueados = {}; (data || []).forEach((x) => { yo.desbloqueados[x.id] = x.apuesta; }); }));
    } else { yo.perfil = null; yo.seguidos = new Set(); yo.desbloqueados = {}; yo.subs = []; }
    await Promise.all(tareas.map((t) => aTiempo(t, 6000, null)));
    try { avisoRenovacion(); } catch (e) { /* el aviso nunca tumba la página */ }
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
    const nom = (yo.perfil && (yo.perfil.usuario || yo.perfil.nombre)) || String(yo.user.email || 'Mi cuenta').split('@')[0];
    c.innerHTML = '<span class="saldo" title="Tus monedas">🪙 ' + (esAdmin() ? '∞' : ((yo.perfil && yo.perfil.monedas) || 0)) + '</span>' +
      (esVip() ? '<span class="et nivel diamante">' + (esAdmin() ? 'ADMIN' : 'VIP') + '</span>' : '') +
      '<button class="entrar" data-mi-cuenta>' + esc(nom) + ' ▾</button>';
    // con Google no se eligió usuario: se pide una vez
    if (yo.perfil && !yo.perfil.usuario && $('elegir').hidden) $('elegir').hidden = false;
  }

  function abrirAcceso(msg, modo) {
    verModo(modo || 'entrar');
    $('acceso-msg').textContent = msg || '';
    const g = document.querySelector('[data-google]'); if (g) g.hidden = !C.LOGIN_GOOGLE;
    $('acceso').hidden = false;
  }
  function verModo(m) {
    document.querySelectorAll('[data-modo]').forEach((x) => { x.hidden = x.dataset.modo !== m; });
    document.querySelectorAll('[data-ir-modo]').forEach((x) => x.classList.toggle('activa', x.dataset.irModo === m));
  }

  async function entrarConUsuario(u, contra) {
    if (u.includes('@')) {
      const { error } = await sb.auth.signInWithPassword({ email: u, password: contra });
      return error ? 'Correo o contraseña incorrectos.' : '';
    }
    const r = await fetch(FN + 'entrar', { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: C.SUPABASE_ANON_KEY },
      body: JSON.stringify({ usuario: u, contrasena: contra }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.access_token) return d.error || 'No se pudo entrar.';
    const { error } = await sb.auth.setSession({ access_token: d.access_token, refresh_token: d.refresh_token });
    return error ? 'No se pudo entrar.' : '';
  }

  async function abrirMiCuenta(msg) {
    if (!yo.user) { abrirAcceso(); return; }
    const p = yo.perfil || {};
    // se abre YA con lo básico (y «Cerrar sesión»); lo que tarda se agrega después
    if ($('micuenta').hidden) {
      $('micuenta-cuerpo').innerHTML = '<button class="cerrar" data-cerrar-cuenta>✕</button><h3>Mi cuenta</h3>' +
        '<div class="cuenta-cab"><b>@' + esc(p.usuario || '—') + '</b><span class="tenue">' + esc(yo.user.email || '') + '</span></div>' +
        '<p class="tenue">Cargando…</p><button class="salir" data-salir>Cerrar sesión</button>';
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
        '</div><p class="tenue chico">💎 🔷 💰 cuestan de 5 a 25 🪙 según su cuota. Si el pick sale rojo, te regresamos tus monedas solas.</p></div>';
    }
    h += '<div class="caja"><div class="tit">👤 Nombre de usuario</div><div class="fila-form"><input id="mi-usuario" value="' + esc(p.usuario || '') +
      '" placeholder="3-20 letras, números, _ o ." autocapitalize="off"><button class="ver" data-mi-usuario>Guardar</button></div></div>';
    h += '<div class="caja"><div class="tit">🎁 Canjear código</div><div class="fila-form"><input id="codigo" placeholder="SHARP-XXXX-XXXX" autocomplete="off"><button class="ver" data-canjear>Canjear</button></div></div>' +
      '<div class="caja"><div class="tit">🔑 ' + (yo.user.app_metadata && yo.user.app_metadata.provider === 'google' ? 'Crear contraseña (para entrar con tu usuario)' : 'Cambiar contraseña') + '</div>' +
      '<div class="fila-form"><input type="password" id="nueva-contra" placeholder="Mínimo 8 caracteres" autocomplete="new-password"><button class="ver" data-contra>Guardar</button></div></div>' +
      '<button class="salir" data-salir>Cerrar sesión</button>';
    $('micuenta-cuerpo').innerHTML = h;
    $('micuenta').hidden = false;
  }

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
      $('micuenta').hidden = true;
      await aTiempo(sb.auth.signOut(), 4000, null);
      try { Object.keys(localStorage).filter((k) => k.startsWith('sb-')).forEach((k) => localStorage.removeItem(k)); } catch (e) {}
      yo.user = null; yo.perfil = null;
      pintarCabecera(); await refrescar();
      return;
    }
    if (t.hasAttribute('data-enlace')) {
      const correo = $('e-usuario').value.trim();
      if (!correo.includes('@')) { $('acceso-msg').textContent = 'Escribe tu correo arriba para mandarte el enlace.'; return; }
      const { error } = await sb.auth.signInWithOtp({ email: correo, options: { emailRedirectTo: location.origin + location.pathname } });
      $('acceso-msg').textContent = error ? 'No se pudo enviar: ' + error.message : 'Listo: revisa tu correo (también «spam»).';
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
      if (t.dataset.sus === 'cancelar' && !confirm('¿Cancelar la renovación automática? Sigues siendo VIP hasta el final de lo ya pagado.')) return;
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
      if (c1.length < 8) { abrirMiCuenta('La contraseña debe tener al menos 8 caracteres.'); return; }
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
      const id = t.dataset.seguir, sigo = yo.seguidos.has(id);
      // v391 — la estrella cambia YA; la base se actualiza detrás (si falla, se regresa)
      if (sigo) { yo.seguidos.delete(id); yo.conteo[id] = Math.max(0, (yo.conteo[id] || 1) - 1); }
      else { yo.seguidos.add(id); yo.conteo[id] = (yo.conteo[id] || 0) + 1; }
      t.classList.toggle('si', !sigo); t.textContent = !sigo ? '★ Siguiendo' : '☆ Seguir';
      const q = sigo ? sb.from('seguidos').delete().eq('pick', id) : sb.from('seguidos').insert({ pick: id });
      aTiempo(q, 6000, { error: 'tiempo' }).then((res) => {
        if (res && res.error && res.error !== 'tiempo') {
          if (sigo) yo.seguidos.add(id); else yo.seguidos.delete(id);
          window.SP.pintar();
        }
      });
      return;
    }
    if (t.dataset.desbComb) {
      t.disabled = true;
      const { data, error } = await sb.rpc('desbloquear_combinada', { comb_id: t.dataset.desbComb });
      if (error || data !== 'ok') { alert(data === 'sin monedas' ? 'No te alcanzan las monedas.' : data === 'ya empezó' ? 'Uno de sus partidos ya empezó.' : 'No se pudo desbloquear. Intenta de nuevo.'); t.disabled = false; return; }
      await refrescar();
      return;
    }
    if (t.dataset.desbloquear) {
      t.disabled = true;
      const { data, error } = await sb.rpc('desbloquear', { pick_id: t.dataset.desbloquear });
      if (error || data !== 'ok') { alert(data === 'sin monedas' ? 'No te alcanzan las monedas.' : data === 'ya empezó' ? 'Ese partido ya empezó.' : 'No se pudo desbloquear. Intenta de nuevo.'); t.disabled = false; return; }
      await refrescar();
    }
  });

  // entrar con usuario (o correo) y contraseña
  $('f-entrar') && $('f-entrar').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = $('e-usuario').value.trim(), c1 = $('e-contra').value;
    if (!u || !c1) { $('acceso-msg').textContent = 'Escribe tu usuario y tu contraseña.'; return; }
    $('acceso-msg').textContent = 'Entrando…';
    const err = await entrarConUsuario(u, c1);
    if (err) { $('acceso-msg').textContent = err; return; }
    $('acceso').hidden = true;
    await refrescar();
  });
  // crear cuenta: usuario + correo + contraseña
  $('f-crear') && $('f-crear').addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = $('c-usuario').value.trim(), correo = $('c-correo').value.trim(), c1 = $('c-contra').value, c2 = $('c-contra2').value;
    const msg = (x) => { $('acceso-msg').textContent = x; };
    if (!RE_USUARIO.test(u)) return msg('El usuario: de 3 a 20 letras, números, «_» o «.», sin espacios.');
    if (c1.length < 8) return msg('La contraseña debe tener al menos 8 caracteres.');
    if (c1 !== c2) return msg('Las contraseñas no coinciden.');
    msg('Creando tu cuenta…');
    const { data: libre } = await sb.rpc('usuario_libre', { u });
    if (!libre) return msg('Ese usuario ya existe. Prueba otro.');
    const { data, error } = await sb.auth.signUp({ email: correo, password: c1, options: { data: { usuario: u } } });
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
    setTimeout(() => abrirMiCuenta(ok ? '🎉 ¡Gracias! Tus monedas llegan en unos segundos.' : pend ? 'Tu pago está en proceso; las monedas llegan en cuanto se apruebe.' : 'El pago no se completó.'), 1500);
    if (ok || pend) { let n = 0; const t2 = setInterval(async () => { await refrescar(); if (++n > 12) clearInterval(t2); }, 5000); }
  }
  if (/[?&]cuenta=1/.test(location.search)) {
    history.replaceState(null, '', location.pathname);
    setTimeout(() => abrirMiCuenta(), 1500);
  }
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
  async function historial() {
    const caja = $('historial'); if (!caja || !sb) return;
    const { data } = await sb.from('historial').select('*').limit(30);
    const filas = (data || []).filter((d) => d.verdes + d.rojas + (d.verdes_error || 0) + (d.rojas_error || 0) > 0);
    if (!filas.length) { caja.innerHTML = '<p class="tenue">El historial se va llenando día con día.</p>'; return; }
    const tv = filas.reduce((s, d) => s + d.verdes, 0), tr = filas.reduce((s, d) => s + d.rojas, 0);
    const ev = filas.reduce((s, d) => s + d.verdes_elige, 0), er = filas.reduce((s, d) => s + d.rojas_elige, 0);
    const xv = filas.reduce((s, d) => s + (d.verdes_error || 0), 0), xr = filas.reduce((s, d) => s + (d.rojas_error || 0), 0);
    const { data: ia } = await sb.from('ia_aciertos').select('*').maybeSingle();
    const p100 = (a, b) => (a + b ? Math.round(100 * a / (a + b)) + ' %' : '—');
    caja.innerHTML = '<div class="num">✅ ' + tv + ' ❌ ' + tr + ' <span class="pct">' + Math.round(100 * tv / (tv + tr)) + ' %</span></div>' +
      '<div class="sub">💎 Diamante: ✅ ' + ev + ' ❌ ' + er + (ev + er ? ' · ' + Math.round(100 * ev / (ev + er)) + ' %' : '') + '</div>' +
      (xv + xr ? '<div class="sub">💰 Cuota alta (errores de cuota): ✅ ' + xv + ' ❌ ' + xr + ' · ' + p100(xv, xr) + '</div>' : '') +
      ''; caja.innerHTML += '';
    // v391 — el bloque de la IA sale SIEMPRE (aunque aún no haya partidos terminados)
    const iaCaja = $('ia-hist');
    if (iaCaja) iaCaja.innerHTML = !ia ? '<p class="tenue">Sin datos de la IA todavía.</p>' :
      '<div class="ia-fila"><span>Partidos analizados</span><b>' + (ia.analizados || 0) + '</b><small>' + (ia.pendientes || 0) + ' esperando resultado</small></div>' +
      '<div class="ia-fila"><span>🤖 Acierta el ganador</span><b>✅ ' + ia.resultado_ok + ' ❌ ' + ia.resultado_mal + '</b><small>' + p100(ia.resultado_ok, ia.resultado_mal) + '</small></div>' +
      '<div class="ia-fila"><span>📈 Elegir al favorito (la vara)</span><b>✅ ' + ia.mercado_ok + ' ❌ ' + ia.mercado_mal + '</b><small>' + p100(ia.mercado_ok, ia.mercado_mal) + '</small></div>' +
      '<div class="ia-fila"><span>⚽ Más / menos de 2.5 goles</span><b>✅ ' + ia.goles_ok + ' ❌ ' + ia.goles_mal + '</b><small>' + p100(ia.goles_ok, ia.goles_mal) + '</small></div>' +
      '<div class="ia-fila"><span>⚽ Marcador exacto</span><b>✅ ' + (ia.marcador_ok || 0) + ' ❌ ' + (ia.marcador_mal || 0) + '</b><small>' + p100(ia.marcador_ok || 0, ia.marcador_mal || 0) + '</small></div>' +
      '<div class="ia-fila"><span>🎯 Ambos anotan</span><b>✅ ' + (ia.btts_ok || 0) + ' ❌ ' + (ia.btts_mal || 0) + '</b><small>' + p100(ia.btts_ok || 0, ia.btts_mal || 0) + '</small></div>' +
      '<div class="ia-fila"><span>🚩 Córners (más / menos)</span><b>✅ ' + (ia.corners_ok || 0) + ' ❌ ' + (ia.corners_mal || 0) + '</b><small>' + p100(ia.corners_ok || 0, ia.corners_mal || 0) + '</small></div>' +
      '<div class="ia-fila"><span>🟨 Tarjetas (más / menos)</span><b>✅ ' + (ia.tarjetas_ok || 0) + ' ❌ ' + (ia.tarjetas_mal || 0) + '</b><small>' + p100(ia.tarjetas_ok || 0, ia.tarjetas_mal || 0) + '</small></div>' +
      '<div class="ia-fila"><span>❌ Cuando dijo «en contra», el pick falló</span><b>' + ia.aviso_bien + ' de ' + (ia.aviso_bien + ia.aviso_mal) + '</b><small>' + p100(ia.aviso_bien, ia.aviso_mal) + '</small></div>' +
      '<div class="ia-fila"><span>✅ Cuando dijo «a favor», el pick salió</span><b>' + ia.favor_bien + ' de ' + (ia.favor_bien + ia.favor_mal) + '</b><small>' + p100(ia.favor_bien, ia.favor_mal) + '</small></div>' +
      '<p class="tenue chico">Si la IA no le gana a «elegir al favorito», no aporta: por eso la medimos aparte y nuestros picks no dependen de ella.</p>';
    caja.innerHTML = caja.innerHTML +
      '<table class="tabla"><tr><th>Día</th><th>✅</th><th>❌</th><th>%</th><th>💎</th><th>💰</th></tr>' +
      filas.map((d) => '<tr><td>' + esc(d.fecha) + '</td><td>' + d.verdes + '</td><td>' + d.rojas + '</td><td>' + Math.round(100 * d.verdes / (d.verdes + d.rojas)) + '</td><td>' + d.verdes_elige + '-' + d.rojas_elige + '</td><td>' + (d.verdes_error || 0) + '-' + (d.rojas_error || 0) + '</td></tr>').join('') + '</table>';
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
        const chip = x.est === 'verde' ? '<span class="et verde">✅ Verde</span>' : x.est === 'roja' ? '<span class="et roja">❌ Roja</span>'
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
    sb.auth.onAuthStateChange(() => refrescar());
    refrescar();
    historial();
    telegramHist();
    setInterval(() => { historial(); telegramHist(); }, 10 * 60 * 1000);
  }
  telegram();
})();
