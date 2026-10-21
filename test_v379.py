#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v379: SharPicks con cuentas, monedas, «No Win, No Pay» y los
dos canales de Telegram.

  1. MODO DE PAGO (`exportar_web.premium`): apagado, nada cambia; encendido,
     el texto del pick premium SALE de lo público (fichero y tabla `picks`)
     y va sólo a `picks_premium`.
  2. La base devuelve las monedas sola si el pick sale rojo o nulo, el usuario
     no puede tocarse las monedas, y el premium sólo lo lee quien le toca.
  3. Telegram: cada canal recibe sólo lo suyo y sólo lo nuevo; sin base no
     manda nada (no repetir es más importante que mandar).
  4. La página: cuenta, Mis picks, planes, historial, páginas legales.

Ejecutar:  python test_v379.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def _p(i, **kw):
    d = {'id': 'id%d' % i, 'partido': 'A%d vs B%d' % (i, i), 'apuesta': 'Gana A%d' % i, 'cuota': 1.15,
         'prob': 0.86, 'elige': False, 'estado': 'pendiente', 'inicio': '2026-10-17 20:00:00'}
    d.update(kw)
    return d


def probar():
    import exportar_web as ew
    os.environ.pop('PREMIUM_NIVELES', None)
    ps = [_p(1, elige=True), _p(2, prob=0.81)]
    check(ew.premium(ps) == [] and ps[0]['apuesta'] == 'Gana A1' and not ps[0]['premium'],
          'en el lanzamiento (sin PREMIUM_NIVELES) todo es gratis')
    os.environ['PREMIUM_NIVELES'] = 'Diamante'
    try:
        ps = [_p(1, elige=True), _p(2, prob=0.81), _p(3, elige=True, estado='verde')]
        sec = ew.premium(ps)
        check(sec == [{'id': 'id1', 'apuesta': 'Gana A1'}] and ps[0]['apuesta'] == '🔒 Pick Diamante'
              and ps[0]['premium'] and ps[1]['apuesta'] == 'Gana A2' and ps[2]['apuesta'] == 'Gana A3',
              'con «Diamante», sólo esos y sólo antes de empezar salen de lo público')
    finally:
        os.environ.pop('PREMIUM_NIVELES', None)
    check(ew.nivel({'elige': True}) == 'Diamante' and ew.nivel({'prob': 0.85}) == 'Platino'
          and ew.nivel({'prob': 0.8}) == 'Oro' and ew.nivel({'prob': 0.7}) == 'Plata',
          'los niveles son los de la página')

    sql = open(os.path.join('web', 'negocio.sql'), encoding='utf-8').read()
    check("new.estado in ('roja', 'nula')" in sql and 'create trigger no_win_no_pay' in sql,
          'la base devuelve sola las monedas si sale roja o nula')
    check('revoke update on public.perfiles from authenticated' in sql
          and 'grant update (nombre, deportes)' in sql,
          'el usuario no puede cambiarse sus monedas ni su plan')
    check('premium a quien le toca' in sql and "p.estado in ('verde','roja','nula')" in sql
          and 'public.es_pro()' in sql,
          'el pick premium sólo lo lee quien lo desbloqueó, el Pro, o ya liquidado')
    check("p.inicio <= now() then return 'ya empezó'" in sql, 'no se desbloquea lo ya empezado')

    import telegram_canales as tc
    ahora = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc)
    ps = [_p(1, elige=True), _p(2, prob=0.81), _p(3, prob=0.70, inicio='2026-10-19 20:00:00'),
          _p(4, elige=True, estado='verde', marcador='1-0', inicio='2026-10-17 09:00:00'),
          _p(5, prob=0.81, estado='roja', marcador='0-2', inicio='2026-10-17 08:00:00'),
          _p(6, prob=0.81, estado='verde', inicio='2026-10-15 08:00:00')]
    os.environ.pop('TELEGRAM_VIP_NIVELES', None)
    m = tc.armar(ps, set(), ahora)          # 12:00 UTC = 6:00 CDMX: aún no toca el gratis
    vip = '\n'.join(t for t, _ in m['vip'])
    # v400 — los 💎 se mandan al abrir su ventana para apostar (4 h antes), no al aparecer
    check('Gana A1' not in vip and 'Gana A4' in vip, 'a 8 h del partido el VIP aún no lo manda; sí los resultados')
    vip4 = '\n'.join(t for t, _ in tc.armar(ps, set(), dt.datetime(2026, 10, 17, 16, 30, tzinfo=dt.timezone.utc))['vip'])
    check('Gana A1' in vip4 and 'Ya es hora de apostar' in vip4 and 'Gana A2' not in vip4 and 'Gana A3' not in vip4,
          'el VIP: sus 💎 al abrir la ventana para apostar, y sus resultados')
    check(not [t for t, _ in m['gratis'] if t], 'el gratis no publica fuera de sus horarios')
    # el usuario: «en el gratis, combinadas de máximo 1,5 o una individual cada cierto tiempo»
    a9 = dt.datetime(2026, 10, 17, 15, 5, tzinfo=dt.timezone.utc)      # 9:05 CDMX
    ps9 = [_p(10, prob=0.84, cuota=1.15, inicio='2026-10-17 18:00:00'),
           _p(11, prob=0.82, cuota=1.20, inicio='2026-10-17 19:00:00'),
           _p(12, prob=0.845, cuota=1.05, inicio='2026-10-17 19:00:00'),
           _p(13, prob=0.80, cuota=1.18, inicio='2026-10-17 19:00:00', partido='A10 vs B10'),
           _p(14, elige=True, estado='verde', inicio='2026-10-16 20:00:00')]
    g = tc.armar(ps9, set(), a9)['gratis']
    textos = [t for t, _ in g if t]
    comb = [t for t in textos if 'Combinada del día' in t]
    check(len(comb) == 1 and 'Gana A10' in comb[0] and 'Gana A11' in comb[0] and 'cuota total <b>1.38</b>' in comb[0],
          'a las 9: UNA combinada de partidos distintos con cuota total 1,30-1,50, la más probable')
    check(not [t for t in textos if '🆕' in t] and sum('Gana A' in t for t in textos) <= 2,
          'el gratis ya no manda listas: una publicación por horario')
    check([t for t in textos if 'Ayer en el VIP' in t and '✅ 1 ❌ 0' in t], 'una vez al día: cómo le fue al VIP ayer')
    cubre = {c for _, cc in g for c in cc}
    check(not [t for t, _ in tc.armar(ps9, cubre, a9)['gratis'] if t], 'lo ya publicado no se repite')
    fin = [dict(p, estado='verde') if p['id'] in ('id10', 'id11') else p for p in ps9]
    r = [t for t, _ in tc.armar(fin, cubre, a9)['gratis'] if t]
    check(len(r) == 1 and 'Combinada cumplida' in r[0], 'y su resultado al terminar')
    a14 = dt.datetime(2026, 10, 17, 20, 5, tzinfo=dt.timezone.utc)     # 14:05 CDMX
    ps14 = [_p(20, prob=0.84, cuota=1.22, inicio='2026-10-17 23:00:00'),
            _p(21, prob=0.88, cuota=1.10, inicio='2026-10-17 23:00:00')]
    s = [t for t, _ in tc.armar(ps14, set(), a14)['gratis'] if 'Pick del día' in t]
    check(len(s) == 1 and 'Gana A20' in s[0], 'a las 14: el pick del día (la más segura que pague 1,20+)')
    for k in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY'):
        os.environ.pop(k, None)
    check(tc.ya_enviados() is None, 'sin la base no se sabe qué se mandó y no manda nada')

    js = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check("sb.rpc('desbloquear'" in js and "from('seguidos')" in js and 'signInWithOtp' in js
          and "from('historial')" in js, 'la página entra, sigue, desbloquea y enseña el historial')
    check('cuenta.js' in html and 'data-vista-ir="mios"' in html and 'id="planes"' in html
          and ('supabase-js@2.45.4' in html or 'vendor/supabase-2.45.4.js' in html), 'la página carga la cuenta, Mis picks y los planes')
    check(all(os.path.exists(os.path.join('web', f)) for f in ('terminos.html', 'privacidad.html'))
          and '800 911 2000' in open(os.path.join('web', 'terminos.html'), encoding='utf-8').read(),
          'términos (con +18 y juego responsable) y aviso de privacidad')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('function agrupar(' in app and 'function filaPartido(' in app and '.sort().join' in app,
          'una tarjeta por partido (también «B vs A»), con sus apuestas dentro')
    ex = open('exportar_web.py', encoding='utf-8').read()
    check("'id': 'not.in.(%s)' % vivos" in ex and "'estado': 'eq.pendiente'" in ex and "'inicio': 'gt.'" in ex,
          'lo que el modelo retira antes de empezar se borra de la base (no se queda repetido)')
    # v380 — «muy larga de scrollear»: pantallas con barra abajo, destacados,
    # lista compacta por liga que se abre, y lo terminado plegado al final
    check('class="nav-abajo"' in html and 'id="destacados"' in html and 'id="busca"' in html
          and 'function destacado(' in app and 'data-ver-fin' in app and 'ligasCerradas' in app,
          'la página es como app: barra abajo, destacados, ligas plegables y terminados al final')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    check('python telegram_canales.py' in wf and 'PREMIUM_NIVELES' in wf,
          'el workflow manda a los canales y respeta el modo de pago')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
