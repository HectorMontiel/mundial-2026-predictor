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
                     params={'select': 'pick,canal,tipo', 'enviado': 'gte.' + desde, 'limit': 20000})
    if not r.ok:
        logger.warning('[telegram] no se pudo leer lo enviado: %s', r.status_code)
        return None
    return {(x['pick'], x['canal'], x['tipo']) for x in r.json()}


def apuntar(filas: List[Tuple[str, str, str]]) -> None:
    sb = _sb()
    if sb is None or not filas:
        return
    import requests
    h = dict(sb[1], Prefer='resolution=ignore-duplicates,return=minimal')
    requests.post(sb[0], headers=h, timeout=30,
                  json=[{'pick': a, 'canal': b, 'tipo': c} for a, b, c in filas])


# ---------- formato ----------
def _e(x) -> str:
    return html.escape(str(x if x is not None else ''))


def _apuesta(p: Dict) -> str:
    if p.get('tipo') == 'error':
        return '➜ %s · cuota <b>%.2f</b> · se cumple ~%d %% · paga %d %% de más%s' % (
            _e(p.get('apuesta')), float(p.get('cuota') or 0), round(100 * float(p.get('prob') or 0)),
            round(100 * float(p.get('ventaja') or 0)), (' en ' + _e(p.get('casa'))) if p.get('casa') else '')
    return '➜ %s · cuota <b>%.2f</b> · acierta %d %%' % (
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
def armar_vip(picks: List[Dict], enviados: Set, ahora: dt.datetime) -> List[Tuple[str, List]]:
    vip = niveles_vip()
    out = []
    nuevos = [p for p in picks if nivel(p) in vip and p.get('estado') == 'pendiente'
              and _utc(p.get('inicio')) is not None
              and ahora < _utc(p.get('inicio')) <= ahora + dt.timedelta(hours=HORAS_ANTES)
              and (p['id'], 'vip', 'pick') not in enviados]
    if nuevos:
        trozos = _trozos('🆕 <b>SharPicks VIP · picks nuevos</b>', _por_partido(nuevos, ahora))
        out += [(t, []) for t in trozos[:-1]] + [(trozos[-1], [(p['id'], 'vip', 'pick') for p in nuevos])]
    res = [p for p in picks if nivel(p) in vip and p.get('estado') in ('verde', 'roja')
           and _utc(p.get('inicio')) is not None and _utc(p.get('inicio')) >= ahora - dt.timedelta(hours=8)
           and (p['id'], 'vip', 'resultado') not in enviados]
    if res:
        v = sum(1 for p in res if p.get('estado') == 'verde')
        lineas = ['%s %s · %s %s' % ('✅' if p.get('estado') == 'verde' else '❌', _e(p.get('apuesta')),
                                     _e(p.get('partido')), _e(p.get('marcador') or '')) for p in res]
        trozos = _trozos('📊 <b>Resultados VIP</b> · ✅ %d ❌ %d\n' % (v, len(res) - v), lineas, sep='\n')
        out += [(t, []) for t in trozos[:-1]] + [(trozos[-1], [(p['id'], 'vip', 'resultado') for p in res])]
    return out


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
                t = ('🔗 <b>Combinada del día</b> · cuota total <b>%.2f</b> · acierta ~%d %%\n\n' % (c, round(100 * pj)) +
                     '\n\n'.join(_cab_partido(p, ahora) + '\n   ' + _apuesta(p) for p in comb) + PIE)
                out.append((t, [(clave, 'gratis', 'horario'),
                                ('comb:' + '+'.join(p['id'] for p in comb), 'gratis', 'pick')]))
            elif sen:
                t = ('🎯 <b>Pick del día</b>\n\n' + _cab_partido(sen, ahora) + '\n   ' + _apuesta(sen) + PIE)
                out.append((t, [(clave, 'gratis', 'horario'), (sen['id'], 'gratis', 'pick')]))
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
    return out


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
