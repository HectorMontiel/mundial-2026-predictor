#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v379 — LOS DOS CANALES DE TELEGRAM DE SHARPICKS: GRATIS Y VIP.

El usuario: «quiero tener grupos de Telegram… dos modelos diferentes, uno
gratis y otro como el No Win, No Pay». Este script, detrás de cada pasada del
sitio (`sitio_web.yml`), manda a cada canal sólo lo NUEVO:

  · VIP (TELEGRAM_CHAT_VIP): los picks 💎 Diamante y 🔷 Platino en cuanto
    salen (de las próximas 18 h) y su resultado al terminar.
  · GRATIS (TELEGRAM_CHAT_GRATIS): los 🥇 Oro y 🥈 Plata, TODOS los
    resultados (también los del VIP: es la prueba de que funciona) y el aviso
    de cuántos 💎 hay hoy en el VIP.

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
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger('telegram_canales')
DATOS = os.environ.get('WEB_DATOS', os.path.join('web', 'datos', 'hoy.json'))
SITIO = os.environ.get('SITIO_URL', 'https://sharpicks.pages.dev')
HORAS_ANTES = 18
ICONO = {'Diamante': '💎', 'Platino': '🔷', 'Oro': '🥇', 'Plata': '🥈'}
MAX_LEN = 3800


def nivel(p: Dict) -> str:
    """El mismo nivel que la página (`web/app.js`, `nivel`)."""
    if p.get('elige'):
        return 'Diamante'
    pr = float(p.get('prob') or 0)
    return 'Platino' if pr >= 0.85 else ('Oro' if pr >= 0.80 else 'Plata')


def niveles_vip() -> Set[str]:
    v = os.environ.get('TELEGRAM_VIP_NIVELES') or 'Diamante,Platino'   # vacío = lo de siempre
    return {x.strip().capitalize() for x in v.split(',') if x.strip()}


def _utc(s) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(s).replace(' ', 'T')[:19]).replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _hora(p: Dict) -> str:
    d = _utc(p.get('inicio'))
    if d is None:
        return ''
    return (d - dt.timedelta(hours=6)).strftime('%d/%m %H:%M')


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


# ---------- los mensajes ----------
def _linea_pick(p: Dict) -> str:
    return '%s <b>%s</b>\n    %s · cuota <b>%.2f</b> · acierta %d %% · %s' % (
        ICONO[nivel(p)], html.escape(str(p.get('apuesta'))), html.escape(str(p.get('partido'))),
        float(p.get('cuota') or 0), round(100 * float(p.get('prob') or 0)), _hora(p))


def _linea_resultado(p: Dict) -> str:
    return '%s %s %s · %s %s' % ('✅' if p.get('estado') == 'verde' else '❌', ICONO[nivel(p)],
                                 html.escape(str(p.get('apuesta'))), html.escape(str(p.get('partido'))),
                                 html.escape(str(p.get('marcador') or '')))


def _trozos(cab: str, lineas: List[str], pie: str = '') -> List[str]:
    out, actual = [], cab
    for ln in lineas:
        if len(actual) + len(ln) + len(pie) + 2 > MAX_LEN:
            out.append(actual + pie)
            actual = cab + ' (sigue)'
        actual += '\n' + ln
    out.append(actual + pie)
    return out


def armar(picks: List[Dict], enviados: Set, ahora: Optional[dt.datetime] = None) -> Dict[str, List]:
    """{canal: [(texto, [(pick, canal, tipo) que cubre])]} con sólo lo nuevo."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    vip = niveles_vip()
    out = {'vip': [], 'gratis': []}
    nuevos = {'vip': [], 'gratis': []}
    for p in picks:
        ini = _utc(p.get('inicio'))
        if p.get('estado') != 'pendiente' or ini is None or not (ahora < ini <= ahora + dt.timedelta(hours=HORAS_ANTES)):
            continue
        canal = 'vip' if nivel(p) in vip else 'gratis'
        if (p['id'], canal, 'pick') not in enviados:
            nuevos[canal].append(p)
    res = {'vip': [], 'gratis': []}
    for p in picks:
        ini = _utc(p.get('inicio'))
        # sólo lo de las últimas 8 h: la primera pasada no repasa días enteros
        if p.get('estado') not in ('verde', 'roja') or ini is None or ini < ahora - dt.timedelta(hours=8):
            continue
        for canal in (('vip', 'gratis') if nivel(p) in vip else ('gratis',)):
            if (p['id'], canal, 'resultado') not in enviados:
                res[canal].append(p)
    pie = '\n\n<i>Juego responsable · +18 · %s</i>' % SITIO
    for canal in ('vip', 'gratis'):
        ps = sorted(nuevos[canal], key=lambda x: (not x.get('elige'), str(x.get('inicio'))))
        if ps:
            cab = '🆕 <b>%s · picks nuevos</b>' % ('SharPicks VIP' if canal == 'vip' else 'SharPicks')
            for t in _trozos(cab, [_linea_pick(p) for p in ps], pie):
                out[canal].append((t, []))
            out[canal][-1] = (out[canal][-1][0], [(p['id'], canal, 'pick') for p in ps])
        rs = res[canal]
        if rs:
            v = sum(1 for p in rs if p.get('estado') == 'verde')
            cab = '📊 <b>Resultados</b> · ✅ %d ❌ %d' % (v, len(rs) - v)
            for t in _trozos(cab, [_linea_resultado(p) for p in rs], pie):
                out[canal].append((t, []))
            out[canal][-1] = (out[canal][-1][0], [(p['id'], canal, 'resultado') for p in rs])
    # el aviso del VIP en el canal gratis (una vez por cada lote de 💎 nuevos)
    n_vip = len(nuevos['vip'])
    if n_vip:
        out['gratis'].append(('🔒 Hay <b>%d picks nuevos</b> 💎🔷 en el VIP para las próximas horas.\n'
                              'Velos en %s' % (n_vip, SITIO), []))
    return out


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
    enviados = set() if seco else ya_enviados()
    if enviados is None:
        print('telegram: sin la base no se sabe qué ya se mandó: no se manda nada')
        return 0
    lotes = armar(picks, enviados)
    for canal, msgs in lotes.items():
        for texto, cubre in msgs:
            if seco or not chats.get(canal):
                print('--- %s ---\n%s' % (canal, texto))
                continue
            if enviar_a(chats[canal], texto):
                apuntar(cubre)
    print('telegram: %s' % {k: len(v) for k, v in lotes.items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
