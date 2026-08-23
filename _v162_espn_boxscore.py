# -*- coding: utf-8 -*-
"""
v162 - QUE ESTADISTICAS TRAE EL BOXSCORE DE ESPN, Y EN QUE LIGAS.

Antes de construir un modelo de imputacion hay que agotar la fuente que ya
esta integrada. El `summary` de ESPN trae una clave `boxscore` que nadie de
este proyecto ha mirado. Si ahi hay corners y tarjetas REALES, las 42 ligas
que hoy no las tienen dejan de necesitar imputacion ninguna.

Se prueba sobre partidos YA JUGADOS (que es donde puede haber estadisticas) de
competiciones de los dos grupos: las que ya tienen datos de football-data y las
que no.
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


# unas cuantas de cada grupo
LIGAS = [
    # con datos de football-data (grupo de control: se puede cruzar)
    ('premier', 'eng.1'), ('laliga', 'esp.1'), ('serie_a', 'ita.1'),
    # SIN datos: es donde hace falta
    ('liga_mx', 'mex.1'), ('argentina', 'arg.1'), ('brasil', 'bra.1'),
    ('mls', 'usa.1'), ('col_primera_a', 'col.1'), ('chi_primera', 'chi.1'),
    ('per_liga1', 'per.1'), ('jpn_j1', 'jpn.1'), ('china', 'chn.1'),
    ('uru_primera', 'uru.1'), ('ecu_liga_pro', 'ecu.1'),
    ('bol_division', 'bol.1'), ('usl_championship', 'usa.usl.1'),
    ('suecia', 'swe.1'), ('noruega', 'nor.1'), ('dinamarca', 'den.1'),
    ('rus_premier', 'rus.1'), ('rumania', 'rou.1'), ('irlanda', 'irl.1'),
    ('finlandia', 'fin.1'), ('bra_serie_b', 'bra.2'),
    ('arg_primera_nacional', 'arg.2'), ('mex_expansion', 'mex.2'),
    ('ven_primera', 'ven.1'), ('crc_fpd', 'crc.1'), ('par_division', 'par.1'),
    ('slv_primera', 'slv.1'), ('ind_isl', 'ind.1'), ('rsa_premier', 'rsa.1'),
    ('aut_bundesliga', 'aut.1'), ('aus_aleague', 'aus.1'),
]

FECHA = '20260816-20260822'   # semana con partidos jugados


def sondear(par):
    clave, code = par
    try:
        sb = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                 'scoreboard?dates=%s' % (code, FECHA))
    except Exception as e:
        return {'clave': clave, 'error': 'scoreboard: %s' % e}
    jugados = [e for e in (sb.get('events') or [])
               if (((e.get('status') or {}).get('type') or {})
                   .get('state') == 'post')]
    if not jugados:
        return {'clave': clave, 'error': 'sin partidos jugados en la ventana'}
    ev = jugados[0]
    try:
        su = get('https://site.api.espn.com/apis/site/v2/sports/soccer/%s/'
                 'summary?event=%s' % (code, ev.get('id')))
    except Exception as e:
        return {'clave': clave, 'error': 'summary: %s' % e}

    box = su.get('boxscore') or {}
    equipos = box.get('teams') or []
    nombres = set()
    for t in equipos:
        for st in (t.get('statistics') or []):
            n = st.get('name') or st.get('label') or st.get('abbreviation')
            if n:
                nombres.add(str(n))
    return {'clave': clave, 'partido': ev.get('name'),
            'n_jugados': len(jugados),
            'claves_boxscore': sorted(box.keys()),
            'n_equipos': len(equipos),
            'stats': sorted(nombres)}


with ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(sondear, LIGAS))

INTERES = ('corner', 'esquina', 'yellow', 'red', 'card', 'foul', 'falta',
           'possession', 'shot', 'save', 'offside')

print('%-22s %-5s %-6s %s' % ('liga', 'stats', 'ck/tj', 'muestra'))
con_ck = con_tj = con_faltas = 0
for r in sorted(res, key=lambda x: x['clave']):
    if r.get('error'):
        print('%-22s  --   --    ERROR: %s' % (r['clave'], r['error'][:50]))
        continue
    s = r['stats']
    low = [x.lower() for x in s]
    ck = any('corner' in x for x in low)
    tj = any('yellow' in x or 'red' in x for x in low)
    fa = any('foul' in x for x in low)
    con_ck += ck
    con_tj += tj
    con_faltas += fa
    print('%-22s %5d  %s%s%s   %s'
          % (r['clave'], len(s), 'C' if ck else '-', 'T' if tj else '-',
             'F' if fa else '-', ', '.join(s[:6])))

print()
print('con CORNERS  : %d de %d' % (con_ck, len(res)))
print('con TARJETAS : %d de %d' % (con_tj, len(res)))
print('con FALTAS   : %d de %d' % (con_faltas, len(res)))

# el catalogo completo de nombres de estadistica que ESPN publica
todas = set()
for r in res:
    todas.update(r.get('stats') or [])
print()
print('CATALOGO COMPLETO de estadisticas vistas (%d):' % len(todas))
for n in sorted(todas):
    print('   %s' % n)

json.dump(res, open('_v162_espn_boxscore.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
