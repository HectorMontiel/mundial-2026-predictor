# -*- coding: utf-8 -*-
"""v343 — siembra `anunciadas_dia.json` repasando las fotos de
`pronostico_dia.json` en git, cada una con la hora de su commit (lo mismo que
habría hecho `anunciadas.acumular` en cada precálculo)."""
import datetime as dt
import json
import subprocess
import anunciadas as an

hs = subprocess.run(['git', 'log', '--reverse', '--format=%H %cI',
                     '--since=2026-10-06T00:00', 'origin/main', '--',
                     'pronostico_dia.json'], capture_output=True, text=True).stdout
for linea in [x for x in hs.split('\n') if x.strip()]:
    h, cuando = linea.split()
    doc = json.loads(subprocess.run(['git', 'show', h + ':pronostico_dia.json'],
                                    capture_output=True).stdout.decode('utf-8'))
    t = dt.datetime.fromisoformat(cuando).astimezone(dt.timezone.utc)
    an.acumular(doc, ahora=t)
d = json.load(open(an.FICHERO, encoding='utf-8'))
print(d['actualizado'], len(d['partidos']), 'partidos')
