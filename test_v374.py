#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v374 (hallazgos urgentes de la auditoría, Telegram).

  1. EL TOKEN NUNCA SALE en un error: un fallo de red de `requests` trae la
     URL con el token y la app lo pintaba.
  2. EL MENSAJE NO SE PARTE a la mitad de un formato al recortarlo (el «_»
     sin cerrar hacía que Telegram lo rechazara: 7, 9 y 13-oct) y, si aun así
     lo rechaza por formato, se reintenta sin formato.
  3. Si no llega con credenciales, el workflow sale en rojo; la pantalla dice
     el motivo real.
  4. El mensaje diario empieza por «✅ QUÉ METER HOY».

Ejecutar:  python test_v374.py
"""
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


class _R:
    def __init__(self, ok, code=200, desc=''):
        self.ok, self.status_code, self._d = ok, code, desc

    def json(self):
        return {'description': self._d}


def probar():
    import requests
    import bot_telegram as bt
    v = requests.post
    os.environ['TELEGRAM_BOT_TOKEN'] = '123456:ABCDEFGHIJKLMNOPQRSTUVWX'
    os.environ['TELEGRAM_CHAT_ID'] = '99'
    llamadas = []
    try:
        def _red(url, **kw):
            raise requests.ConnectionError('Max retries exceeded with url: %s' % url)
        requests.post = _red
        ok = bt.enviar('hola')
        check(not ok and 'ABCDEFGHIJKLMNOPQRSTUVWX' not in bt.motivo_fallo()
              and 'ConnectionError' in bt.motivo_fallo(),
              'un fallo de red no enseña el token (%s)' % bt.motivo_fallo())
        check('ABCDEFGHIJKLMNOPQRSTUVWX' not in bt.limpio(
            'https://api.telegram.org/bot123456:ABCDEFGHIJKLMNOPQRSTUVWX/sendMessage'),
            'limpio() tapa el token en cualquier texto')

        def _formato(url, **kw):
            llamadas.append(dict(kw.get('json') or {}))
            if 'parse_mode' in (kw.get('json') or {}):
                return _R(False, 400, "Bad Request: can't parse entities: offset 4159")
            return _R(True)
        requests.post = _formato
        check(bt.enviar('texto con _ suelto') and len(llamadas) == 2
              and 'parse_mode' not in llamadas[1],
              'si Telegram rechaza el formato, se reintenta sin formato y llega')
    finally:
        requests.post = v
        os.environ.pop('TELEGRAM_BOT_TOKEN', None)
        os.environ.pop('TELEGRAM_CHAT_ID', None)
    check('faltan TELEGRAM_BOT_TOKEN' in bt.motivo_fallo(), 'sin credenciales lo dice así')
    # el recorte
    r = {'actualizado': 'hoy', 'deportes_cubiertos': ['Fútbol'], 'pronosticos': [],
         'capa1': [{'partido': 'Equipo_%d vs Otro_%d' % (i, i), 'apuesta': 'Gana *X*',
                    'cuota': 2.0, 'prob': 0.5, 'ev': 0.03, 'deporte': 'Fútbol'} for i in range(400)]}
    try:
        m = bt.construir_mensaje(r)
    except Exception as e:
        m = ''
        check(False, 'construir_mensaje no revienta (%s)' % e)
    check(len(m) <= bt.MAX_LEN and m.endswith('_Juego responsable. Cuota justa = 1/probabilidad._'),
          'el mensaje largo se recorta en una línea y conserva el pie entero (%d)' % len(m))
    src = open('bot_telegram.py', encoding='utf-8').read()
    check('✅ *QUÉ METER HOY*' in src and '_fi_q.que_meter(' in src
          and 'sys.exit(1)' in src.split("if __name__ == '__main__':")[1],
          'el mensaje empieza por lo que se mete y el workflow sale en rojo si no llega')
    ui = open('dashboard_ui.py', encoding='utf-8').read()
    check('No se pudo enviar ({type(e).__name__}: {e})' not in ui
          and ui.count('__import__("bot_telegram").motivo_fallo()') >= 4,
          'la pantalla dice el motivo real y nunca el error crudo')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
