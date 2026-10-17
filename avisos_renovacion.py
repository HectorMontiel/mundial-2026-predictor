# -*- coding: utf-8 -*-
"""
v395 — AVISO ANTES DE CADA RENOVACIÓN DEL VIP.

El usuario: «por ley en México tienes que avisar unos días antes de que está
por renovarse». Cada suscripción que se va a volver a cobrar (`renueva`, estado
`authorized`) recibe UN correo `DIAS` días antes de su `proximo_cobro`, con la
fecha, el monto y cómo cancelar. `avisado_para` guarda la fecha de la que ya se
avisó: cada renovación se avisa una sola vez, aunque esto corra cada hora.

La página además lo enseña dentro de «Mi cuenta» los mismos 7 días
(`cuenta.js`), así que el aviso no depende sólo del correo.

El correo sale por Brevo (`BREVO_API_KEY`, remitente verificado en
`BREVO_REMITENTE`). Sin la clave no se marca nada como avisado: en cuanto se
ponga, se avisa lo pendiente.

Uso (en `sitio_web.yml`):  python avisos_renovacion.py
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DIAS = 7
SITIO = 'https://sharpicks.pages.dev'
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']


def _fecha(iso: str) -> str:
    f = dt.datetime.fromisoformat(str(iso).replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=-6)))
    return '%d de %s de %d' % (f.day, MESES[f.month - 1], f.year)


def por_avisar(subs: List[Dict], ahora: dt.datetime) -> List[Dict]:
    """Las que renuevan dentro de `DIAS` días y aún no se avisaron para ESA fecha."""
    fuera = []
    for s in subs:
        if not s.get('renueva') or s.get('estado') != 'authorized' or not s.get('proximo_cobro'):
            continue
        f = dt.datetime.fromisoformat(str(s['proximo_cobro']).replace('Z', '+00:00'))
        if not (ahora < f <= ahora + dt.timedelta(days=DIAS)):
            continue
        if s.get('avisado_para') and str(s['avisado_para'])[:16] == str(s['proximo_cobro'])[:16]:
            continue
        fuera.append(s)
    return fuera


def correo(s: Dict) -> Dict[str, str]:
    fecha = _fecha(s['proximo_cobro'])
    periodo = '6 meses' if s.get('tipo') == 'semestral' else '1 mes'
    monto = '$%s MXN' % ('{:,.0f}'.format(float(s.get('precio') or 0)))
    por = 'Stripe' if str(s.get('id', '')).startswith('stripe:') else 'Mercado Pago'
    asunto = 'Tu VIP de SharPicks se renueva el %s' % fecha
    html = (
        '<p>Hola:</p>'
        '<p>Te avisamos con anticipación: tu suscripción <b>SharPicks VIP (%s)</b> se renovará '
        'automáticamente el <b>%s</b> y se cobrarán <b>%s</b> (IVA incluido) con %s.</p>'
        '<p>Si quieres seguir, no tienes que hacer nada. Si <b>no</b> quieres que se renueve, '
        'cancélala antes de esa fecha en <a href="%s/?cuenta=1">Mi cuenta → Cancelar renovación</a>. '
        'Seguirás siendo VIP hasta el final de lo que ya pagaste.</p>'
        '<p>— SharPicks</p>' % (periodo, fecha, monto, por, SITIO))
    return {'asunto': asunto, 'html': html}


def _sb():
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return None
    return url.rstrip('/'), {'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}


def _email_de(sb, usuario: str) -> Optional[str]:
    import requests
    r = requests.get(sb[0] + '/auth/v1/admin/users/' + usuario, headers=sb[1], timeout=20)
    return (r.json() or {}).get('email') if r.ok else None


def enviar(para: str, c: Dict[str, str]) -> bool:
    import requests
    k, de = os.environ.get('BREVO_API_KEY'), os.environ.get('BREVO_REMITENTE')
    if not k or not de:
        return False
    r = requests.post('https://api.brevo.com/v3/smtp/email', timeout=20,
                      headers={'api-key': k, 'Content-Type': 'application/json', 'accept': 'application/json'},
                      json={'sender': {'name': 'SharPicks', 'email': de}, 'to': [{'email': para}],
                            'subject': c['asunto'], 'htmlContent': c['html']})
    if not r.ok:
        logger.warning('[avisos] Brevo %s: %s', r.status_code, r.text[:200])
    return r.ok


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sb = _sb()
    if sb is None:
        print('avisos: sin la base')
        return 0
    import requests
    r = requests.get(sb[0] + '/rest/v1/suscripciones', headers=sb[1], timeout=30,
                     params={'select': '*', 'estado': 'eq.authorized', 'renueva': 'eq.true', 'limit': 5000})
    if not r.ok:
        print('avisos: no se pudo leer (%s)' % r.status_code)
        return 0
    pend = por_avisar(r.json(), dt.datetime.now(dt.timezone.utc))
    if pend and not os.environ.get('BREVO_API_KEY'):
        print('avisos: %d renovaciones por avisar, pero falta BREVO_API_KEY (se ven en la app)' % len(pend))
        return 0
    hechos = 0
    for s in pend:
        para = _email_de(sb, s['usuario'])
        if para and enviar(para, correo(s)):
            requests.patch(sb[0] + '/rest/v1/suscripciones', headers=dict(sb[1], Prefer='return=minimal'),
                           params={'id': 'eq.' + s['id']}, json={'avisado_para': s['proximo_cobro']}, timeout=20)
            hechos += 1
    print('avisos: %d de %d avisados' % (hechos, len(pend)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
