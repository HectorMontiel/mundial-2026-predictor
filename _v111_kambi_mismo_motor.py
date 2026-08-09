"""
¿Dos marcas de Kambi dan precios DISTINTOS para el mismo partido?

Importa mucho. Si comparten motor de precios, añadir varias marcas fabricaría
dispersión falsa: el sistema vería «una casa paga más que otra» donde en
realidad hay un único precio. Sería peor que no añadir nada — inventaría
oportunidades de line shopping inexistentes, que es justo el error que la v25
llamó «la trampa del EV+ ilusorio».
"""
import requests

UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}


def precios(marca):
    u = (f'https://eu-offering-api.kambicdn.com/offering/v2018/{marca}/'
         f'listView/football.json?lang=en_GB&market=GB')
    try:
        j = requests.get(u, headers=UA, timeout=25).json()
    except Exception as e:
        print(f'  {marca}: {type(e).__name__}')
        return {}
    out = {}
    for e in (j.get('events') or []):
        ev = e.get('event') or {}
        nombre = ev.get('name')
        for o in (e.get('betOffers') or []):
            crit = ((o.get('criterion') or {}).get('label') or '')
            if 'full time' not in crit.lower() and crit.lower() != 'match':
                continue
            precios_ev = {}
            for oc in (o.get('outcomes') or []):
                if oc.get('odds'):
                    precios_ev[oc.get('label')] = oc['odds'] / 1000.0
            if len(precios_ev) >= 2 and nombre:
                out[nombre] = precios_ev
            break
    return out


a = precios('ub')
b = precios('atg')
print(f'ub:  {len(a)} partidos con 1X2')
print(f'atg: {len(b)} partidos con 1X2')

comunes = sorted(set(a) & set(b))
print(f'\npartidos en AMBAS: {len(comunes)}')
if not comunes:
    print('  sin solape: no se puede comparar')
    raise SystemExit

iguales = distintos = 0
print(f'\n{"partido":48s} {"ub":22s} {"atg":22s}')
for n in comunes[:18]:
    pa = ' / '.join(f'{k}:{v:.2f}' for k, v in sorted(a[n].items()))
    pb = ' / '.join(f'{k}:{v:.2f}' for k, v in sorted(b[n].items()))
    if a[n] == b[n]:
        iguales += 1
    else:
        distintos += 1
    marca = '' if a[n] == b[n] else '  <-- DISTINTO'
    print(f'{n[:47]:48s} {pa[:21]:22s} {pb[:21]:22s}{marca}')

for n in comunes[18:]:
    if a[n] == b[n]:
        iguales += 1
    else:
        distintos += 1

print(f'\nidénticos: {iguales} · distintos: {distintos} de {len(comunes)}')
if distintos == 0:
    print('\nVEREDICTO: las marcas de Kambi comparten motor de precios.')
    print('Se añade UNA sola. Meter varias fabricaría dispersión falsa.')
else:
    pct = distintos / len(comunes)
    print(f'\nVEREDICTO: difieren en el {pct:.0%} de los partidos.')
    print('Habría que medir si esa diferencia es real o ruido de captura.')
