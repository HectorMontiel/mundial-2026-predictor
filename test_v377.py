#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v377: el sitio web nuevo (carpeta `web/`, fuera de Streamlit).

  1. `exportar_web` saca las «se mete» con las MISMAS funciones que la app y
     un id estable (el mismo pick no se duplica al subirlo a Supabase).
  2. Sin secretos de Supabase no sube nada ni falla.
  3. En la página nunca va la clave de servicio; el workflow publica el sitio.

Ejecutar:  python test_v377.py
"""
import json
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar():
    import exportar_web as ew
    a = {'fecha': '2026-10-16', 'partido': 'A vs B', 'apuesta': '⭐ Gana A'}
    b = dict(a, apuesta='Gana A')
    check(ew._id(a) == ew._id(b) and ew._id(a) != ew._id(dict(a, partido='A vs C')),
          'el id no cambia por la ⭐ y distingue partidos')
    f = ew._fila(dict(a, cuota='1.2', prob=0.861, elige=1, liga=None), 'verde', {'A vs B': 'MLS'})
    check(f['apuesta'] == 'Gana A' and f['cuota'] == 1.2 and f['elige'] is True
          and f['estado'] == 'verde' and f['liga'], 'la fila queda limpia (%s)' % f)
    for k in ('SUPABASE_URL', 'SUPABASE_SERVICE_KEY'):
        os.environ.pop(k, None)
    check(ew.subir_supabase([f]) == 0, 'sin secretos no sube nada ni falla')
    if os.path.exists('pronostico_dia.json'):
        r = ew.construir()
        ps = r['picks']
        check(isinstance(ps, list) and all({'id', 'estado', 'partido', 'apuesta'} <= set(p) for p in ps)
              and len({p['id'] for p in ps}) == len(ps),
              'con el precálculo real salen %d picks sin repetir' % len(ps))
        json.dumps(r, ensure_ascii=False)
    cfg = open(os.path.join('web', 'config.js'), encoding='utf-8').read()
    check('service_role' not in cfg.replace('«service_role»', '') and 'SUPABASE_SERVICE_KEY' not in cfg,
          'la página nunca lleva la clave de servicio')
    js = open(os.path.join('web', 'app.js'), encoding='utf-8').read()
    check('datos/hoy.json' in js and '/rest/v1/picks' in js, 'la página lee el fichero o la base')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    check('python exportar_web.py' in wf and 'deploy-pages' in wf and 'Precálculo del día' in wf,
          'el workflow saca los datos y publica el sitio detrás del precálculo')
    sql = open(os.path.join('web', 'supabase.sql'), encoding='utf-8').read()
    check('enable row level security' in sql and 'create table if not exists public.picks' in sql,
          'la base tiene la tabla picks con reglas de lectura')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
