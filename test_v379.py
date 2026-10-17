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
    check('premium a quien le toca' in sql and 'p.inicio <= now()' in sql and 'public.es_pro()' in sql,
          'el pick premium sólo lo lee quien lo desbloqueó, el Pro, o ya empezado')
    check("p.inicio <= now() then return 'ya empezó'" in sql, 'no se desbloquea lo ya empezado')

    import telegram_canales as tc
    ahora = dt.datetime(2026, 10, 17, 12, 0, tzinfo=dt.timezone.utc)
    ps = [_p(1, elige=True), _p(2, prob=0.81), _p(3, prob=0.70, inicio='2026-10-19 20:00:00'),
          _p(4, elige=True, estado='verde', marcador='1-0', inicio='2026-10-17 09:00:00'),
          _p(5, prob=0.81, estado='roja', marcador='0-2', inicio='2026-10-17 08:00:00'),
          _p(6, prob=0.81, estado='verde', inicio='2026-10-15 08:00:00')]
    os.environ.pop('TELEGRAM_VIP_NIVELES', None)
    m = tc.armar(ps, set(), ahora)
    vip, gra = '\n'.join(t for t, _ in m['vip']), '\n'.join(t for t, _ in m['gratis'])
    check('Gana A1' in vip and 'Gana A1' not in gra and 'Gana A2' in gra and 'Gana A2' not in vip,
          'el 💎 va al VIP y el 🥇 al gratis')
    check('Gana A3' not in vip + gra, 'lo de pasado mañana todavía no se manda')
    check('Gana A4' in vip and 'Gana A4' in gra and 'Gana A5' in gra and 'Gana A6' not in gra,
          'los resultados del VIP también salen en el gratis (la prueba); lo viejo no')
    check('Hay <b>1 picks nuevos</b>' in gra, 'el gratis avisa cuántos hay en el VIP')
    cubre = {c for msgs in m.values() for _, cc in msgs for c in cc}
    m2 = tc.armar(ps, cubre, ahora)
    check(not m2['vip'] and not [t for t, _ in m2['gratis'] if 'Hay <b>' not in t],
          'lo ya enviado no se repite')
    for k in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY'):
        os.environ.pop(k, None)
    check(tc.ya_enviados() is None, 'sin la base no se sabe qué se mandó y no manda nada')

    js = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check("sb.rpc('desbloquear'" in js and "from('seguidos')" in js and 'signInWithOtp' in js
          and "from('historial')" in js, 'la página entra, sigue, desbloquea y enseña el historial')
    check('cuenta.js' in html and 'data-dia="mios"' in html and 'id="planes"' in html
          and 'supabase-js@2.45.4' in html, 'la página carga la cuenta, Mis picks y los planes')
    check(all(os.path.exists(os.path.join('web', f)) for f in ('terminos.html', 'privacidad.html'))
          and '800 911 2000' in open(os.path.join('web', 'terminos.html'), encoding='utf-8').read(),
          'términos (con +18 y juego responsable) y aviso de privacidad')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('function agrupar(' in app and 'grupos.map(tarjeta)' in app and '.sort().join' in app,
          'una tarjeta por partido (también «B vs A»), con sus apuestas dentro')
    ex = open('exportar_web.py', encoding='utf-8').read()
    check("'id': 'not.in.(%s)' % vivos" in ex and "'estado': 'eq.pendiente'" in ex and "'inicio': 'gt.'" in ex,
          'lo que el modelo retira antes de empezar se borra de la base (no se queda repetido)')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    check('python telegram_canales.py' in wf and 'PREMIUM_NIVELES' in wf,
          'el workflow manda a los canales y respeta el modo de pago')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
