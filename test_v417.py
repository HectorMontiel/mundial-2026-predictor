#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v417-v418.

  v417 — la IA bloqueada para quien no es VIP (lleva a Planes) y los planes con
         sus números REALES (30 días, sólo con 30+ partidos; de la IA sólo lo mejor).
  v418 — tarjetas de TODOS los partidos: los que no tienen pick salen como
         «sólo análisis», en un fichero aparte que nunca cuenta en verdes/rojas.

Ejecutar:  python test_v417.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def leer(*p):
    return open(os.path.join(*p), encoding='utf-8').read()


def probar_v417():
    sql = leer('supabase', 'v417_planes_y_ia_bloqueada.sql')
    check('historial_niveles with (security_invoker = true)' in sql and "coalesce(tipo, 'pick') <> 'analisis'" in sql,
          'el récord por nivel respeta la RLS de picks y no cuenta las tarjetas de sólo análisis')
    check('select distinct partido, fecha from public.ia_analisis' in sql,
          'ia_disponibles sólo dice QUÉ partidos tienen IA, nunca el contenido')
    app, js, html = leer('web', 'app.js'), leer('web', 'cuenta.js'), leer('web', 'index.html')
    check('function iaBloque(p, L, V, ctx)' in app and 'data-vista-ir="planes" data-foco="plan-vip"' in app
          and 'SPX.esVip && SPX.esVip()' in app, 'quien no es VIP ve «🤖 Análisis IA 🔒 VIP» y lo lleva al plan VIP')
    check('t.dataset.foco && document.getElementById(t.dataset.foco)' in app, 'el candado aterriza en el plan VIP')
    check("esVip: () => esVip()" in js and "from('ia_disponibles')" in js, 'la página sabe qué partidos tienen IA')
    check('async function numerosPlanes()' in js and 'v + r >= 30' in js and "x.que === 'mejor' && x.total >= 30" in js,
          'los planes enseñan números reales, sólo con 30+ partidos, y de la IA sólo lo mejor')
    check('id="plan-vip"' in html and 'id="numeros-vip"' in html and 'id="numeros-monedas"' in html
          and 'Análisis IA de cada partido' in html, 'cada plan dice lo que incluye y trae sus números')


def probar_v418():
    import exportar_web as xw
    hoy = dt.date(2026, 10, 21)
    prons = [{'deporte': 'Fútbol', 'partido': 'A vs B', 'fecha': '2026-10-21', 'inicio': '2026-10-21 19:00:00', 'apuesta': 'Gana A', 'prob': 0.6},
             {'deporte': 'Fútbol', 'partido': 'C vs D', 'fecha': '2026-10-21', 'inicio': '2026-10-21 19:00:00', 'apuesta': 'Gana C', 'prob': 0.7},
             {'deporte': 'Fútbol', 'partido': 'E vs F', 'fecha': '2026-10-30', 'inicio': '2026-10-30 19:00:00', 'apuesta': 'Gana E', 'prob': 0.7}]
    picks = [{'partido': 'C vs D', 'fecha': '2026-10-21', 'id': 'x'}]
    jugados = [{'deporte': 'Fútbol', 'partido': 'G vs H', 'fecha': '2026-10-20', 'inicio': '2026-10-20 19:00:00', 'apuesta': 'Gana H',
                'prob': 0.48, 'jugado': True, 'goles_home': 1, 'goles_away': 2},
               {'deporte': 'Fútbol', 'partido': 'I vs J', 'fecha': '2026-10-20', 'jugado': True}]
    an = xw.solo_analisis(prons, picks, jugados, hoy)
    por = {a['partido']: a for a in an}
    check(set(por) == {'A vs B', 'G vs H'}, 'sólo los partidos SIN pick, de hoy a pasado, y los jugados con marcador: %s' % sorted(por))
    a = por.get('A vs B') or {}
    check(a.get('solo_analisis') and a.get('tipo') == 'analisis' and a.get('premium') is False and a.get('cuota') is None
          and str(a.get('id', '')).startswith('an-'), 'la tarjeta va marcada, sin cuota ni premium, y con su propio id')
    check((por.get('G vs H') or {}).get('marcador') == '1-2' and (por.get('G vs H') or {}).get('estado') == 'final',
          'lo ya jugado sale con su marcador')
    src = leer('exportar_web.py')
    check("ANALISIS = os.environ.get('WEB_ANALISIS'" in src and "r.pop('analisis', [])" in src
          and 'subir_supabase(r[' not in src.split('def solo_analisis')[1].split('def construir')[0],
          'las de sólo análisis van a su fichero, nunca a la tabla picks')
    ia = leer('ia_gemini.py')
    check("'analisis.json'" in ia and "if not x.get('solo_analisis')" in ia and "-1 if x.get('solo_analisis')" in ia,
          'la IA analiza también esos partidos, sin tomar la sugerencia del modelo como pick nuestro')
    app = leer('web', 'app.js')
    check("if (p.solo_analisis) return { n: 'Sólo análisis'" in app and 'function listaConAnalisis()' in app
          and "cajaMarcador('Hoy', estado.picks.filter" in app, 'la página las enseña sutiles y los marcadores siguen contando sólo picks')


def probar_v419():
    import pandas as pd
    import config
    import historico_fotmob as hf
    import stats_flashscore as sf
    for c, n in (('cze_first', 1000), ('aze_premier', 600)):
        h = pd.read_csv('historico_%s.csv' % c)
        check(c in config.LEAGUES and c in hf.LIGAS and c in sf.EXTRA and len(h) >= n and h['home_corners'].notna().sum() >= 200,
              'v419: %s con partidos y córners REALES (%d partidos, %d con córners)' % (c, len(h), h['home_corners'].notna().sum()))
    check(config.LEAGUES['cze_first'].get('disponible') is False and config.LEAGUES['aze_premier'].get('disponible') is False,
          'v419: Chequia y Azerbaiyán no entran al barrido de picks (sólo dan liga local)')
    js = leer('web', 'cuenta.js')
    check('>= 0.75 ? linea(ico, n' in js, 'v419: los planes sólo presumen los niveles de 75 % o más')


def probar_v420():
    import datetime as _dt
    import combinadas_web as cw
    check(cw.TIPOS['combinada']['cuota'] == (1.20, 1.60) and cw.TIPOS['combinada'].get('solo_altos')
          and cw.TIPOS['combinada'].get('por_acierto') and cw.TIPOS['alta']['cuota'] == (1.80, 2.60),
          'v420: las de 2 patas con 💎/🔷 por acierto real, cuota 1,20-1,60; las de 3 sin cambio')
    ahora = _dt.datetime(2026, 10, 21, 12, tzinfo=_dt.timezone.utc)
    ini = (ahora + _dt.timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
    pk = lambda i, dep, c, pr, el=False: {'id': 'q%d' % i, 'partido': 'X%d vs Y%d' % (i, i), 'deporte': dep, 'apuesta': 'Gana X%d' % i,
                                           'cuota': c, 'prob': pr, 'elige': el, 'inicio': ini, 'estado': 'pendiente', 'tipo': 'pick'}
    ps = [pk(1, 'Tenis', 1.12, .90, True), pk(2, 'Tenis', 1.12, .89, True), pk(3, 'Tenis', 1.25, .80), pk(4, 'Tenis', 1.24, .81)]
    cs = [c for c in cw.armar(ps, {}, ahora, cal={}) if c['tipo'] == 'combinada' and c['alcance'] == 'Tenis']
    check(cs and {x['id'] for x in cs[0]['patas']} == {'q1', 'q2'},
          'v420: dos 💎 a 1,12 (1,25 total) ya entran; antes se forzaban patas más flojas')
    cal = cw.calibracion([{'elige': True, 'deporte': 'Tenis', 'estado': 'verde'}] * 20 + [{'elige': True, 'deporte': 'NBA', 'estado': 'roja'}] * 20)
    check(cal[('Diamante', 'Tenis')] > 0.9 and cal[('Diamante', 'NBA')] < 0.3, 'v420: la calibración es el acierto real por nivel y deporte')


def probar_v420_web():
    sql = leer('supabase', 'v420_precios_plata_deportes.sql')
    import re as _re
    bandas = [(float(a), float(b), int(m)) for a, b, m in _re.findall(r'\((\d\.\d\d), (\d+\.\d\d), (\d+)\)', sql)]
    check(bandas and min(m for _, _, m in bandas) == 5 and bandas[0][:2] == (1.00, 1.15) and bandas[1] == (1.15, 1.30, 6)
          and all(bandas[i][1] == bandas[i + 1][0] and bandas[i][2] < bandas[i + 1][2] for i in range(len(bandas) - 1)),
          'v420: precios escalonados desde 5 🪙, sin huecos y siempre subiendo: %s' % bandas)
    check("coalesce((p).prob, 0) >= 0.80 and coalesce((p).prob, 0) < 0.85 then 0" in sql and "= 'analisis' then 0" in sql,
          'v420: 🥇 Oro gratis, 🥈 Plata a monedas y el «sólo análisis» nunca se cobra')
    check('create or replace view public.historial_deportes' in sql and 'gana_por_100' in sql.split('create or replace view public.historial_niveles')[-1],
          'v420: historial por deporte y la ganancia por nivel')
    js, html = leer('web', 'cuenta.js'), leer('web', 'index.html')
    check("['Diamante', 'Platino', 'Plata', 'Cuota alta'].includes(n)" in js and '<li>Picks 🥇 Oro</li>' in html,
          'v420: la página cobra 🥈 Plata y el plan gratis dice sólo 🥇 Oro')
    check('function mejorIA(med)' in js and 'm.total >= 20 && m.ok / m.total >= 0.65' in js and 'function wilson(ok, n)' in js
          and 'calibracion(med)' not in js.split('mejorIA(med) +')[0][-400:],
          'v420: de la IA sólo lo mejor, nivelado entre porcentaje y cantidad (Wilson, 20+ partidos)')
    check("'IA, el ganador del partido'" in js and "id=\"tabla-precios\"" in html and "from('historial_deportes')" in js
          and 'id="dep-hist"' in html, 'v420: el ganador de la IA en el VIP, precios de la base y el historial por deporte')


def probar_v421():
    import json as _json
    js, app, html = leer('web', 'cuenta.js'), leer('web', 'app.js'), leer('web', 'index.html')
    salir = js.split("if (t.hasAttribute('data-salir')) {")[1].split('return;')[0]
    check(salir.index('yo.user = null') < salir.index('signOut'), 'v421: al cerrar sesión la pantalla se limpia antes de esperar a Supabase')
    check('yo.siguiendoAhora.has(id)' in js and "onConflict: 'usuario,pick'" in js and "from('seguidores').select('pick,n').eq('pick', id)" in js
          and 'const otros = (n || 0) - (sigo ? 1 : 0)' in js, 'v421: «seguir» de un toque a la vez, sin duplicar y el 👥 sin contarte a ti')
    check("Date.now() - ini > duracion(ps[0].deporte)" in app and "'Fútbol': 2.1" in app, 'v421: sin ESPN, el partido se cierra cuando ya no puede seguir jugándose')
    check('const conPicks = filas.filter(' in js, 'v421: el historial por día sin renglones vacíos')
    sim = _json.load(open(os.path.join('web', 'combinadas_simuladas.json'), encoding='utf-8'))
    check(sim['desde'] == '2026-10-17' and len(sim['combinadas']) >= 10 and all(c['tipo'] == 'combinada' for c in sim['combinadas'])
          and "const DESDE_NUEVO = '2026-10-22'" in app, 'v421: las de 2 patas del historial son el método nuevo desde la misma fecha (simulado, y lo dice)')
    check('💰 Cuota alta y 🔗 combinadas sin gastar monedas' in html and '20 🪙 de regalo al registrarte' in html and '50 🪙 de regalo' not in html,
          'v421: el VIP incluye 💰 Cuota alta y se regalan 20 🪙')
    check("set valor = '20' where clave = 'monedas_bienvenida'" in leer('supabase', 'v421_bienvenida_20.sql'), 'v421: la base regala 20 🪙')


def probar_v422():
    js, app, html = leer('web', 'cuenta.js'), leer('web', 'app.js'), leer('web', 'index.html')
    check('id="intereses"' in html and 'data-guardar-intereses' in html and 'id="parati"' in html,
          'v422: la pregunta «¿Qué te interesa?» y el carrusel «✨ Para ti»')
    check('async function cargarGustos()' in js and "select('id,deporte,liga,cuota,prob,elige,tipo').in('id', ids)" in js
          and 'yo.perfil.deportes == null' in js and '7 * 864e5' in js and 'data-intereses' in js,
          'v422: las tendencias salen de lo que sigue y desbloquea; se pregunta una vez y se cambia desde Mi cuenta')
    check('function paraTi()' in app and 'it.ligas.has(p.liga)' in app and 'Math.log(Number(p.cuota) / med)' in app
          and 'function ordenPreferido(mapa)' in app and 'ordenPreferido(porLiga(grupos))' in app,
          'v422: Para ti puntúa liga, deporte, nivel y cuota; sus ligas van primero')
    check('add column if not exists ligas text[]' in leer('supabase', 'v422_intereses.sql'), 'v422: las ligas se guardan en el perfil')


def probar_v423():
    import datetime as _dt, tempfile, json as _json
    import exportar_web as xw
    ini = _dt.datetime(2026, 10, 22, 1, 30, tzinfo=_dt.timezone.utc).timestamp()
    doc = {'partidos': [{'deporte': 'mlb', 'liga': 'MEXICO: LMP', 'home': 'Jalisco', 'away': 'Mexicali', 'inicio': str(ini),
                         'casas': {'A': {'HOME_AWAY': {'home': 1.62, 'away': 2.10}}, 'B': {'HOME_AWAY': {'home': 1.65, 'away': 2.13}}}},
                        {'deporte': 'mlb', 'liga': 'USA: MLB - Play Offs', 'home': 'X', 'away': 'Y', 'inicio': str(ini),
                         'casas': {'A': {'HOME_AWAY': {'home': 1.6, 'away': 2.3}}}}]}
    ruta = os.path.join(tempfile.gettempdir(), '_v423_cmx.json'); _json.dump(doc, open(ruta, 'w'))
    b = xw.beisbol_invierno(_dt.date(2026, 10, 21), ruta)
    check(len(b) == 1 and b[0]['partido'] == 'Jalisco vs Mexicali' and b[0]['liga'] == 'Liga Mexicana del Pacífico'
          and b[0]['fecha'] == '2026-10-21' and b[0]['solo_analisis'] and b[0]['fuente'] == 'casa' and b[0]['cuota'] is None
          and 0.55 < b[0]['prob'] < 0.58, 'v423: el béisbol de invierno sale como sólo análisis, con lo que ve la casa (no la MLB)')
    m = _json.load(open('_v423_beisbol_invierno.json', encoding='utf-8'))
    check(m['casa_065_o_mas']['roi_por_100'] < 0 and 'no se meten picks' in m['veredicto'], 'v423: medido, no hay pick que vender (y queda escrito)')
    check("p.fuente === 'casa' ? 'la casa ve'" in leer('web', 'app.js'), 'v423: la tarjeta dice que es lo que ve la casa')


def probar_v424():
    fn = leer('functions', 'vivo.js')
    check('export async function onRequestGet' in fn and "'x-fsign': 'SW9D1eZo'" in fn and "/^[A-Za-z0-9]{6,12}$/.test(id)" in fn
          and "'Cache-Control': 'public, max-age=30'" in fn, 'v424: /vivo pide a Flashscore lo que ESPN no cubre (sólo lectura, id validado, 30 s de caché)')
    check("split('~SE÷').filter(Boolean)[0]" in fn, 'v424: las estadísticas son las del partido entero, no las de cada tiempo')
    app = leer('web', 'app.js')
    check('async function vivoFs()' in app and "fetch('vivo?dep=' + dep)" in app and 'estado.fsPor[clavePartido(ps[0])]' in app
          and 'estado.picks.concat(estado.analisis || [])) {' in app and 'setInterval(vivoFs, 45 * 1000)' in app,
          'v424: todos los partidos en vivo con marcador (ESPN, o si no Flashscore), también los de sólo análisis')
    check("estado.abiertos.has(k) && m.estado === 'in'" in app and "'Corner kicks': 'wonCorners'" in app,
          'v424: con la tarjeta abierta, sus estadísticas del momento')
    check("connect-src 'self'" in leer('web', '_headers'), 'v424: /vivo es del mismo sitio (la CSP lo permite)')
    wf = leer('.github', 'workflows', 'sitio_web.yml')
    check('pages deploy web' in wf and os.path.isdir('functions'), 'v424: Cloudflare publica functions/ junto con web/')


def probar_v425():
    js, fn = leer('web', 'cuenta.js'), leer('supabase', 'functions', 'entrar', 'index.ts')
    check("sb.auth.onAuthStateChange((evento) => {" in js and "setTimeout(refrescar, 0);\n    });" in js,
          'v425: el inicio de sesión ya no espera a que se recargue todo')
    check('async function esperarCaptcha(ms = 6000)' in js and "ocupado(e.target.querySelector('button[type=submit]'), 'Entrando…')" in js
          and '.cargando::before' in leer('web', 'estilo.css'), 'v425: espera al CAPTCHA y el botón muestra que está trabajando')
    check("accion: 'recuperar'" in js and "if (accion === 'recuperar' || accion === 'enlace') {" in fn
          and 'Si ese usuario existe' in fn, 'v425: el enlace por correo también con el usuario (el correo no sale del servidor)')
    html = leer('web', 'index.html')
    check('sb.auth.resetPasswordForEmail(quien' in js and 'anonE.auth.resetPasswordForEmail(correoE' in fn
          and "evento === 'PASSWORD_RECOVERY'" in js and 'const DESDE_RECUPERACION' in js and 'sb.auth.updateUser({ password: c1 })' in js
          and 'id="nueva-clave"' in html, 'v426: «Olvidé mi contraseña» manda el de RESTABLECER y al volver pide la nueva')


def probar_v427():
    app, css = leer('web', 'app.js'), leer('web', 'estilo.css')
    check('function cancha(v, p)' in app and 'fieldPositionX != null' in app and "(lado === 0 ? x : 100 - x) * 1.05" in app
          and "cancha(v, p) : '')" in app and 'h += cancha(v, p);' in app, 'v427: la cancha en vivo (jugadas con lugar, el visitante reflejado) en la tarjeta y la ficha')
    check('Presión minuto a minuto' in app and '.cancha-svg .balon' in css and 'prefers-reduced-motion' in css,
          'v429: la ola de presión minuto a minuto y el balón que recorre las jugadas (sin animación si el usuario la apaga)')
    check("webws.365scores.com/web/" in app and 'async function detalle365(p)' in app and 'yardFormation' in app and 'chartEvents' in app
          and 'https://webws.365scores.com' in leer('web', '_headers'), 'v429: los 22 en su formación y todos los tiros con su xG (365Scores, la CSP lo permite)')
    check('function mejorCruce(L, V, lista, kh, ka)' in app and "mejorCruce(L, V, lista, 'home', 'away')" in app,
          'v429: se empareja con el partido MÁS parecido (no el Sub-19 del mismo día)')
    check('function estadoVisto(p, v)' in app and "title=\"Al pitazo; el servidor lo confirma\"" in app
          and "evs.includes('roja') ? 'roja'" in app and "cajaMarcador('Hoy', estado.picks.filter" in app,
          'v430: cada pick y cada combinada con su verde o rojo al pitazo; los marcadores, sólo lo oficial')


def probar_v428():
    sql = leer('supabase', 'v428_mis_combinadas.sql')
    check('v_n < 2 or v_n > 20' in sql and 'count(distinct lower(p.partido))' in sql and "p.inicio > now() + interval '1 minute'" in sql
          and 'public.es_pro()' in sql and 'from public.desbloqueos d where d.pick = p.id' in sql,
          'v428: de 2 a 20 picks, partidos distintos, sin empezar y sólo lo que el usuario puede ver')
    check("when v_cuota >= 5 then 5 when v_cuota >= 3 then 3 when v_cuota >= 2 then 2 else 0" in sql and 'o.dia = c.dia and o.premio > 0' in sql
          and 'v_total % 5 = 0' in sql, 'v428: premio 2/3/5 🪙 por cuota, una premiada por día y +5 🪙 cada 5')
    check('revoke all on table public.combinadas_usuario from public, anon, authenticated' in sql
          and 'grant execute on function public.liquidar_combinadas_usuario() to service_role' in sql,
          'v428: nadie escribe la tabla ni da monedas desde la página; sólo el servidor liquida')
    js, xw = leer('web', 'cuenta.js'), leer('exportar_web.py')
    check("sb.rpc('crear_combinada', { p_patas: boleto() })" in js and 'data-a-comb' in js and 'async function misCombinadas(intento)' in js
          and '/rest/v1/rpc/liquidar_combinadas_usuario' in xw, 'v428: el boleto, «Mis combinadas» y la liquidación en cada pasada')


def probar_v431():
    app, css = leer('web', 'app.js'), leer('web', 'estilo.css')
    check('function moverCanchas()' in app and 'function dominio(k)' in app and 'async function stats365(gid)' in app
          and 'setInterval(moverCanchas, 1000)' in app, 'v431: el balón y los 22 se mueven con quién ataca ahora (365Scores, ESPN, posesión)')
    check("'MEDIO TIEMPO'" in app and "'FINAL'" in app and 'const quieto = m.pausa;' in app,
          'v431: en el medio tiempo y al final todo se detiene y la cancha lo dice')
    check('Animación aproximada según el juego' in app and 'peligro (xG)' in app and 't.gol || minuto(t.min) >= ahora - 15' in app,
          'v431: leyenda clara, sólo los tiros recientes y dice que la animación es aproximada')
    check("if (v && v.fase === 'pre' && !fin) return 'proximo';" in app, 'v431: si ESPN dice que aún no empieza, no se toma como en vivo (la hora rara de la MLS)')
    check('.cancha-svg .jug { transition: transform' in css and '.cancha-svg .letrero text' in css, 'v431: el movimiento es suave')


def probar_v433():
    app, css = leer('web', 'app.js'), leer('web', 'estilo.css')
    check('const FRANJA = (prof) =>' in app and "data-prof=\"' + j.prof" in app and 'const [mn, mx] = FRANJA(q.prof)' in app,
          'v432: los 22 siguen al balón con lógica (cada puesto en su franja; el más cercano va al balón)')
    check('class="ola-gol' in app and '.ola-gol.arriba' in css, 'v432: un ⚽ en la ola en el minuto de cada gol')
    check('function ponerEscena(e, js, m)' in app and "e.tipo === 'corner'" in app and "e.tipo === 'libre'" in app and "e.tipo === 'penal'" in app
          and "e.tipo === 'gol'" in app and "e.tipo === 'banda'" in app and "e.tipo === 'tiro'" in app,
          'v433: córner, tiro libre (con barrera a 9,15 m), penal, gol con festejo, saque de banda y tiro')
    check('function escenasDeStats(m)' in app and 'sube(15, lado)' in app and "if (e.tipo === 'gol') { bx = 52.5; by = 34;" in app,
          'v433: sin ESPN, córners/faltas/saques de banda salen de las estadísticas; tras el gol, saque de media cancha')


def probar_v434():
    app, css = leer('web', 'app.js'), leer('web', 'estilo.css')
    check('m.portador = port ? port.key : null;' in app and "classList.toggle('portador', q === port)" in app and '.cancha-svg .jug.portador .aro' in css,
          'v434: el balón siempre lo tiene alguien; sólo él sale grande con número y nombre')
    check('<line class="pase"' in app and "ln.classList.add('ve')" in app and 'dd < 6 || dd > 28' in app,
          'v434: pases de 6 a 28 m, de preferencia hacia adelante, con su línea')
    check('const f = q === port ? 1 : quieto ? 0.5 : m.escena ? 0.6 : 0.38;' in app and 'm.pos[q.key] = [q.cx, q.cy];' in app,
          'v434: cada quien va a su lugar con inercia; el lugar sobrevive a los repintados')
    check('const barras = suave.map(' in app and '<polygon points="0,12' not in app, 'v434: la presión en barras por minuto, como Sofascore')
    check('if (!m.ini && reales.length) {' in app and 'reales.forEach((q) => m.vistas.add(q.id));' in app and 'q.m < (m.minuto || 0) - 2' in app
          and 'reales.slice(0, -1)' not in app, 'v434: al abrir una tarjeta en vivo, la cancha va en el minuto que corre (no repite lo ya pasado)')
    check('class="bola"' in app and 'class="penta"' in app and '.cancha-svg .balon .bola { fill: #fff; stroke: #0b1220;' in css,
          'v435: el balón con contorno oscuro y aro amarillo (no se pierde con el equipo de blanco)')
    check('q.cx = Math.max(bd, Math.min(105 - bd, q.cx));' in app and "prof <= 5 ? [2, 13] : prof <= 35 ? [7, 66]" in app,
          'v435: nadie se sale de la cancha ni se pega a la línea')
    check('const bd = q === port ? 3.2 :' in app and 'bx = Math.max(bb, Math.min(105 - bb, bx));' in app and '.cancha-svg { overflow: hidden; }' in css,
          'v438: ni el portador (con su aro) ni el balón se dibujan fuera de la cancha')
    cu = leer('web', 'cuenta.js')
    check('function pintarHistorial(caja)' in cu and "c.estado !== 'pendiente'" in cu and 'data-hist-rango' in cu
          and 'id="mi-hist"' in leer('web', 'index.html') and "sb.from('seguidos').select('pick,creado')" not in cu,
          'v442: el historial es sólo de SUS combinadas terminadas (no lo que sigue); «Mis combinadas» sólo las vivas')
    check("const pr = PREMIO(Number(c.cuota));" in cu and 'Si acierta: <b>+' in cu, 'v443: cada combinada pendiente dice cuántas 🪙 gana si acierta')
    check(True,
          'v439: «Mi historial»: lo seguido, desbloqueado y combinado, con verdes/rojas y desglose por deporte')
    check('$100 a cada uno' not in cu, 'v440: el historial no pone dinero ni supuestos (decisión del usuario)')
    check('.partido-fila.deslizable' in css and "document.addEventListener('touchmove'" in app and 'data-dejar=' in app and 'async function quitarSeguidos(ids, volver)' in cu,
          'v440: en «Mis picks» se desliza la fila para quitarla, con «Deshacer»')
    check("ps.some(empezo) ? '<span class=\"et vivo\">🔴 En juego</span>'" in cu and 'class="tg-pata ir-partido" data-ficha=' in cu,
          'v441: la combinada dice «Por jugar» hasta que empieza alguno; cada pata abre su partido')
    check('if (turno !== turnoComb) return;' in cu and 'function pintarCombinadas(caja)' in cu and "'sharpicks-comb-' + (yo.user && yo.user.id)" in cu
          and "caja.innerHTML = '<p class=\"tenue\">Arma tu combinada" not in cu,
          'v437: «Mis combinadas» no desaparece al volver a la app (sólo pinta la petición más nueva; un error no borra)')
    check("const fuente = espnJ.length ? 'espn' : t365.length ? '365' : evE.length ? 'eventos' : '';" in app
          and "fuente === 'espn' ? js.map(" in app and '.concat(todos.map(' not in app,
          'v436: una fuente por cosa, sin mezclar (los goles ya no salen dos veces en la presión)')
    check('function puestoEspn(a)' in app and 'v && v.once && v.once.length >= 18 ? v.once' in app and 'BASE_442.flatMap(' in app,
          'v436: si 365Scores no trae la alineación, la de ESPN; la cancha nunca se queda sin jugadores')
    check("const pocas = reales.filter((q) => q.w > 0).length < 4;" in app and '.presion-svg.linea .va' in css,
          'v436: sin jugadas suficientes no se inventa la presión: la línea del partido con goles y tarjetas')
    check("gid === null && Date.now() - (estado.p365[k + '|t'] || 0) > 120e3" in app and 'setInterval(vivo365, 20 * 1000);' in app,
          'v436: se vuelve a buscar el partido en 365Scores y se refresca cada 20 s')
    check("(pocas ? '' : 'Presión')" in app and 'tamaño = peligro (xG)</span>' not in app, 'v434: el menos texto posible en la cancha')


if __name__ == '__main__':
    probar_v434()
    probar_v433()
    probar_v431()
    probar_v427()
    probar_v428()
    probar_v425()
    probar_v424()
    probar_v423()
    probar_v422()
    probar_v421()
    probar_v420_web()
    probar_v420()
    probar_v419()
    probar_v417()
    probar_v418()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
