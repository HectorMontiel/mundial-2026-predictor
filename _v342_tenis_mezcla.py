# -*- coding: utf-8 -*-
"""v342 — qué peso del modelo frente a la casa da el número mejor calibrado
en el tenis (log-loss), elegido con el 70 % viejo y juzgado en el 30 %."""
import json
import numpy as np
import _v342_tenis as t

f, corte = t.cargar()
out = {}
for w in (0.0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 1.0):
    q = np.clip(w * f.p + (1 - w) * f.pm, 0.01, 0.99)
    ll = -(f.y * np.log(q) + (1 - f.y) * np.log(1 - q))
    out[w] = {tr: round(float(ll[f.tramo == tr].mean()), 5) for tr in ('elige', 'juzga')}
    print(w, out[w])
mejor = min(out, key=lambda w: out[w]['elige'])
print('elegido', mejor)
# calibración del elegido en las apuestas que dirían «meter» con la regla
s = f[(f.pm >= 0.70) & (f.p >= 0.65) & (f.tramo == 'juzga')]
q = mejor * s.p + (1 - mejor) * s.pm
print('regla, juzga: promete %.3f acierta %.3f n=%d' % (q.mean(), s.y.mean(), len(s)))
for lo, hi in ((0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1)):
    z = s[(q >= lo) & (q < hi)]
    zq = q[(q >= lo) & (q < hi)]
    print('  %.2f-%.2f n=%4d promete %.3f acierta %.3f' % (lo, hi, len(z), zq.mean(), z.y.mean()))
json.dump({'logloss': {str(k): v for k, v in out.items()}, 'elegido': mejor},
          open('_v342_tenis_mezcla.json', 'w'), indent=1)
