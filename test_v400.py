#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v399-v400: «lo que metería la IA» con verde o roja, sus
probabilidades medidas, y los avisos de Telegram (VIP y gratis).

Ejecutar:  python test_v400.py
"""
import datetime as dt
import os

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def probar_liquidar():
    import ia_gemini as ia
    L = lambda a, g, k=None, t=None: ia.liquidar(a, 'América', 'Pumas', g, k, t)
    check(L('Gana América', (2, 1)) is True and L('Gana Pumas', (2, 1)) is False and L('Empate', (1, 1)) is True,
          'ganador y empate')
    check(L('América o empate', (1, 1)) is True and L('Pumas o empate', (2, 0)) is False, 'doble oportunidad')
    check(L('Goles: Más de 2.5', (2, 1)) is True and L('Goles: Menos de 2.5', (2, 1)) is False, 'goles totales')
    check(L('Goles Pumas: Más de 0.5', (2, 0)) is False and L('Goles América: Más de 1.5', (2, 0)) is True, 'goles de un equipo')
    check(L('Ambos anotan: Sí', (1, 1)) is True and L('Ambos anotan: No', (1, 1)) is False, 'ambos anotan')
    check(L('Córners: Más de 8.5', (0, 0), 10) is True and L('Córners: Más de 8.5', (0, 0)) is None
          and L('Tarjetas: Menos de 4.5', (0, 0), None, 3) is True, 'córners y tarjetas (sin el dato real, no se califica aún)')
    check(L('Algo raro que no entiendo', (1, 0)) is None and L('Gana Chivas', (1, 0)) is None,
          'lo que no se entiende no se cuenta ni verde ni roja')
    sql = open(os.path.join('supabase', 'v399_ia_medicion.sql'), encoding='utf-8').read()
    check('ok_mejor boolean' in sql and 'create or replace view public.ia_medicion' in sql, 'la vista de calibración está guardada')
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check("from('ia_medicion')" in cu and '¿Sus probabilidades son honestas?' in cu and 'Lo que metería la IA' in cu,
          'el historial enseña lo que metería y si sus probabilidades son honestas')


def _p(i, **kw):
    d = {'id': 'id%d' % i, 'partido': 'A%d vs B%d' % (i, i), 'apuesta': 'Gana A%d' % i, 'cuota': 1.15,
         'prob': 0.86, 'elige': True, 'estado': 'pendiente', 'inicio': '2026-10-17 22:00:00', 'tipo': 'pick'}
    d.update(kw)
    return d


def probar_telegram():
    import telegram_canales as tc
    os.environ.pop('TELEGRAM_VIP_NIVELES', None)
    ahora = dt.datetime(2026, 10, 17, 19, 0, tzinfo=dt.timezone.utc)          # 13:00 CDMX
    relleno = [_p(100 + i, elige=False, prob=0.7, inicio='2026-10-18 20:00:00') for i in range(40)]
    ps = [_p(1, inicio='2026-10-17 22:00:00'),                                  # en 3 h: ventana abierta
          _p(2, inicio='2026-10-18 03:00:00'),                                  # en 8 h: aún no
          _p(3, tipo='error', apuesta='Gana B3', cuota=2.4, prob=0.45, ventaja=0.12, inicio='2026-10-18 03:00:00')] + relleno
    vip = '\n'.join(t for t, _ in tc.armar_vip(ps, set(), ahora))
    check('Ya es hora de apostar' in vip and 'Gana A1' in vip and 'Gana A2' not in vip,
          '⏰ el 💎 se manda al abrir su ventana de 4 h, no antes')
    check('Error de cuota · al momento' in vip and 'Gana B3' in vip, '💰 el error de cuota sale al momento, aunque falten 8 h')
    # ♻️ algo ya mandado que el modelo retiró
    tc._DETALLES.clear()
    tc._DETALLES[('idX', 'vip')] = {'pick': 'idX', 'canal': 'vip', 'texto': 'Goles: Menos de 2.5', 'partido': 'X vs Y',
                                    'inicio': '2026-10-17 23:00:00'}
    msgs = tc.armar_vip(ps, {('id1', 'vip', 'pick'), ('id3', 'vip', 'pick')}, ahora)
    r = [t for t, c in msgs if 'Cambio' in t]
    check(r and 'Goles: Menos de 2.5' in r[0], '♻️ se avisa lo que ya mandamos y el modelo retiró')
    check(not [t for t, _ in tc.armar_vip(ps[:3], {('id1', 'vip', 'pick'), ('id3', 'vip', 'pick')}, ahora) if 'Cambio' in t],
          'con una pasada casi vacía (un fallo) no se avisa nada')
    tc._DETALLES.clear()
    # 🌙 la noche
    noche = dt.datetime(2026, 10, 18, 4, 30, tzinfo=dt.timezone.utc)           # 22:30 CDMX del 17
    hechos = [_p(5, estado='verde', inicio='2026-10-17 20:00:00'), _p(6, estado='roja', inicio='2026-10-17 21:00:00')]
    n = [t for t, _ in tc.armar_vip(hechos, set(), noche) if '🌙' in t]
    check(n and '✅ 1 ❌ 1' in n[0], '🌙 el VIP recibe el resumen de la noche')
    g = [t for t, _ in tc.armar_gratis(hechos, set(), noche) if '🌙' in t]
    check(g and 'Hoy en SharPicks' in g[0], '🌙 y el gratis también')
    src = open('telegram_canales.py', encoding='utf-8').read()
    check("getChatMemberCount" in src and 'META_MIEMBROS = int(os.environ.get(\'TG_META_MIEMBROS\', \'100\'))' in src
          and 'codigos_regalo' in src and 'META_CODIGOS = 5' in src,
          '🎉 a los 100 miembros del gratis, 5 códigos de VIP (una sola vez)')
    sql = open(os.path.join('supabase', 'v400_telegram.sql'), encoding='utf-8').read()
    check('add column if not exists texto' in sql, 'lo mandado se guarda con su texto (para el ♻️)')


def probar_comentarios():
    import comentarios_correo as cc
    h = cc.cuerpo([{'tipo': 'falla', 'creado': '2026-10-17T20:00:00', 'texto': 'No abre <b>x</b>', 'correo': 'a@b.mx'}])
    check('🐞 Algo no funciona' in h and '&lt;b&gt;' in h and 'mailto:a@b.mx' in h, 'el correo trae el comentario (escapado) y a quién responder')
    html = open(os.path.join('web', 'index.html'), encoding='utf-8').read()
    cu = open(os.path.join('web', 'cuenta.js'), encoding='utf-8').read()
    check('id="f-comentario"' in html and 'data-ir-comentarios' in html and "sb.from('comentarios').insert" in cu,
          'la página tiene «¿Qué mejorarías?» (en Planes y desde la Ayuda)')
    check('por tiempo limitado' not in html, 'ya no se promete que con cuenta gratis se ven los 💎')
    wf = open(os.path.join('.github', 'workflows', 'sitio_web.yml'), encoding='utf-8').read()
    sql = open(os.path.join('supabase', 'v401_comentarios.sql'), encoding='utf-8').read()
    hardening = open(os.path.join('supabase', 'v402_bughunter_hardening.sql'), encoding='utf-8').read()
    edge = open(os.path.join('supabase', 'functions', 'comentario', 'index.ts'), encoding='utf-8').read()
    check('python comentarios_correo.py' in wf and 'for insert to anon, authenticated' in sql and 'for select' not in sql
          and 'revoke insert on public.comentarios from anon, authenticated' in hardening
          and "rpc('registrar_comentario'" in edge,
          'los comentarios pasan por Edge Function con rate limit y no se leen desde la web')


if __name__ == '__main__':
    probar_comentarios()
    probar_liquidar()
    probar_telegram()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
