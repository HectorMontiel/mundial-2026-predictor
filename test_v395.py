#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v395: Stripe, cancelar, renovar sí/no, aviso 7 días antes, y el PSG.

  · el usuario: «debe haber una sección de cancelar suscripción», «un botón de
    que se renueve cada mes» y «por ley en México tienes que avisar unos días
    antes de que está por renovarse»;
  · «Strasbourg vs Paris FC» era Strasbourg vs PSG: `normalizar` deja
    «Paris FC» en «paris» y la contención casaba «Paris Saint-Germain» con él.

Ejecutar:  python test_v395.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_nombres():
    import name_mapper as nm
    l1 = ['Paris FC', 'Paris SG', 'Strasbourg', 'Lille', 'Lyon']
    check(nm.mapear('Paris Saint-Germain', l1, contexto='t') == 'Paris SG', 'Paris Saint-Germain es el Paris SG, no el Paris FC')
    check(nm.mapear('Paris FC', l1, contexto='t') == 'Paris FC', 'y el Paris FC sigue siendo el Paris FC')
    check(nm.mapear('Lillestrom', l1, contexto='t') is None, 'Lillestrøm no es el Lille')
    check(nm.mapear('Deportivo', ['Deportivo Alavés', 'Deportivo de A Coruña'], contexto='t') == 'Deportivo de A Coruña',
          'el Deportivo no es el Alavés')
    check(nm.mapear('12 de Octubre', ['9 de Octubre', 'Olimpia'], contexto='t') is None
          and nm.mapear('River Plate (Asunción)', ['River Plate'], contexto='t') is None,
          'clubes distintos con nombre parecido no se juntan (Sudamericana)')
    check(nm.mapear('Man City', ['Manchester City', 'Manchester United'], contexto='t') == 'Manchester City'
          and nm.mapear('Roma', ['AS Roma', 'Lazio'], contexto='t') == 'AS Roma',
          'lo que ya casaba bien sigue igual (Man City, Roma)')


def probar_avisos():
    import avisos_renovacion as av
    ahora = dt.datetime(2026, 10, 17, 12, tzinfo=dt.timezone.utc)
    base = {'id': 'stripe:sub_1', 'usuario': 'u', 'tipo': 'mensual', 'precio': 99, 'renueva': True, 'estado': 'authorized'}
    en5 = (ahora + dt.timedelta(days=5)).isoformat()
    subs = [dict(base, proximo_cobro=en5),
            dict(base, id='b', proximo_cobro=(ahora + dt.timedelta(days=12)).isoformat()),   # falta mucho
            dict(base, id='c', proximo_cobro=en5, renueva=False),                            # no renueva
            dict(base, id='d', proximo_cobro=en5, avisado_para=en5)]                         # ya avisado
    check([s['id'] for s in av.por_avisar(subs, ahora)] == ['stripe:sub_1'],
          'se avisa 7 días antes, una vez por renovación y sólo si se va a cobrar')
    c = av.correo(subs[0])
    check('22 de octubre de 2026' in c['asunto'] and '$99' in c['html'] and 'Cancelar renovación' in c['html'] and 'Stripe' in c['html'],
          'el correo dice fecha, monto, quién cobra y cómo cancelar')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    check('python avisos_renovacion.py' in wf and 'BREVO_API_KEY' in wf, 'el aviso corre cada hora en el sitio')


def probar_pagina_y_funciones():
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check('data-sus="cancelar"' in cu and "FN + (t.dataset.sus ? 'suscripcion' : 'stripe')" in cu, 'hay botón de cancelar la renovación')
    check('id="vip-renovar" checked' in cu and 'renovar }' in cu, 'al contratar se elige renovar automáticamente o pagar sólo el periodo')
    check('data-metodo="stripe"' in cu and 'data-metodo="mp"' in cu, 'se elige pagar con Stripe (Apple Pay) o Mercado Pago')
    check('function avisoRenovacion()' in cu and 'DIAS_AVISO = 7' in cu, 'aviso dentro de la app 7 días antes')
    t = open(os.path.join('web', 'terminos.html'), encoding='utf-8').read()
    check('7 días antes de cada cobro' in t and 'Cancelar renovación' in t, 'los Términos explican la renovación y cómo cancelar')
    F = os.path.join('supabase', 'functions')
    w = open(os.path.join(F, 'stripe-webhook', 'index.ts'), encoding='utf-8').read()
    check('firmaValida' in w and "'HMAC'" in w and "await stripe('/checkout/sessions/' + obj.id)" in w,
          'el aviso de Stripe comprueba la firma y vuelve a preguntarle a Stripe')
    s = open(os.path.join(F, 'suscripcion', 'index.ts'), encoding='utf-8').read()
    check("cancel_at_period_end" in s and "status: 'cancelled'" in s, 'cancelar sirve con Stripe y con Mercado Pago')
    sql = open(os.path.join('supabase', 'v395_stripe_renovacion.sql'), encoding='utf-8').read()
    check('renueva boolean' in sql and 'avisado_para' in sql and 'revoke all on function public.sumar_vip' in sql,
          'el SQL está guardado y sumar_vip sólo lo usa el servidor')


if __name__ == '__main__':
    probar_nombres()
    probar_avisos()
    probar_pagina_y_funciones()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
