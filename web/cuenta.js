// v379 — SharPicks: la CUENTA del usuario (Supabase Auth), «Mis picks»,
// monedas, desbloquear con «No Win, No Pay» y el historial público.
// Lo que manda (saldo, quién ve un pick premium, la devolución si falla) lo
// decide la BASE (`negocio.sql`), no esta página: aquí sólo se pide y se pinta.
(function () {
  const C = window.CONFIG || {};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const sb = (window.supabase && C.SUPABASE_URL && C.SUPABASE_ANON_KEY)
    ? window.supabase.createClient(C.SUPABASE_URL, C.SUPABASE_ANON_KEY) : null;
  const yo = { user: null, perfil: null, seguidos: new Set(), desbloqueados: {}, conteo: {}, precios: {} };
  window.SPX = { yo, sb, extra, apuesta, filtrarMios, refrescar };

  // ---------- precios (de la base; 0 = gratis en el lanzamiento) ----------
  const CLAVE = { Diamante: 'precio_diamante', Platino: 'precio_platino', Oro: 'precio_oro', Plata: 'precio_plata' };
  function precio(p) { return Number(yo.precios[CLAVE[window.SP.nivel(p).n]] || 0); }

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
      if (!yo.user) h += '<button class="desbloquear" data-entrar>🔓 Entra gratis para verlo</button>';
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

  function filtrarMios(lista) { return lista.filter((p) => yo.seguidos.has(p.id)); }

  // ---------- sesión ----------
  async function refrescar() {
    if (!sb) return;
    const { data } = await sb.auth.getSession();
    yo.user = data && data.session ? data.session.user : null;
    const tareas = [
      sb.from('ajustes').select('clave,valor').then(({ data }) => { (data || []).forEach((x) => { yo.precios[x.clave] = x.valor; }); }),
      sb.from('seguidores').select('pick,n').then(({ data }) => { yo.conteo = {}; (data || []).forEach((x) => { yo.conteo[x.pick] = x.n; }); }),
    ];
    if (yo.user) {
      tareas.push(sb.from('perfiles').select('*').eq('id', yo.user.id).maybeSingle().then(({ data }) => { yo.perfil = data; }));
      tareas.push(sb.from('seguidos').select('pick').then(({ data }) => { yo.seguidos = new Set((data || []).map((x) => x.pick)); }));
      tareas.push(sb.from('picks_premium').select('id,apuesta').then(({ data }) => { yo.desbloqueados = {}; (data || []).forEach((x) => { yo.desbloqueados[x.id] = x.apuesta; }); }));
    } else { yo.perfil = null; yo.seguidos = new Set(); yo.desbloqueados = {}; }
    await Promise.all(tareas.map((t) => t.catch(() => {})));
    pintarCabecera();
    if (window.SP) window.SP.pintar();
  }

  function pintarCabecera() {
    const c = $('cuenta'); if (!c) return;
    if (!sb) { c.innerHTML = ''; return; }
    if (!yo.user) { c.innerHTML = '<button class="entrar" data-entrar>Entrar</button>'; return; }
    const nom = (yo.perfil && yo.perfil.nombre) || (yo.user.email || '').split('@')[0];
    c.innerHTML = '<span class="saldo" title="Tus monedas">🪙 ' + ((yo.perfil && yo.perfil.monedas) || 0) + '</span>' +
      (yo.perfil && yo.perfil.plan === 'pro' ? '<span class="et nivel diamante">PRO</span>' : '') +
      '<button class="entrar" data-salir title="Cerrar sesión">' + esc(nom) + ' ✕</button>';
  }

  function abrirAcceso(msg) {
    $('acceso-msg').textContent = msg || '';
    const g = document.querySelector('[data-google]'); if (g) g.hidden = !C.LOGIN_GOOGLE;
    $('acceso').hidden = false;
    setTimeout(() => $('acceso-correo').focus(), 50);
  }

  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-entrar],[data-salir],[data-seguir],[data-desbloquear],[data-cerrar-acceso],[data-google]');
    if (!t) return;
    // v380 — entrar con Google (se enciende con CONFIG.LOGIN_GOOGLE cuando
    // el proveedor está activo en Supabase → Authentication → Providers)
    if (t.hasAttribute('data-google')) {
      const { error } = await sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: location.origin + location.pathname } });
      if (error) $('acceso-msg').textContent = 'Google todavía no está disponible; entra con tu correo.';
      return;
    }
    if (t.hasAttribute('data-cerrar-acceso')) { $('acceso').hidden = true; return; }
    if (t.hasAttribute('data-entrar')) { abrirAcceso(); return; }
    if (t.hasAttribute('data-salir')) { await sb.auth.signOut(); await refrescar(); return; }
    if (!yo.user) { abrirAcceso('Inicia sesión para seguir y desbloquear picks.'); return; }
    if (t.dataset.seguir) {
      const id = t.dataset.seguir;
      if (yo.seguidos.has(id)) { await sb.from('seguidos').delete().eq('pick', id); yo.seguidos.delete(id); yo.conteo[id] = Math.max(0, (yo.conteo[id] || 1) - 1); }
      else { const { error } = await sb.from('seguidos').insert({ pick: id }); if (!error) { yo.seguidos.add(id); yo.conteo[id] = (yo.conteo[id] || 0) + 1; } }
      window.SP.pintar();
      return;
    }
    if (t.dataset.desbloquear) {
      t.disabled = true;
      const { data, error } = await sb.rpc('desbloquear', { pick_id: t.dataset.desbloquear });
      if (error || data !== 'ok') { alert(data === 'sin monedas' ? 'No te alcanzan las monedas.' : data === 'ya empezó' ? 'Ese partido ya empezó.' : 'No se pudo desbloquear. Intenta de nuevo.'); t.disabled = false; return; }
      await refrescar();
    }
  });

  $('acceso-form') && $('acceso-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const correo = $('acceso-correo').value.trim();
    if (!correo) return;
    $('acceso-msg').textContent = 'Enviando…';
    const { error } = await sb.auth.signInWithOtp({ email: correo, options: { emailRedirectTo: location.origin + location.pathname } });
    $('acceso-msg').textContent = error ? 'No se pudo enviar: ' + error.message
      : 'Listo: revisa tu correo y abre el enlace para entrar (revisa también «spam»).';
  });

  // ---------- historial público (verdes, rojas y porcentaje) ----------
  async function historial() {
    const caja = $('historial'); if (!caja || !sb) return;
    const { data } = await sb.from('historial').select('*').limit(30);
    const filas = (data || []).filter((d) => d.verdes + d.rojas > 0);
    if (!filas.length) { caja.innerHTML = '<p class="tenue">El historial se va llenando día con día.</p>'; return; }
    const tv = filas.reduce((s, d) => s + d.verdes, 0), tr = filas.reduce((s, d) => s + d.rojas, 0);
    const ev = filas.reduce((s, d) => s + d.verdes_elige, 0), er = filas.reduce((s, d) => s + d.rojas_elige, 0);
    caja.innerHTML = '<div class="num">✅ ' + tv + ' ❌ ' + tr + ' <span class="pct">' + Math.round(100 * tv / (tv + tr)) + ' %</span></div>' +
      '<div class="sub">💎 Diamante: ✅ ' + ev + ' ❌ ' + er + (ev + er ? ' · ' + Math.round(100 * ev / (ev + er)) + ' %' : '') + '</div>' +
      '<table class="tabla"><tr><th>Día</th><th>✅</th><th>❌</th><th>%</th><th>💎</th></tr>' +
      filas.map((d) => '<tr><td>' + esc(d.fecha) + '</td><td>' + d.verdes + '</td><td>' + d.rojas + '</td><td>' + Math.round(100 * d.verdes / (d.verdes + d.rojas)) + '</td><td>' + d.verdes_elige + '-' + d.rojas_elige + '</td></tr>').join('') + '</table>';
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
  function telegram() {
    const c = $('telegram'); if (!c) return;
    const g = C.TELEGRAM_GRATIS, v = C.TELEGRAM_VIP;
    c.innerHTML = (g ? '<a class="tg" href="' + esc(g) + '" target="_blank" rel="noopener">📢 Canal gratis de Telegram</a>' : '') +
      (v ? '<a class="tg vip" href="' + esc(v) + '" target="_blank" rel="noopener">💎 Grupo VIP de Telegram</a>' : '') +
      (!g && !v ? '<p class="tenue">Los canales de Telegram abren muy pronto.</p>' : '');
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
