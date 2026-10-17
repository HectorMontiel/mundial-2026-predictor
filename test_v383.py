#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v383: usuario y contraseña, Mi cuenta, códigos de regalo y VIP
con Mercado Pago (fundador $99 los primeros 50, $149, semestral $749).

Ejecutar:  python test_v383.py
"""
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def leer(*p):
    return open(os.path.join(*p), encoding='utf-8').read()


def probar():
    cu, html, cfg = leer('web', 'cuenta.js'), leer('web', 'index.html'), leer('web', 'config.js')
    sql = leer('supabase', 'v383_usuarios_vip.sql')
    check('id="f-entrar"' in html and 'id="f-crear"' in html and 'id="f-elegir"' in html and 'id="micuenta"' in html,
          'la página tiene entrar, crear cuenta, elegir usuario y Mi cuenta')
    check("FN + 'entrar'" in cu and 'setSession' in cu and "sb.auth.signUp" in cu and "options: { data: { usuario: u } }" in cu,
          'entrar con usuario (por el servidor) y registrarse con usuario')
    check("sb.rpc('canjear_codigo'" in cu and "FN + 'vip'" in cu and "sb.rpc('enlace_vip')" in cu,
          'canjear código, hacerse VIP y el enlace del VIP desde la cuenta')
    check('t.me/+' not in cfg and 't.me/+' not in html and 't.me/+' not in cu,
          'el enlace del grupo VIP ya no está en la página pública')
    check("revoke execute on function public.id_de_usuario(text) from public, anon, authenticated" in sql,
          'buscar el correo por usuario sólo lo puede el servidor')
    check("return 'ya usado'" in sql and 'make_interval(days => r.dias)' in sql, 'cada código sirve una vez y da sus días de VIP')
    check("50 - (select count(distinct usuario)" in sql and "('precio_fundador', '99')" in sql
          and "('precio_mensual', '149')" in sql and "('precio_semestral', '749')" in sql,
          'precios: fundador $99 para 50, $149 y semestral $749')
    check("admin or (plan = 'pro'" in sql and "case when es_admin then 0" in sql, 'el administrador es VIP y no gasta monedas')
    vip, wh = leer('supabase', 'functions', 'vip', 'index.ts'), leer('supabase', 'functions', 'mp-webhook', 'index.ts')
    check("status: 'pending'" in vip and 'external_reference: user.id' in vip and "currency_id: 'MXN'" in vip,
          'la suscripción se crea en Mercado Pago ligada al usuario, en pesos')
    check("mp('/preapproval/' + pre)" in wh and "s.status === 'authorized'" in wh and 'return ok();' in wh,
          'el aviso se comprueba preguntando a Mercado Pago y siempre contesta 200')
    tg = leer('telegram_canales.py')
    check("'Únete gratis durante el lanzamiento: %s'" not in tg, 'el canal gratis ya no publica el enlace del VIP')


if __name__ == '__main__':
    probar()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
