#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v377 — LO QUE VE EL SITIO WEB NUEVO (fuera de Streamlit).

El usuario: «quiero que hagamos eso [una app como BetFlipAi: base de datos +
página web] de manera gratuita». El sitio (carpeta `web/`) no calcula nada:
lee lo que deja este script, igual que la pantalla de Streamlit lee el
precálculo. Mismas funciones que la app (`modo_modelo.lista_por_acierto` y
`lista_finalizadas`), así el sitio y la app dicen lo mismo.

v378 — y a cada pick le pone su partido de ESPN (`espn_vivo`): la página lee
de ahí, cada 30 s, el marcador, el minuto y las estadísticas en vivo.

Escribe `web/datos/hoy.json` y, si hay credenciales de Supabase
(`SUPABASE_URL` y `SUPABASE_SERVICE_KEY`, secretos de GitHub), sube cada pick
a la tabla `picks` (ver `web/supabase.sql`). Sin credenciales sólo escribe el
fichero: nunca falla por eso.

Ejecutar:  python exportar_web.py
"""
import datetime as dt
import hashlib
import json
import logging
import os
import sys
from typing import Dict, List

logger = logging.getLogger('exportar_web')
SALIDA = os.environ.get('WEB_DATOS', os.path.join('web', 'datos', 'hoy.json'))
# v381 — el texto real de los picks premium, para el bot del canal VIP. Fuera
# de `web/` a propósito: lo de `web/` se publica y cualquiera lo leería.
PRIVADO = os.environ.get('WEB_PRIVADO', os.path.join('datos_privados', 'premium.json'))
CAMPOS = ('partido', 'inicio', 'fecha', 'deporte', 'liga', 'apuesta', 'cuota', 'prob',
          'elige', 'porque', 'resultado_c1', 'marcador',
          # v378 — para lo en vivo (ver `espn_vivo`)
          'espn', 'logo_h', 'logo_a', 'girado',
          # v379 — el modo de pago (`premium`)
          'premium',
          # v384 — errores de cuota (`errores_web`) y el contexto del partido
          'tipo', 'casa', 'ventaja', 'gratis', 'ctx')


def _id(p: Dict) -> str:
    """El mismo pick siempre con el mismo id (para no duplicarlo al subirlo)."""
    k = '|'.join(str(p.get(x) or '') for x in ('fecha', 'partido', 'apuesta'))
    return hashlib.sha1(k.replace('⭐ ', '').encode('utf-8')).hexdigest()[:20]


def _fila(p: Dict, estado: str, ligas: Dict = None) -> Dict:
    f = {k: p.get(k) for k in CAMPOS}
    if not f.get('liga') and ligas:
        f['liga'] = ligas.get(p.get('partido'))
    f['apuesta'] = str(f.get('apuesta') or '').replace('⭐ ', '').replace('🏆 ', '')
    f['estado'] = estado
    # v389 — la hora, siempre como fecha (nunca segundos sueltos ni texto raro):
    # un solo pick así hacía que Supabase rechazara el lote entero
    ini = str(f.get('inicio') or '').strip()
    if ini.replace('.', '', 1).isdigit():
        try:
            ini = dt.datetime.fromtimestamp(float(ini), dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ini = ''
    f['inicio'] = ini if len(ini) >= 10 and ini[:4].isdigit() and ini[4] == '-' else None
    # la tabla exige la fecha: sin ella, Supabase rechazaría el lote entero
    f['fecha'] = f.get('fecha') or str(f.get('inicio') or '')[:10] or None
    f['id'] = _id(p)
    f['elige'] = bool(f.get('elige'))
    f['gratis'] = bool(f.get('gratis'))
    f['tipo'] = f.get('tipo') or 'pick'
    for k in ('cuota', 'prob', 'ventaja'):
        try:
            f[k] = round(float(f[k]), 3) if f.get(k) is not None else None
        except (TypeError, ValueError):
            f[k] = None
    try:
        import nombres_ligas
        if f.get('liga'):
            f['liga'] = nombres_ligas.canonica(f['liga'], p.get('clave_liga') or '',
                                               f.get('deporte') or '')
    except Exception:
        pass
    return f


def construir() -> Dict:
    import modo_modelo as mm
    import partidos_jugados as pj
    import precalculo_dia as pc
    doc = pc.leer() or {}
    prons = (doc.get('datos') or {}).get('pronosticos') or []
    proximas = [_fila(p, 'pendiente') for p in mm.lista_por_acierto(prons)
                if not p.get('sigue')]
    jugadas = []
    hoy = dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date()
    for d in (hoy - dt.timedelta(days=1), hoy):
        lst = pj._para_la_vista(pj._leer_precalculo(d.isoformat(), permitir_viejo=True) or [])
        ligas = {x.get('partido'): x.get('liga') for x in lst}
        jugadas += [_fila(p, {'verde': 'verde', 'rojo': 'roja', 'nula': 'nula'}.get(
            p.get('resultado_c1'), 'vivo'), ligas) for p in mm.lista_finalizadas(lst)]
    # v384 — los errores de cuota (💰 «Cuota alta»): ver `errores_web`
    errs = []
    try:
        import errores_web
        errs = [_fila(e, e['estado']) for e in errores_web.errores(doc.get('datos') or {})]
    except Exception as e:
        logger.warning('[web] sin errores de cuota: %s', e)
    vistos, picks = set(), []
    for f in [x for x in jugadas + proximas + errs if x.get('fecha')]:          # lo jugado manda sobre lo pendiente
        if f['id'] not in vistos:
            vistos.add(f['id'])
            picks.append(f)
    # v384 — el contexto (forma, H2H, bajas) de cada partido de fútbol que aún no empieza
    try:
        import errores_web
        memo = {}
        claves = {p.get('partido'): p.get('clave_liga') for p in prons if p.get('clave_liga')}
        for f in picks:
            if f.get('estado') == 'pendiente' and f.get('deporte') == 'Fútbol':
                k = f.get('partido')
                if k not in memo:
                    memo[k] = errores_web.contexto(dict(f, clave_liga=f.get('clave_liga') or claves.get(k)))
                if memo[k]:
                    f['ctx'] = memo[k]
    except Exception as e:
        logger.warning('[web] sin contexto: %s', e)
    # v378 — el partido de ESPN de cada pick (marcador y estadísticas en vivo)
    try:
        import espn_vivo
        crudos = {f['id']: f for f in picks}
        espn_vivo.emparejar(list(crudos.values()))
        for f in picks:
            f['girado'] = bool(f.get('girado'))
    except Exception as e:
        logger.warning('[web] sin ESPN: %s', e)
    return {'generado': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
            'precalculo': doc.get('generado'), 'picks': picks}


def nivel(p: Dict) -> str:
    """El mismo nivel que la página (`web/app.js`) y Telegram (`telegram_canales`)."""
    if p.get('tipo') == 'error':
        return 'Cuota alta'
    if p.get('elige'):
        return 'Diamante'
    pr = float(p.get('prob') or 0)
    return 'Platino' if pr >= 0.85 else ('Oro' if pr >= 0.80 else 'Plata')


def premium(picks: List[Dict]) -> List[Dict]:
    """v379 — EL MODO DE PAGO (apagado en el lanzamiento: todo gratis).

    Con `PREMIUM_NIVELES` (p. ej. «Diamante»), el texto de esos picks que aún
    no empiezan SALE de lo público (el fichero de la página y la tabla
    `picks`, que lee cualquiera) y va sólo a `picks_premium`, que la base deja
    leer a quien lo desbloqueó o es Pro (`web/negocio.sql`). Esconderlo en la
    página no serviría: el fichero se ve en el navegador. Devuelve las filas
    para `picks_premium`."""
    nv = {x.strip().capitalize() for x in os.environ.get('PREMIUM_NIVELES', '').split(',') if x.strip()}
    secretos = []
    for p in picks:
        # v384 — lo que va al canal gratis es muestra: no se tapa
        p['premium'] = bool(nv) and nivel(p) in nv and p.get('estado') in ('pendiente', 'vivo') and not p.get('gratis')
        if p['premium']:
            secretos.append({'id': p['id'], 'apuesta': p['apuesta']})
            p['apuesta'] = '🔒 Pick %s' % nivel(p)
    return secretos


def subir_supabase(picks: List[Dict], secretos: List[Dict] = ()) -> int:
    """Sube (o actualiza) cada pick en Supabase. Devuelve cuántos; 0 sin claves."""
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key or not picks:
        return 0
    import requests
    filas = [dict(p, actualizado=dt.datetime.now(dt.timezone.utc).isoformat()) for p in picks]
    # v384 — un error de cuota deja de salir en la Capa 1 al empezar su partido:
    # su verde o roja se toma de lo anunciado y se pone a la fila que ya está
    try:
        import errores_web
        res = errores_web._resultados_anunciados()
        ya = {p['id'] for p in picks}
        r0 = requests.get(url.rstrip('/') + '/rest/v1/picks', timeout=30,
                          headers={'apikey': key, 'Authorization': 'Bearer ' + key},
                          params={'select': '*', 'tipo': 'eq.error', 'estado': 'eq.pendiente',
                                  'inicio': 'lt.' + dt.datetime.now(dt.timezone.utc).isoformat()})
        for x in (r0.json() if r0.ok else []):
            rr = res.get((x.get('partido'), x.get('apuesta')))
            if rr and x['id'] not in ya:
                x.update(estado={'verde': 'verde', 'rojo': 'roja'}.get(rr[0], 'pendiente'), marcador=rr[1],
                         actualizado=dt.datetime.now(dt.timezone.utc).isoformat())
                filas.append({k: x.get(k) for k in filas[0]} if filas else x)
    except Exception as e:
        logger.warning('[web] errores ya jugados: %s', e)
    n = 0
    hdr = {'apikey': key, 'Authorization': 'Bearer ' + key,
           'Prefer': 'resolution=merge-duplicates,return=minimal'}
    for i in range(0, len(filas), 200):
        r = requests.post(url.rstrip('/') + '/rest/v1/picks', json=filas[i:i + 200], timeout=30,
                          headers=hdr)
        if r.ok:
            n += len(filas[i:i + 200])
        else:
            logger.warning('[web] Supabase respondió %s: %s', r.status_code, r.text[:200])
            # v389 — si el lote falla, uno por uno: que un pick malo no tire a los otros 199
            for fila1 in filas[i:i + 200]:
                r1 = requests.post(url.rstrip('/') + '/rest/v1/picks', json=[fila1], timeout=30, headers=hdr)
                n += bool(r1.ok)
    # v379 — LO RETIRADO SE BORRA. Si el modelo cambia «Menos de 3.5» por
    # «Menos de 4.5», la vieja se quedaba «pendiente» en la base para siempre y
    # el partido salía dos veces. Se borran las pendientes de partidos que aún
    # no empiezan y que ya no están en esta pasada (sólo si la pasada trae
    # picks: una vacía por un fallo no debe vaciar la base).
    if n == len(filas) and filas:
        ahora = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        vivos = ','.join(sorted({p['id'] for p in picks}))
        r = requests.delete(url.rstrip('/') + '/rest/v1/picks', timeout=30, headers=hdr,
                            params={'estado': 'eq.pendiente', 'inicio': 'gt.' + ahora,
                                    'id': 'not.in.(%s)' % vivos})
        if not r.ok:
            logger.warning('[web] no se pudo limpiar lo retirado: %s %s', r.status_code, r.text[:200])
    if secretos:
        r = requests.post(url.rstrip('/') + '/rest/v1/picks_premium', json=list(secretos), timeout=30,
                          headers=hdr)
        if not r.ok:
            logger.warning('[web] picks premium: %s %s', r.status_code, r.text[:200])
    return n


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    r = construir()
    secretos = premium(r['picks'])
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    tmp = SALIDA + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=0)
    os.replace(tmp, SALIDA)
    # v384 — deportes con partidos hoy pero sin ningún pick (para decirlo en la página)
    try:
        import precalculo_dia as pc
        prons = ((pc.leer() or {}).get('datos') or {}).get('pronosticos') or []
        hoy = dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date().isoformat()
        con = {p.get('deporte') for p in r['picks'] if str(p.get('fecha') or '') == hoy}
        sin = {}
        for p in prons:
            dep = str(p.get('deporte') or '')
            if dep and dep not in con and str(p.get('fecha') or p.get('fecha_cdmx') or '')[:10] == hoy:
                sin[dep] = sin.get(dep, 0) + 1
        with open(os.path.join(os.path.dirname(SALIDA), 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump({'sin_pick': sin}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning('[web] sin meta: %s', e)
    try:
        os.makedirs(os.path.dirname(PRIVADO), exist_ok=True)
        with open(PRIVADO, 'w', encoding='utf-8') as f:
            json.dump({x['id']: x['apuesta'] for x in secretos}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning('[web] sin fichero privado: %s', e)
    n = subir_supabase(r['picks'], secretos)
    print('web: %d picks en %s; %d subidos a Supabase; %d premium' % (len(r['picks']), SALIDA, n, len(secretos)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
