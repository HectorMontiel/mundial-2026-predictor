# -*- coding: utf-8 -*-
"""
v401 — LOS COMENTARIOS DE LA PÁGINA, A TU CORREO.

El usuario: «una parte de deja tu feedback… para saber qué puede mejorar de
la app. El correo debe de ser el mismo que está registrado para Brevo». La
página guarda cada comentario en `comentarios` (cualquiera escribe, nadie lee)
y esto, en cada pasada del sitio, manda los nuevos a BREVO_REMITENTE (el
correo verificado en Brevo) y los marca como enviados. Sin Brevo no marca
nada: en cuanto esté, llegan los pendientes.

Uso (en `sitio_web.yml`):  python comentarios_correo.py
"""
from __future__ import annotations

import html
import os
import sys

TIPOS = {'idea': '💡 Idea', 'falla': '🐞 Algo no funciona', 'otro': '💬 Otro'}


def cuerpo(cs) -> str:
    filas = []
    for c in cs:
        filas.append(
            '<div style="border:1px solid #ddd;border-radius:8px;padding:10px;margin:8px 0">'
            '<b>%s</b> · %s<br>%s<p style="white-space:pre-wrap">%s</p></div>' % (
                html.escape(TIPOS.get(c.get('tipo'), '💬')), html.escape(str(c.get('creado', ''))[:16].replace('T', ' ')),
                ('Responder a: <a href="mailto:%s">%s</a>' % (html.escape(c['correo']), html.escape(c['correo'])))
                if c.get('correo') else 'Sin correo para responder',
                html.escape(c.get('texto') or '')))
    return '<p>Comentarios nuevos en SharPicks:</p>' + ''.join(filas)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    k, de = os.environ.get('BREVO_API_KEY'), os.environ.get('BREVO_REMITENTE')
    if not url or not key:
        print('comentarios: sin la base')
        return 0
    import requests
    base = url.rstrip('/') + '/rest/v1/comentarios'
    hdr = {'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    try:
        r = requests.get(base, headers=hdr, timeout=30,
                         params={'select': '*', 'enviado': 'is.null', 'order': 'creado.asc', 'limit': 100})
    except requests.RequestException as exc:
        print('comentarios: ERROR consultando la base (%s)' % type(exc).__name__)
        return 1
    if not r.ok:
        print('comentarios: ERROR leyendo la base (HTTP %s)' % r.status_code)
        return 1
    try:
        cs = r.json()
    except ValueError:
        print('comentarios: ERROR la base devolvió una respuesta que no es JSON')
        return 1
    if not isinstance(cs, list):
        print('comentarios: ERROR la respuesta no es una lista')
        return 1
    if not cs:
        print('comentarios: lectura verificada, 0 nuevos')
        return 0
    if not k or not de:
        print('comentarios: %d nuevos, pero falta BREVO_API_KEY / BREVO_REMITENTE' % len(cs))
        return 0
    rr = requests.post('https://api.brevo.com/v3/smtp/email', timeout=30,
                       headers={'api-key': k, 'Content-Type': 'application/json', 'accept': 'application/json'},
                       json={'sender': {'name': 'SharPicks', 'email': de}, 'to': [{'email': de}],
                             'subject': '💬 %d comentario%s nuevo%s en SharPicks' % (len(cs), '' if len(cs) == 1 else 's', '' if len(cs) == 1 else 's'),
                             'htmlContent': cuerpo(cs),
                             **({'replyTo': {'email': cs[0]['correo']}} if len(cs) == 1 and cs[0].get('correo') else {})})
    if not rr.ok:
        print('comentarios: ERROR Brevo respondió %s %s' % (rr.status_code, rr.text[:200]))
        return 1
    import datetime as dt
    ids = ','.join(str(c['id']) for c in cs)
    try:
        marcado = requests.patch(base, headers=dict(hdr, Prefer='return=minimal'), timeout=30,
                                 params={'id': 'in.(%s)' % ids},
                                 json={'enviado': dt.datetime.now(dt.timezone.utc).isoformat()})
    except requests.RequestException as exc:
        print('comentarios: CORREO ENVIADO, pero falló el marcado en base (%s); revisar para evitar duplicados' % type(exc).__name__)
        return 1
    if not marcado.ok:
        print('comentarios: CORREO ENVIADO, pero la base no marcó los registros (HTTP %s); revisar para evitar duplicados' % marcado.status_code)
        return 1
    print('comentarios: %d enviados a tu correo y marcados en base' % len(cs))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
