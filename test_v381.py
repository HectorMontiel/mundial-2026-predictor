#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v381: lanzamiento con cuenta, VIP con valor propio, Google.

El usuario: «¿qué caso tiene la app y el Telegram VIP si en la app se ven los
VIP?». Ahora: los 💎/🔷 se ven en la app SÓLO CON CUENTA (gratis en el
lanzamiento); sin cuenta, candado. El canal gratis ya no da 💎/🔷. El texto
real de lo premium nunca va a lo público (va a `datos_privados/`, que sólo
lee el bot del VIP).

Ejecutar:  python test_v381.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import telegram_canales as tc
    os.environ.pop('TELEGRAM_VIP_NIVELES', None)
    ahora = dt.datetime(2026, 10, 17, 15, 0, tzinfo=dt.timezone.utc)
    base = {'estado': 'pendiente', 'cuota': 1.2, 'inicio': '2026-10-17 18:00:00'}
    ps = [dict(base, id='d', partido='A vs B', elige=True, prob=0.9),
          dict(base, id='p', partido='C vs D', prob=0.86),
          dict(base, id='o', partido='E vs F', prob=0.82),
          dict(base, id='x', partido='G vs H', prob=0.81, premium=True)]
    ids = {p['id'] for p in tc.candidatas_gratis(ps, ahora)}
    check(ids == {'o'}, 'el canal gratis no da 💎, 🔷 ni nada premium (%s)' % ids)
    src = open('telegram_canales.py', encoding='utf-8').read()
    check("reales = json.load(open(PRIVADO" in src, 'el VIP manda el texto real de lo premium')
    ex = open('exportar_web.py', encoding='utf-8').read()
    check("os.path.join('datos_privados', 'premium.json')" in ex and 'web' not in ex.split("PRIVADO = ")[1].split('\n')[0],
          'el texto real va a un fichero fuera de lo que se publica')
    check('datos_privados/' in open('.gitignore', encoding='utf-8').read(), 'y nunca se sube a git')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    check('upload-pages-artifact' in wf and 'path: web\n' in wf and 'pages deploy web ' in wf,
          'sólo se publica la carpeta web (no datos_privados)')
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check('Entra gratis y desbloquéalo' in cu and "provider: 'google'" in cu, 'sin cuenta, candado; y entrar con Google')
    check('LOGIN_GOOGLE: true' in open(os.path.join('web', 'config.js'), encoding='utf-8').read(), 'Google encendido')
    app = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('SPX.yo.desbloqueados[p.id]) || p.apuesta' in app, 'el premium se sigue en vivo con su texto real')
    check("'premium_con_cuenta'" in open(os.path.join('web', 'negocio.sql'), encoding='utf-8').read(),
          'la base deja ver lo premium a quien tiene cuenta (lanzamiento)')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
