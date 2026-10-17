#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v389: comprar monedas y precio por cuota."""
import os
FALLOS = []


def check(c, m):
    print(('OK   ' if c else 'FALLO') + ' ' + m)
    if not c:
        FALLOS.append(m)


def probar():
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check(("FN + 'monedas'" in cu or "conStripe ? 'stripe' : 'monedas'" in cu) and 'data-comprar' in cu and "from('paquetes')" in cu, 'Mi cuenta compra paquetes de monedas')
    check("from('precios_cuota')" in cu and "['Diamante', 'Platino', 'Cuota alta'].includes(n)" in cu,
          'el precio de un pick premium sale de su cuota; 🥇 y 🥈 gratis')
    m = open(os.path.join('supabase', 'functions', 'monedas', 'index.ts'), encoding='utf-8').read()
    check("checkout/preferences" in m and "'monedas|' + user.id" in m and 'notification_url' in m,
          'el cobro es un pago único de Mercado Pago ligado al usuario y al paquete')
    w = open(os.path.join('supabase', 'functions', 'mp-webhook', 'index.ts'), encoding='utf-8').read()
    check("mp('/v1/payments/' + id)" in w and "ref.startsWith('monedas|')" in w and "acreditar_compra" in w
          and "p.status === 'approved'" in w, 'el aviso comprueba el pago con Mercado Pago y acredita una vez')
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    check('3.00 o más</td><td>25' in html and '100 🪙 $49' in html, 'Planes enseña la tabla de precios y los paquetes')


def probar_horas():
    import errores_web as ew
    check(ew._hora('1792242000') == '2026-10-17 13:00:00' and ew._hora('2026-10-17T20:00:00') == '2026-10-17 20:00:00',
          'la hora en segundos se convierte a fecha (antes tumbaba el lote entero)')
    import exportar_web as xw
    f = xw._fila({'fecha': '2026-10-17', 'partido': 'A vs B', 'apuesta': 'Gana A', 'inicio': '1792242000'}, 'pendiente')
    g = xw._fila({'fecha': '2026-10-17', 'partido': 'A vs C', 'apuesta': 'Gana A', 'inicio': 'mañana'}, 'pendiente')
    check(f['inicio'] == '2026-10-17 13:00:00' and g['inicio'] is None, 'ninguna hora rara llega a la base')
    src = open('exportar_web.py', encoding='utf-8').read()
    check('uno por uno' in src, 'si un lote falla, se sube uno por uno')


if __name__ == '__main__':
    probar()
    probar_horas()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
