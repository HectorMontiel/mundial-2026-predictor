#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de la v413 — seguridad.

  · `entrar` con límite de intentos propio (por usuario y por IP): para Supabase
    todos los intentos salían de la función, su límite no protegía cada cuenta.
  · Cabeceras de seguridad en Cloudflare (CSP sin scripts en línea ni de otros
    dominios, nadie mete el sitio en otra página).
  · La librería de Supabase servida desde el sitio, con su huella (SRI).
  · La contraseña: 8+ caracteres, letras y números (la misma regla que Supabase).
  · Los .sql de referencia no se publican.

Ejecutar:  python test_v413.py
"""
import base64
import hashlib
import os
import re

FALLOS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FALLO') + ' ' + msg)
    if not cond:
        FALLOS.append(msg)


def leer(*p):
    return open(os.path.join(*p), encoding='utf-8').read()


def probar_entrar():
    sql = leer('supabase', 'v413_intentos_entrar.sql')
    check('enable row level security' in sql and 'revoke all on table public.intentos_entrar from public, anon, authenticated' in sql,
          'los intentos no los lee ni escribe nadie de fuera')
    check("< 5" in sql and "< 20" in sql and "interval '15 minutes'" in sql,
          '5 fallos por usuario y 20 por IP en 15 minutos')
    check('grant execute on function public.puede_entrar(text, text) to service_role' in sql
          and 'revoke all on function public.anotar_entrar(text, text, boolean) from public, anon, authenticated' in sql,
          'las funciones del límite sólo las llama el servidor')
    fn = leer('supabase', 'functions', 'entrar', 'index.ts')
    check("admin.rpc('puede_entrar'" in fn and '429' in fn and fn.count("rpc('anotar_entrar'") == 3,
          '`entrar` consulta el límite, anota fallos y aciertos, y responde 429')
    check("x-forwarded-for" in fn and 'Usuario o contraseña incorrectos.' in fn,
          'cuenta por la IP real y responde igual exista o no el usuario')


def probar_cabeceras():
    h = leer('web', '_headers')
    csp = re.search(r'Content-Security-Policy: (.+)', h).group(1)
    check("script-src 'self'" in csp and "'unsafe-inline'" not in csp.split('style-src')[0]
          and "'unsafe-eval'" not in csp, 'la CSP sólo deja correr scripts del sitio')
    check("frame-ancestors 'none'" in csp and 'X-Frame-Options: DENY' in h, 'nadie mete el sitio dentro de otra página')
    check("object-src 'none'" in csp and "base-uri 'self'" in csp and 'Permissions-Policy:' in h
          and 'Strict-Transport-Security:' in h, 'objetos, base, permisos y HTTPS cerrados')
    for host in ('lyfmyehvfywnjasinbne.supabase.co', 'site.api.espn.com', 'webws.365scores.com'):
        check(host in csp.split('connect-src')[1].split(';')[0], 'la CSP deja hablar con ' + host)
    html = leer('web', 'index.html')
    check(not re.search(r'<script>(?!</script>)', html) and not re.search(r'\son[a-z]+=', html),
          'index.html sin scripts ni eventos en línea')
    hosts = set(re.findall(r'https?://([a-z0-9.-]+)', leer('web', 'app.js') + leer('web', 'cuenta.js') + leer('web', 'fechas.js')))
    permitidos = {'lyfmyehvfywnjasinbne.supabase.co', 'site.api.espn.com', 'sharpicks.pages.dev', 't.me', 'fonts.googleapis.com', 'webws.365scores.com'}   # v429
    check(hosts <= permitidos, 'la página no llama a dominios fuera de la CSP: %s' % sorted(hosts - permitidos))
    wf = leer('.github', 'workflows', 'sitio_web.yml')
    check(wf.index('rm -f web/*.sql') < wf.index('pages deploy web'), 'los .sql no se publican')


def probar_libreria():
    html = leer('web', 'index.html')
    m = re.search(r'<script src="(vendor/[^"]+)" integrity="(sha384-[^"]+)"', html)
    check(bool(m) and 'cdn.jsdelivr.net' not in html, 'la librería de Supabase sale del sitio, con huella')
    if m:
        dig = base64.b64encode(hashlib.sha384(open(os.path.join('web', m.group(1)), 'rb').read()).digest()).decode()
        check(m.group(2) == 'sha384-' + dig, 'la huella coincide con el archivo servido')


def probar_contrasena():
    js = leer('web', 'cuenta.js')
    check('function contraDebil(c)' in js and js.count('contraDebil(c1)') >= 4,
          'registro y cambio de contraseña piden 8+ caracteres con letras y números')


def probar_v414():
    app = leer('web', 'app.js')
    check('function memoriaVista()' in app and 'restaurarVista(m)' in app and 'data-k="\' + esc(k)' in app,
          'v414: al repintar se reabren las secciones (Análisis IA, H2H) y el scroll no brinca')
    js = leer('web', 'cuenta.js')
    check("const PERFIL_GUARDADO = 'sharpicks-perfil'" in js and 'yo.perfil = perfilGuardado(yo.user.id)' in js
          and 'guardarPerfil(null)' in js, 'v414: el usuario y sus derechos salen al instante (y se borran al salir)')
    check(js.count('captchaToken: await esperarCaptcha()') == 3 and js.count('captcha: await esperarCaptcha()') == 2 and js.count('reiniciarCaptcha();') >= 4,
          'v414: el CAPTCHA va en entrar, crear cuenta y el enlace por correo')
    cfg, h, html = leer('web', 'config.js'), leer('web', '_headers'), leer('web', 'index.html')
    check("TURNSTILE_SITE_KEY: '0x4" in cfg and 'challenges.cloudflare.com/turnstile/v0/api.js' in html
          and "script-src 'self' https://challenges.cloudflare.com;" in h and 'frame-src https://challenges.cloudflare.com;' in h,
          'v414: el CAPTCHA de Cloudflare cabe en la CSP')
    fn = leer('supabase', 'functions', 'entrar', 'index.ts')
    check('captchaToken: captcha ?' in fn, 'v414: `entrar` pasa el CAPTCHA a Supabase')


if __name__ == '__main__':
    probar_v414()
    probar_entrar()
    probar_cabeceras()
    probar_libreria()
    probar_contrasena()
    print('\n' + '=' * 40)
    print('TODO OK' if not FALLOS else '%d FALLOS' % len(FALLOS))
    raise SystemExit(1 if FALLOS else 0)
