#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v379 — LOS DOS CANALES DE TELEGRAM DE SHARPICKS: GRATIS Y VIP.

El usuario: «quiero tener grupos de Telegram… dos modelos diferentes, uno
gratis y otro como el No Win, No Pay». Este script, detrás de cada pasada del
sitio (`sitio_web.yml`), manda a cada canal sólo lo NUEVO:

  · VIP (TELEGRAM_CHAT_VIP): los picks 💎 Diamante y 🔷 Platino en cuanto
    salen (de las próximas 18 h), agrupados por partido, y su resultado.
  · GRATIS (TELEGRAM_CHAT_GRATIS): POCO Y BUENO. El usuario, al ver el primer
    envío (70 picks de golpe): «siento que es mucho… no se entiende… en el
    gratis hay que dar combinadas con alta probabilidad, máximo 1,5, o una
    individual cada cierto tiempo». Tres horarios al día (9, 14 y 19 h de
    CDMX), UNA publicación en cada uno, alternando:
      🔗 la COMBINADA del día: 2 picks de partidos distintos, cuota total
         1,30-1,50, la de mayor probabilidad de acierto;
      🎯 el PICK del día: la sencilla más segura de las próximas horas;
    su resultado al terminar, y una vez al día «Ayer en el VIP: ✅ ❌».

Qué es VIP lo dice `TELEGRAM_VIP_NIVELES` (por defecto «Diamante,Platino»).
Para no repetir, lo enviado se apunta en Supabase (`telegram_enviados`, con la
clave de servicio). Sin el canal o sin la base, no manda nada: nunca falla.

v400 — AVISOS AL MOMENTO (el usuario: «el Telegram VIP no tiene ningún valor
añadido a comparación de la suscripción… que empiece a mandar notificaciones
en ambas, en el VIP más y mejores»). La app se CONSULTA; Telegram AVISA:
  VIP
    💰 errores de cuota en cuanto aparecen (una casa que paga de más suele
       corregir pronto: el que se entera tarde ya no la alcanza);
    ⏰ «ya es hora de apostar»: cada 💎/🔷 al abrir su ventana de 4 h antes del
       partido (v351-v352: fijar ahí acierta 82 % contra 79 % al pitido);
    ♻️ si retiramos o cambiamos algo que ya mandamos;
    🌙 resumen de la noche: verdes y rojas del día.
  GRATIS
    lo de siempre (3 publicaciones, error de muestra, «ayer en el VIP») y además
    ♻️ si se retira lo publicado, 🌙 el resumen de la noche y 🎉 al llegar a
    100 miembros, 5 códigos de VIP de regalo (una sola vez).

Ejecutar:  python telegram_canales.py [--seco]
"""
import datetime as dt
import html
import json
import logging
import os
import sys
from itertools import combinations
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger('telegram_canales')
DATOS = os.environ.get('WEB_DATOS', os.path.join('web', 'datos', 'hoy.json'))
PRIVADO = os.environ.get('WEB_PRIVADO', os.path.join('datos_privados', 'premium.json'))
SITIO = os.environ.get('SITIO_URL', 'https://sharpicks.pages.dev')
VIP_URL = os.environ.get('TELEGRAM_VIP_URL', 'https://t.me/+qqtEBbAClQwxYzYx')
HORAS_ANTES = 18
ICONO = {'Diamante': '💎', 'Platino': '🔷', 'Oro': '🥇', 'Plata': '🥈', 'Cuota alta': '💰'}
MAX_LEN = 3800
CDMX = dt.timezone(dt.timedelta(hours=-6))
# el canal gratis: horarios (hora de CDMX) y qué toca en cada uno
HORARIOS_GRATIS = ((9, 'combinada'), (14, 'pick'), (19, 'combinada'))
VENTANA_GRATIS_H = 8              # sólo partidos que empiezan en las próximas 8 h
COMB_MIN, COMB_MAX = 1.30, 1.50   # cuota total de la combinada (pedido del usuario)
PROB_MIN_GRATIS = 0.78            # cada pata (y la sencilla) con al menos esto medido
PIE = '\n\n<i>Juego responsable · +18 · %s</i>' % SITIO
VENTANA_APUESTA_H = 4             # v351: la hora para apostar
HORA_NOCHE = 22                   # 🌙 resumen del día (hora de CDMX)
META_MIEMBROS = int(os.environ.get('TG_META_MIEMBROS', '100'))
META_CODIGOS = 5
META_DIAS = int(os.environ.get('TG_META_DIAS', '7'))
# lo ya mandado con su texto (para poder avisar si se retira): {(pick, canal): fila}
_DETALLES: Dict[Tuple[str, str], Dict] = {}


def nivel(p: Dict) -> str:
    """El mismo nivel que la página (`web/app.js`, `nivel`)."""
    if p.get('tipo') == 'error':
        return 'Cuota alta'
    if p.get('elige'):
        return 'Diamante'
    pr = float(p.get('prob') or 0)
    return 'Platino' if pr >= 0.85 else ('Oro' if pr >= 0.80 else 'Plata')


def niveles_vip() -> Set[str]:
    v = os.environ.get('TELEGRAM_VIP_NIVELES') or 'Diamante,Platino,Cuota alta'   # vacío = lo de siempre
    return {x.strip().capitalize() for x in v.split(',') if x.strip()}


def _utc(s) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(s).replace(' ', 'T')[:19]).replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _cuando(p: Dict, ahora: dt.datetime) -> str:
    """«hoy 21:00», «mañana 09:30» o «18/10 13:00» (hora de CDMX)."""
    d = _utc(p.get('inicio'))
    if d is None:
        return ''
    loc, hoy = d.astimezone(CDMX), ahora.astimezone(CDMX).date()
    dias = (loc.date() - hoy).days
    pre = 'hoy' if dias == 0 else ('mañana' if dias == 1 else loc.strftime('%d/%m'))
    return '%s %s' % (pre, loc.strftime('%H:%M'))


# ---------- lo ya enviado (Supabase) ----------
def _sb():
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return None
    return url.rstrip('/') + '/rest/v1/telegram_enviados', {
        'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}


def ya_enviados() -> Optional[Set[Tuple[str, str, str]]]:
    """(pick, canal, tipo) ya mandados; None si no hay base (no se manda nada)."""
    sb = _sb()
    if sb is None:
        return None
    import requests
    desde = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=4)).isoformat()
    r = requests.get(sb[0], headers=sb[1], timeout=30,
                     params={'select': '*', 'enviado': 'gte.' + desde, 'limit': 20000})
    if not r.ok:
        logger.warning('[telegram] no se pudo leer lo enviado: %s', r.status_code)
        return None
    _DETALLES.clear()
    for x in r.json():
        if x.get('tipo') == 'pick' and x.get('texto'):
            _DETALLES[(x['pick'], x['canal'])] = x
    return {(x['pick'], x['canal'], x['tipo']) for x in r.json()}


def apuntar(filas: List[Tuple]) -> None:
    """(pick, canal, tipo) o, para los picks, (pick, canal, tipo, texto,
    partido, inicio): con el texto se puede avisar si luego se retira."""
    sb = _sb()
    if sb is None or not filas:
        return
    import requests
    h = dict(sb[1], Prefer='resolution=ignore-duplicates,return=minimal')
    filas = [tuple(f) + (None,) * (6 - len(f)) for f in filas]
    requests.post(sb[0], headers=h, timeout=30,
                  json=[{'pick': a, 'canal': b, 'tipo': c, 'texto': d, 'partido': e, 'inicio': f}
                        for a, b, c, d, e, f in filas])


def _cubre_pick(p: Dict, canal: str) -> Tuple:
    return (p['id'], canal, 'pick', p.get('apuesta'), p.get('partido'), p.get('inicio'))


# ---------- formato ----------
def _e(x) -> str:
    return html.escape(str(x if x is not None else ''))


def _apuesta(p: Dict) -> str:
    if p.get('tipo') == 'error':
        return '➜ %s · cuota <b>%.2f</b> · se cumple ~%d %% · paga %d %% de más%s' % (
            _e(p.get('apuesta')), float(p.get('cuota') or 0), round(100 * float(p.get('prob') or 0)),
            round(100 * float(p.get('ventaja') or 0)), (' en ' + _e(p.get('casa'))) if p.get('casa') else '')
    return '➜ %s · cuota <b>%.2f</b> · probabilidad %d %%' % (
        _e(p.get('apuesta')), float(p.get('cuota') or 0), round(100 * float(p.get('prob') or 0)))


def _cab_partido(p: Dict, ahora: dt.datetime, icono: str = '') -> str:
    liga = (' · ' + _e(p.get('liga'))) if p.get('liga') else ''
    return '%s<b>%s</b>%s · %s' % (icono + ' ' if icono else '', _e(p.get('partido')), liga, _cuando(p, ahora))


def _por_partido(ps: List[Dict], ahora: dt.datetime) -> List[str]:
    """Un bloque por partido con sus apuestas debajo (nunca el partido dos veces)."""
    g: Dict[str, List[Dict]] = {}
    for p in sorted(ps, key=lambda x: (str(x.get('inicio')), not x.get('elige'), -float(x.get('prob') or 0))):
        g.setdefault('%s|%s' % (p.get('partido'), str(p.get('inicio'))[:10]), []).append(p)
    out = []
    for grupo in g.values():
        mejor = max(grupo, key=lambda x: (bool(x.get('elige')), float(x.get('prob') or 0)))
        out.append(_cab_partido(grupo[0], ahora, ICONO[nivel(mejor)]) + '\n' +
                   '\n'.join('   ' + _apuesta(p) for p in grupo))
    return out


def _trozos(cab: str, bloques: List[str], pie: str = PIE, sep: str = '\n\n') -> List[str]:
    out, actual = [], cab
    for b in bloques:
        if len(actual) + len(b) + len(pie) + 2 > MAX_LEN:
            out.append(actual + pie)
            actual = cab + ' (sigue)'
        actual += sep + b
    out.append(actual + pie)
    return out


def _resultado_txt(ps: List[Dict]) -> Optional[str]:
    """'verde' / 'roja' cuando ya se sabe; None mientras falte alguna."""
    est = [p.get('estado') for p in ps]
    if any(e == 'roja' for e in est):
        return 'roja'
    if all(e in ('verde', 'nula') for e in est) and any(e == 'verde' for e in est):
        return 'verde'
    return None


# ---------- el canal VIP ----------
def _retirados(picks: List[Dict], enviados: Set, canal: str, ahora: dt.datetime) -> List[Dict]:
    """Lo que ya mandamos a `canal`, aún sin empezar, que el modelo ya NO da.
    Sólo con una pasada completa (si viniera casi vacía por un fallo, se callaría)."""
    pend = [p for p in picks if p.get('estado') == 'pendiente']
    if len(pend) < 30:
        return []
    vivos = {p['id'] for p in picks}
    out = []
    for (k, c), x in list(_DETALLES.items()):
        ini = _utc(x.get('inicio'))
        if c != canal or ini is None or ini <= ahora or (k, canal, 'retirado') in enviados:
            continue
        ids = k[5:].split('+') if k.startswith('comb:') else [k]
        if any(i not in vivos for i in ids):
            out.append(x)
    return out


def _avisos_retiro(picks: List[Dict], enviados: Set, canal: str, ahora: dt.datetime) -> List[Tuple[str, List]]:
    rs = _retirados(picks, enviados, canal, ahora)
    if not rs:
        return []
    t = ('♻️ <b>Cambio</b>: ya no recomendamos esto (el modelo lo retiró con los datos nuevos):\n\n' +
         '\n'.join('✖️ %s · %s' % (_e(x.get('texto')), _e(x.get('partido'))) for x in rs) +
         '\n\nSi ya lo metiste, tú decides; nosotros ya no lo contamos.' + PIE)
    return [(t, [(x['pick'], canal, 'retirado') for x in rs])]


def _dia_cdmx(p: Dict) -> Optional[str]:
    ini = _utc(p.get('inicio'))
    return ini.astimezone(CDMX).strftime('%Y-%m-%d') if ini else None


def _tres(enviados) -> Set:
    """(pick, canal, tipo) aunque llegue con el texto detrás (v400)."""
    return {tuple(x[:3]) for x in enviados}


def armar_vip(picks: List[Dict], enviados: Set, ahora: dt.datetime) -> List[Tuple[str, List]]:
    enviados = _tres(enviados)
    vip = niveles_vip()
    out = []
    loc = ahora.astimezone(CDMX)
    pend = [p for p in picks if nivel(p) in vip and p.get('estado') == 'pendiente'
            and _utc(p.get('inicio')) is not None and _utc(p.get('inicio')) > ahora
            and (p['id'], 'vip', 'pick') not in enviados]
    # 💰 errores de cuota: AL MOMENTO (se corrigen pronto)
    errs = [p for p in pend if p.get('tipo') == 'error'
            and _utc(p.get('inicio')) <= ahora + dt.timedelta(hours=HORAS_ANTES)]
    if errs:
        trozos = _trozos('💰 <b>Error de cuota · al momento</b>\nUna casa paga más de lo que vale; estas cuotas se '
                         'corrigen pronto. Riesgo alto: apuesta poco.', _por_partido(errs, ahora))
        out += [(t, []) for t in trozos[:-1]] + [(trozos[-1], [_cubre_pick(p, 'vip') for p in errs])]
    # ⏰ los demás, al abrir su ventana para apostar (4 h antes)
    ya = [p for p in pend if p.get('tipo') != 'error'
          and _utc(p.get('inicio')) <= ahora + dt.timedelta(hours=VENTANA_APUESTA_H)]
    if ya:
        trozos = _trozos('⏰ <b>Ya es hora de apostar</b> · empiezan en las próximas %d h' % VENTANA_APUESTA_H,
                         _por_partido(ya, ahora))
        out += [(t, []) for t in trozos[:-1]] + [(trozos[-1], [_cubre_pick(p, 'vip') for p in ya])]
    out += _avisos_retiro(picks, enviados, 'vip', ahora)
    res = [p for p in picks if nivel(p) in vip and p.get('estado') in ('verde', 'roja')
           and _utc(p.get('inicio')) is not None and _utc(p.get('inicio')) >= ahora - dt.timedelta(hours=8)
           and (p['id'], 'vip', 'resultado') not in enviados]
    if res:
        v = sum(1 for p in res if p.get('estado') == 'verde')
        lineas = ['%s %s · %s %s' % ('✅' if p.get('estado') == 'verde' else '❌', _e(p.get('apuesta')),
                                     _e(p.get('partido')), _e(p.get('marcador') or '')) for p in res]
        trozos = _trozos('📊 <b>Resultados VIP</b> · ✅ %d ❌ %d\n' % (v, len(res) - v), lineas, sep='\n')
        out += [(t, []) for t in trozos[:-1]] + [(trozos[-1], [(p['id'], 'vip', 'resultado') for p in res])]
    # 🌙 el resumen de la noche
    hoy = loc.strftime('%Y-%m-%d')
    if loc.hour >= HORA_NOCHE and ('noche:' + hoy, 'vip', 'resumen') not in enviados:
        dia = [p for p in picks if nivel(p) in vip and _dia_cdmx(p) == hoy]
        t = _resumen_noche('💎 <b>Hoy en el VIP</b>', dia)
        if t:
            out.append((t, [('noche:' + hoy, 'vip', 'resumen')]))
    return out


def _resumen_noche(titulo: str, ps: List[Dict]) -> Optional[str]:
    hechos = [p for p in ps if p.get('estado') in ('verde', 'roja')]
    if not hechos:
        return None
    v = sum(1 for p in hechos if p.get('estado') == 'verde')
    er = [p for p in hechos if p.get('tipo') == 'error']
    ev = sum(1 for p in er if p.get('estado') == 'verde')
    falta = sum(1 for p in ps if p.get('estado') in ('pendiente', 'vivo'))
    return ('🌙 %s: ✅ %d ❌ %d · %d %%' % (titulo, v, len(hechos) - v, round(100 * v / len(hechos))) +
            (('\n💰 Errores de cuota: ✅ %d ❌ %d' % (ev, len(er) - ev)) if er else '') +
            (('\n⏳ %d por terminar' % falta) if falta else '') +
            '\n\nTodo, verde y rojo, en el historial: %s' % SITIO)


# ---------- el canal gratis: poco y bueno ----------
def candidatas_gratis(picks: List[Dict], ahora: dt.datetime) -> List[Dict]:
    """v381 — sin los niveles del VIP (💎/🔷): si el gratis los diera, el VIP
    no tendría nada propio. Tampoco nada premium (su texto no es público)."""
    fin = ahora + dt.timedelta(hours=VENTANA_GRATIS_H)
    vip = niveles_vip()
    out = []
    for p in picks:
        ini = _utc(p.get('inicio'))
        if (p.get('estado') == 'pendiente' and p.get('cuota') and ini is not None
                and nivel(p) not in vip and not p.get('premium')
                and float(p.get('prob') or 0) >= PROB_MIN_GRATIS
                and ahora + dt.timedelta(minutes=20) < ini <= fin):
            out.append(p)
    return out


def mejor_combinada(cands: List[Dict]) -> Optional[List[Dict]]:
    """2 picks de partidos distintos, cuota total 1,30-1,50, máxima probabilidad
    conjunta (producto de lo medido: las patas de partidos distintos son
    independientes)."""
    mejor, pm = None, 0.0
    for a, b in combinations(cands, 2):
        if a.get('partido') == b.get('partido'):
            continue
        c = float(a['cuota']) * float(b['cuota'])
        if not (COMB_MIN <= c <= COMB_MAX):
            continue
        pj = float(a['prob']) * float(b['prob'])
        if pj > pm:
            mejor, pm = sorted([a, b], key=lambda x: str(x.get('inicio'))), pj
    return mejor


def mejor_sencilla(cands: List[Dict]) -> Optional[Dict]:
    """La más segura que pague algo (cuota ≥ 1,20); si no hay, la más segura."""
    con = [p for p in cands if float(p['cuota']) >= 1.20] or cands
    return max(con, key=lambda p: (float(p['prob']), float(p['cuota'])), default=None)


def armar_gratis(picks: List[Dict], enviados: Set, ahora: dt.datetime) -> List[Tuple[str, List]]:
    enviados = _tres(enviados)
    out = []
    loc = ahora.astimezone(CDMX)
    hoy = loc.strftime('%Y-%m-%d')
    toca = [(h, t) for h, t in HORARIOS_GRATIS if loc.hour >= h]
    if toca:
        h, tipo = toca[-1]
        clave = 'horario:%s:%02d' % (hoy, h)
        if (clave, 'gratis', 'horario') not in enviados:
            cands = candidatas_gratis(picks, ahora)
            comb = mejor_combinada(cands) if tipo == 'combinada' else None
            sen = None if comb else mejor_sencilla(cands)
            if comb:
                c = float(comb[0]['cuota']) * float(comb[1]['cuota'])
                pj = float(comb[0]['prob']) * float(comb[1]['prob'])
                t = ('🔗 <b>Combinada del día</b> · cuota total <b>%.2f</b> · probabilidad ~%d %%\n\n' % (c, round(100 * pj)) +
                     '\n\n'.join(_cab_partido(p, ahora) + '\n   ' + _apuesta(p) for p in comb) + PIE)
                out.append((t, [(clave, 'gratis', 'horario'),
                                ('comb:' + '+'.join(p['id'] for p in comb), 'gratis', 'pick',
                                 ' + '.join(str(p.get('apuesta')) for p in comb),
                                 ' / '.join(str(p.get('partido')) for p in comb), comb[0].get('inicio'))]))
            elif sen:
                t = ('🎯 <b>Pick del día</b>\n\n' + _cab_partido(sen, ahora) + '\n   ' + _apuesta(sen) + PIE)
                out.append((t, [(clave, 'gratis', 'horario'), _cubre_pick(sen, 'gratis')]))
            else:
                out.append(('', [(clave, 'gratis', 'horario')]))     # nada que valga: no se publica
    # el resultado de lo que se publicó
    por_id = {p['id']: p for p in picks}
    for (k, canal, tipo) in sorted(enviados):
        if canal != 'gratis' or tipo != 'pick' or (k, 'gratis', 'resultado') in enviados:
            continue
        ps = [por_id.get(i) for i in (k[5:].split('+') if k.startswith('comb:') else [k])]
        if not all(ps):
            continue
        r = _resultado_txt(ps)
        if r is None:
            continue
        que = 'Combinada' if len(ps) > 1 else 'Pick'
        t = ('%s <b>%s %s</b>\n' % ('✅' if r == 'verde' else '❌', que, 'cumplida' if r == 'verde' else 'fallada') +
             '\n'.join('%s %s · %s %s' % ('✅' if p.get('estado') == 'verde' else ('❌' if p.get('estado') == 'roja' else '➖'),
                                          _e(p.get('apuesta')), _e(p.get('partido')), _e(p.get('marcador') or ''))
                       for p in ps) + PIE)
        out.append((t, [(k, 'gratis', 'resultado')]))
    # v384 — a mediodía, los 1-2 errores de cuota «muestra» (los más probables)
    if loc.hour >= 12:
        clave = 'error-gratis:' + hoy
        mues = [p for p in picks if p.get('tipo') == 'error' and p.get('gratis') and p.get('estado') == 'pendiente'
                and (p['id'], 'gratis', 'pick') not in enviados]
        if mues and (clave, 'gratis', 'horario') not in enviados:
            t = ('💰 <b>Error de cuota del día</b>\nUna casa paga más de lo que vale. Riesgo alto: apuesta poco.\n\n' +
                 '\n\n'.join(_cab_partido(p, ahora) + '\n   ' + _apuesta(p) for p in mues) +
                 '\n\n🔒 En el VIP hay más todos los días.' + PIE)
            out.append((t, [(clave, 'gratis', 'horario')] + [(p['id'], 'gratis', 'pick') for p in mues]))
    # una vez al día: cómo le fue ayer al VIP (la prueba de que vale la pena)
    ayer = (loc - dt.timedelta(days=1)).strftime('%Y-%m-%d')
    clave = 'resumen-vip:' + ayer
    if loc.hour >= 9 and (clave, 'gratis', 'resumen') not in enviados:
        vip = niveles_vip()
        ps = [p for p in picks if nivel(p) in vip and p.get('estado') in ('verde', 'roja')
              and _utc(p.get('inicio')) is not None
              and _utc(p.get('inicio')).astimezone(CDMX).strftime('%Y-%m-%d') == ayer]
        if ps:
            v = sum(1 for p in ps if p.get('estado') == 'verde')
            # v383 — el enlace del VIP ya no se publica: se da en la app a quien le toca
            t = ('💎 <b>Ayer en el VIP</b>: ✅ %d ❌ %d · %d %% de acierto\n'
                 'Hazte VIP (o entra gratis con tu cuenta en el lanzamiento): %s' % (v, len(ps) - v, round(100 * v / len(ps)), SITIO))
            out.append((t, [(clave, 'gratis', 'resumen')]))
    out += _avisos_retiro(picks, enviados, 'gratis', ahora)
    # 🌙 la noche: lo que se publicó aquí y el total del día en la app
    if loc.hour >= HORA_NOCHE and ('noche:' + hoy, 'gratis', 'resumen') not in enviados:
        dia = [p for p in picks if _dia_cdmx(p) == hoy and p.get('tipo') != 'error']
        t = _resumen_noche('<b>Hoy en SharPicks</b> (todos los picks de la app)', dia)
        if t:
            out.append((t, [('noche:' + hoy, 'gratis', 'resumen')]))
    return out


def meta_miembros(chat: str, enviados: Set) -> Optional[Tuple[str, List]]:
    """🎉 Al llegar a META_MIEMBROS en el canal gratis, UNA vez: 5 códigos de
    VIP de META_DIAS días, creados en la base (`codigos_regalo`)."""
    clave = 'meta-miembros:%d' % META_MIEMBROS
    if not chat or (clave, 'gratis', 'regalo') in enviados:
        return None
    import bot_telegram as bt
    r, _ = bt._post('getChatMemberCount', timeout=20, json={'chat_id': chat})
    try:
        n = int(r.json().get('result')) if r is not None and r.ok else 0
    except Exception:
        n = 0
    if n < META_MIEMBROS:
        return None
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return None
    import requests
    import secrets
    abc = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    cods = ['SHARP-%s-%s' % (''.join(secrets.choice(abc) for _ in range(4)), ''.join(secrets.choice(abc) for _ in range(4)))
            for _ in range(META_CODIGOS)]
    rr = requests.post(url.rstrip('/') + '/rest/v1/codigos_regalo', timeout=30,
                       headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                                'Prefer': 'return=minimal'},
                       json=[{'codigo': c, 'dias': META_DIAS} for c in cods])
    if not rr.ok:
        logger.warning('[telegram] no se pudieron crear los códigos: %s %s', rr.status_code, rr.text[:200])
        return None
    t = ('🎉 <b>¡Ya somos %d en la comunidad!</b>\nPara celebrarlo regalamos <b>%d códigos de %d días de VIP</b>. '
         'El primero que canjee cada uno se lo queda: entra a %s → Mi cuenta → 🎁 Canjear código.\n\n%s' %
         (n, META_CODIGOS, META_DIAS, SITIO, '\n'.join('<code>%s</code>' % c for c in cods)) + PIE)
    return t, [(clave, 'gratis', 'regalo')]


def armar(picks: List[Dict], enviados: Set, ahora: Optional[dt.datetime] = None) -> Dict[str, List]:
    """{canal: [(texto, [(pick, canal, tipo) que cubre])]} con sólo lo nuevo."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    return {'vip': armar_vip(picks, enviados, ahora), 'gratis': armar_gratis(picks, enviados, ahora)}


def enviar_a(chat: str, texto: str) -> bool:
    import bot_telegram as bt
    r, motivo = bt._post('sendMessage', timeout=30, json={
        'chat_id': chat, 'text': texto, 'parse_mode': 'HTML', 'disable_web_page_preview': True})
    if r is not None and r.ok:
        return True
    logger.warning('[telegram] %s', motivo)
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    seco = '--seco' in sys.argv
    chats = {'vip': os.environ.get('TELEGRAM_CHAT_VIP'), 'gratis': os.environ.get('TELEGRAM_CHAT_GRATIS')}
    if not seco and (not os.environ.get('TELEGRAM_BOT_TOKEN') or not any(chats.values())):
        print('telegram: sin bot o sin canales (TELEGRAM_CHAT_VIP / TELEGRAM_CHAT_GRATIS): no se manda nada')
        return 0
    try:
        picks = json.load(open(DATOS, encoding='utf-8')).get('picks') or []
    except Exception as e:
        print('telegram: sin datos del sitio (%s)' % e)
        return 0
    # v381 — el texto real de lo premium (el fichero público lo lleva tapado)
    try:
        reales = json.load(open(PRIVADO, encoding='utf-8'))
        for p in picks:
            if p.get('id') in reales:
                p['apuesta'] = reales[p['id']]
    except Exception:
        pass
    enviados = set() if seco else ya_enviados()
    if enviados is None:
        print('telegram: sin la base no se sabe qué ya se mandó: no se manda nada')
        return 0
    lotes = armar(picks, enviados)
    if not seco:
        try:
            m = meta_miembros(chats.get('gratis'), enviados)
            if m:
                lotes['gratis'].append(m)
        except Exception as e:
            logger.warning('[telegram] meta de miembros: %s', e)
    for canal, msgs in lotes.items():
        for texto, cubre in msgs:
            if not texto:                      # horario sin nada que valga: sólo se apunta
                if not seco:
                    apuntar(cubre)
                continue
            if seco or not chats.get(canal):
                print('--- %s ---\n%s' % (canal, texto))
                continue
            if enviar_a(chats[canal], texto):
                apuntar(cubre)
    print('telegram: %s' % {k: len([m for m in v if m[0]]) for k, v in lotes.items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
