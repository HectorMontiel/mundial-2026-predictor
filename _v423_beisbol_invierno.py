# Histórico del béisbol de invierno con cuotas de cierre (Betexplorer): LMP, LIDOM, LVBP.
import json, re, sys, time
import requests
from bs4 import BeautifulSoup
BASE = 'https://www.betexplorer.com'
UA = {'User-Agent': 'Mozilla/5.0'}
LIGAS = {'lmp': 'baseball/mexico/lmp', 'lidom': 'baseball/dominican-republic/lidom', 'lvbp': 'baseball/venezuela/lvbp'}
TEMPORADAS = ['2021-2022', '2022-2023', '2023-2024', '2024-2025', '2025-2026']


def pagina(url):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.ok:
                return r.text
        except Exception:
            pass
        time.sleep(2)
    return ''


def filas(html, temporada):
    s = BeautifulSoup(html, 'lxml')
    out = []
    anio_ini, anio_fin = temporada.split('-')
    for tr in s.select('tr'):
        a = tr.select_one('a.in-match')
        if not a:
            continue
        sp = a.select('span')
        if len(sp) < 2:
            continue
        m = tr.select_one('td.h-text-center a')
        cu = [td.get('data-odd') or (td.select_one('[data-odd]') or {}).get('data-odd') for td in tr.select('td.table-main__odds')]
        f = tr.select_one('td.h-text-right')
        mm = re.match(r'(\d+):(\d+)', m.get_text(strip=True)) if m else None
        ff = re.match(r'(\d{2})\.(\d{2})\.(\d{4})?', (f.get_text(strip=True) if f else ''))
        if not (mm and ff and len(cu) >= 2 and all(cu[:2])):
            continue
        anio = ff.group(3) or (anio_ini if int(ff.group(2)) >= 7 else anio_fin)
        out.append({'home': sp[0].get_text(strip=True), 'away': sp[-1].get_text(strip=True),
                    'rh': int(mm.group(1)), 'ra': int(mm.group(2)), 'fecha': '%s-%s-%s' % (anio, ff.group(2), ff.group(1)),
                    'oh': float(cu[0]), 'oa': float(cu[1]), 'temporada': temporada})
    etapas = sorted({a.get('href') for a in s.select('a') if (a.get('href') or '').startswith('?stage=')})
    return out, etapas


todo = []
for liga, ruta in LIGAS.items():
    for t in TEMPORADAS:
        url = '%s/%s-%s/results/' % (BASE, ruta, t)
        h = pagina(url)
        if not h:
            print(liga, t, 'sin página'); continue
        p, etapas = filas(h, t)
        vistos = {(x['fecha'], x['home'], x['away']) for x in p}
        for e in etapas:
            h2 = pagina(url + e); time.sleep(0.6)
            p2, _ = filas(h2, t)
            for x in p2:
                k = (x['fecha'], x['home'], x['away'])
                if k not in vistos:
                    vistos.add(k); p.append(x)
        for x in p:
            x['liga'] = liga
        todo += p
        print(liga, t, len(p), 'partidos', len(etapas), 'fases', flush=True)
        time.sleep(0.6)
json.dump(todo, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False)
print('total', len(todo))
