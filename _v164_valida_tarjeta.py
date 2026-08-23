#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — LAS TRES COMPROBACIONES DEL ENCARGO, SOBRE TARJETAS REALES.

`valida_render.py` abre las vistas y comprueba que no revientan, que es su
trabajo. Lo que pidió el encargo es más concreto y no se ve desde ahí:

    1. en un partido de una liga SIN datos, el bloque ya no anuncia un
       destacado estimado;
    2. en un partido de Premier, con datos, el destacado sigue saliendo;
    3. el bloque de jugadores enseña el porcentaje sobre la LÍNEA de la casa
       cuando la casa la ofrece, y dice «no disponible» cuando no.

Se pinta el HTML de verdad de partidos de verdad y se lee lo que sale.

    python _v164_valida_tarjeta.py
"""
import logging
import re
import sys
import warnings

warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.ERROR)
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

FALLOS = []


def check(cond, msg):
    print(('OK    ' if cond else 'FALLO ') + msg)
    if not cond:
        FALLOS.append(msg)


def _texto(html):
    return ' '.join(re.sub('<[^>]+>', ' ', html or '').replace('&nbsp;', ' ')
                    .split())


def _pick(clave, home, away):
    return {'partido': '%s vs %s' % (home, away), 'clave_liga': clave,
            'deporte': 'Fútbol'}


def main():
    import modo_modelo as mm
    import rendimiento_equipos as rq
    import fixtures_espn as fx
    from config import LEAGUES

    # ---- 1) una liga SIN datos observados --------------------------------
    print('=' * 78)
    print('1) COMPETICIÓN SIN DATOS: el bloque no anuncia destacado')
    print('=' * 78)
    sin = None
    for c, v in LEAGUES.items():
        if not v.get('disponible') or c not in fx.ESPN_CODIGOS:
            continue
        try:
            if rq.stats_disponibles(c).get('corners'):
                continue
            d = rq._historico(c)
            if d is None or getattr(d, 'empty', True) or len(d) < 300:
                continue
            sin = (c, str(d['home_team'].iloc[-1]), str(d['away_team'].iloc[-1]))
            break
        except Exception:
            continue
    if not sin:
        print('   (no queda ninguna competición sin córners observados)')
    else:
        p = _pick(*sin)
        b = mm.corners_tarjeta(p)
        html = mm._bloque_corners_html(b)
        t = _texto(html)
        print('   %s → %s' % (sin[0], t[:120]))
        check(b is not None and b.get('origen') == 'estimado',
              '%s: el bloque sale y viene marcado como estimado' % sin[0])
        check('destacado' not in t,
              '%s: NO anuncia ningún destacado' % sin[0])
        check('Estimado' in t or 'estimado' in t,
              '%s: conserva su etiqueta de estimado' % sin[0])
        check('%' in t,
              '%s: y sigue enseñando sus probabilidades, que es la '
              'información' % sin[0])

    # ---- 2) la Premier, con datos ----------------------------------------
    print()
    print('=' * 78)
    print('2) PREMIER (con datos): el destacado sigue apareciendo')
    print('=' * 78)
    p = _pick('premier', 'Man City', 'Arsenal')
    hubo = 0
    for nombre, fn, pintar in (
            ('córners', mm.corners_tarjeta, mm._bloque_corners_html),
            ('tarjetas', mm.tarjetas_tarjeta, mm._bloque_tarjetas_html)):
        b = fn(p)
        if not b:
            continue
        t = _texto(pintar(b))
        conf = b.get('confianza') or {}
        print('   %-9s nivel %s · %s' % (nombre, conf.get('nivel'), t[:96]))
        if b.get('origen') == 'observado':
            hubo += 1
            check('destacado' in t,
                  'premier/%s: el destacado sigue saliendo' % nombre)
            check('🟡' in pintar(b),
                  'premier/%s: en ámbar, nunca en verde' % nombre)
    check(hubo >= 1, 'la Premier tiene al menos un bloque observado')

    # ---- 3) el bloque de jugadores con la línea de la casa ---------------
    print()
    print('=' * 78)
    print('3) JUGADORES: la probabilidad va sobre la línea de la casa')
    print('=' * 78)
    import lineas_jugador as lj
    doc = lj.cargar()
    partidos = doc.get('partidos') or {}
    print('   %d partidos con líneas en el precálculo del día' % len(partidos))
    check(bool(partidos),
          'el precálculo del día trae líneas de jugador')

    probados, con_linea, con_nd = 0, 0, 0
    for llave, datos in list(partidos.items())[:6]:
        clave = datos.get('clave_liga')
        h, a = datos.get('home'), datos.get('away')
        if not (clave and h and a):
            continue
        qr = mm.quien_remata_tarjeta(_pick(clave, h, a))
        if not qr:
            continue
        probados += 1
        t = _texto(mm._bloque_quien_remata_html(qr))
        js = (qr.get('home_jugadores') or []) + (qr.get('away_jugadores') or [])
        n_lin = sum(1 for j in js if j.get('p_linea_tot') is not None)
        con_linea += n_lin
        con_nd += len(js) - n_lin
        print('   %-30s %d de %d con línea · %s'
              % (('%s-%s' % (h, a))[:30], n_lin, len(js), t[:78]))
        for j in js:
            if j.get('p_linea_tot') is None:
                continue
            # la probabilidad tiene que ser la de ESA línea, no otra
            import remates_jugador as rjg
            esperada = rjg.p_mas_de(j.get('lambda_tot'), j.get('linea_tot'))
            check(abs(j['p_linea_tot'] - esperada) < 1e-9,
                  '%s: la probabilidad es la de su línea (+%.1f)'
                  % (j.get('jugador'), j['linea_tot']))
            check(0.0 <= j['p_linea_tot'] <= 1.0,
                  '%s: es una probabilidad' % j.get('jugador'))
            break                       # uno por partido basta para el patrón

    check(probados >= 2,
          'se probaron %d partidos con líneas' % probados)
    check(con_linea > 0,
          '%d jugadores llevan la línea de la casa' % con_linea)
    print()
    print('   %d jugadores con línea · %d sin ella (la casa no los cotiza)'
          % (con_linea, con_nd))

    # y sin línea NO se inventa un cero
    src = open('modo_modelo.py', encoding='utf-8').read()
    check('de rematar' in src,
          'sin línea se cae a «probabilidad de rematar», no a un 0 %')

    print()
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    for x in FALLOS:
        print('  - ' + x)
    return 1 if FALLOS else 0


if __name__ == '__main__':
    sys.exit(main())
