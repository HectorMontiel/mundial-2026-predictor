# -*- coding: utf-8 -*-
"""
v264 — EL SELECTOR: un modelo que aprende CUÁL apuesta tomar y cuál no.

QUÉ PIDIÓ EL USUARIO
«Lo que quiero es que estas redes neuronales estén aprendiendo constantemente
para decir: ok, ahora es cuando sí debes poner a éste, éste no. Y no sólo de
los picks del día o de los que tienen EV positivo, sino de cada uno de los
partidos, saber cuál agarrar y cuál no.»

El caso que lo trae es un parley de cuatro patas donde tres entraron y la
cuarta —«Ambos marcan: No» a 1,42— acabó 2-1. Todas venían del semáforo en
verde. «Casi siempre me quedo a uno.»

SOBRE REDES NEURONALES, QUE ES LO QUE SE PEDÍA
Se pidieron redes neuronales y árboles de decisión. Esto usa **árboles**
(gradient boosting, LightGBM), y no es un atajo: con datos tabulares y este
tamaño de muestra, los árboles baten a las redes de forma consistente y además
aguantan categorías con miles de valores —`liga` tiene cientos— sin
codificarlas a mano. El proyecto ya usa árboles para el 1X2 (XGBoost +
LightGBM + Random Forest). Una red aquí sería más lenta, más frágil y peor.

Lo que sí es nuevo, y es lo que se pedía de verdad: que el sistema **aprenda
de sus propios resultados** en vez de confiar en su probabilidad a ciegas.

CÓMO APRENDE
Cada fila de los ledgers ES una apuesta que el modelo pudo proponer: su
probabilidad, su mercado, su liga, su precio cuando lo hay, y si acertó. Son
**1.911.136 apuestas con resultado entre 2013 y 2026**, de las que 250.094
llevan cuota real. Los picks publicados son sólo 568 y de dos días; los
ledgers son el histórico de verdad.

El selector recibe la probabilidad del modelo como una variable más y aprende
DÓNDE esa probabilidad se equivoca: por mercado, por línea, por liga, por
tramo de precio y por cuánto discrepa del mercado.

LO QUE APORTA, MEDIDO EN WALK-FORWARD (4 pliegues, 955.568 apuestas fuera de
muestra, todos los pliegues a favor):

    log-loss   modelo solo 0,53811  ->  con selector 0,53313   (+0,00498)
    Brier          0,18136          ->      0,17945
    AUC            0,8017           ->      0,8056
    p5 de la mejora +0,00478 · 100 % de los remuestreos a favor

Y en dinero, sobre las 96.804 con cuota real:

    modelo solo    n=33.056  acierta 0,345  ROI -8,17 %  (p5 -9,44 %)
    con selector   n=19.950  acierta 0,423  ROI -5,66 %  (p5 -7,09 %)

Ocho puntos más de acierto y dos y medio menos de pérdida, filtrando además
un tercio de las apuestas.

DÓNDE APRENDE, QUE IMPORTA MÁS QUE EL PROMEDIO

    BTTS «Ambos marcan»   n=67.289    +0,02802   <- seis veces el resto
    Tenis 1X2             n=34.704    +0,01054
    Fútbol 1X2            n=81.836    +0,00604
    Hándicap              n=488.071   +0,00345
    Goles                 n=201.842   +0,00148
    Doble oportunidad     n=81.826    +0,00037   <- no aprende nada

El BTTS es donde el modelo más se equivoca y donde el selector más corrige —
que es exactamente la pata que tumbó el parley del usuario.

LO QUE ESTO **NO** HACE, Y HAY QUE DECIRLO
No convierte las apuestas en rentables. El ROI mejora de -8,17 % a -5,66 %,
pero sigue siendo negativo: la comisión de la casa ronda el 6 % y el modelo no
le gana al precio de cierre en ningún mercado medido. Lo que hace el selector
es **elegir mejor dentro de lo que hay** y decir con honestidad cuándo una
apuesta que parece buena no lo es.

El dinero sigue estando en la Capa 1 (`valor_vs_sharp`), que no usa el modelo
para nada. El selector ordena el resto.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODELO = 'selector_apuestas.txt'      # el booster, en texto: sin pickle
META = 'selector_apuestas.json'

# Las variables. `liga` y `mercado` van como categoría nativa de LightGBM: no
# se codifican a mano porque el árbol parte por categoría mejor que cualquier
# codificación que uno invente.
FEATS = ['p_modelo', 'logit_p', 'linea', 'cuota', 'p_mercado', 'brecha',
         'mercado', 'seleccion', 'deporte', 'liga',
         # v265 — en qué se viene equivocando el modelo con ESTOS equipos.
         # Medido: correlación +0,0493 entre el error pasado y el de hoy, con
         # gradiente monótono. Se le da al selector en vez de corregir la
         # lambda, porque sobre la lambda ya hay dos correcciones apiladas y
         # hoy se vio a dónde lleva eso. Ver `memoria_equipos`.
         'sesgo_local', 'sesgo_visita']
CATEGORICAS = ['mercado', 'seleccion', 'deporte', 'liga']

# Por debajo de esto no se publica: el selector tiene que GANARLE a la
# probabilidad del modelo en el remuestreo, no sólo empatar.
P5_MINIMO = 0.0

_CACHE: Dict = {}


def cargar(recargar: bool = False) -> Dict:
    """El booster y su ficha, o {} si no hay. Nunca lanza."""
    global _CACHE
    if _CACHE and not recargar:
        return _CACHE
    fuera: Dict = {}
    try:
        if os.path.exists(META):
            with open(META, encoding='utf-8') as f:
                fuera['meta'] = json.load(f) or {}
        if os.path.exists(MODELO) and (fuera.get('meta') or {}).get('activo'):
            import lightgbm as lgb
            fuera['booster'] = lgb.Booster(model_file=MODELO)
            fuera['categorias'] = (fuera['meta'].get('categorias') or {})
    except Exception as e:
        logger.warning('[selector] no se pudo cargar: %s', e)
        fuera = {}
    _CACHE = fuera
    return _CACHE


def olvidar() -> None:
    global _CACHE
    _CACHE = {}


def disponible() -> bool:
    d = cargar()
    return bool(d.get('booster'))


def _fila(pick: Dict) -> Optional[Dict]:
    """El diccionario de un pick, traducido a las variables del selector."""
    import math
    try:
        p = float(pick.get('prob'))
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        return None
    cuota = pick.get('cuota')
    try:
        cuota = float(cuota) if cuota else None
    except (TypeError, ValueError):
        cuota = None
    p_mer = (1.0 / cuota) if (cuota and cuota > 1) else None
    linea = pick.get('linea')
    try:
        linea = float(linea) if linea is not None else None
    except (TypeError, ValueError):
        linea = None
    return {
        'p_modelo': p,
        'logit_p': math.log(p / (1.0 - p)),
        'linea': linea,
        'cuota': cuota,
        'p_mercado': p_mer,
        'brecha': (p - p_mer) if p_mer is not None else None,
        'mercado': str(pick.get('mercado') or ''),
        'seleccion': _seleccion(pick),
        'deporte': str(pick.get('deporte') or ''),
        'liga': str(pick.get('clave_liga') or pick.get('liga') or ''),
        # v265 — el sesgo VIGENTE de cada equipo. En entrenamiento se usa el
        # que se conocía ANTES de cada partido (ver `construir_universo`);
        # aquí, en producción, «antes del próximo partido» es justo el de
        # ahora, así que son la misma cosa.
        'sesgo_local': _sesgo_de(pick, 'local'),
        'sesgo_visita': _sesgo_de(pick, 'visita'),
    }


def _sesgo_de(pick: Dict, lado: str) -> Optional[float]:
    """El sesgo del equipo que toca, o None. Nunca lanza."""
    try:
        import memoria_equipos as me
        import modo_modelo as mm
        h, a = mm._equipos(pick)
        return me.sesgo(h if lado == 'local' else a)
    except Exception as e:
        logger.debug('[selector] memoria de equipos: %s', e)
        return None


def _seleccion(pick: Dict) -> str:
    """La cara de la apuesta, con el mismo vocabulario que el entrenamiento."""
    a = str(pick.get('apuesta') or '').lower()
    m = str(pick.get('mercado') or '').lower()
    if m.startswith('goles') or 'de ' in a:
        return 'mas' if 'más de' in a or 'mas de' in a else 'menos'
    if m.startswith('btts') or 'ambos' in m or 'ambos' in a:
        return 'no' if ': no' in a or a.endswith(' no') else 'si'
    if m.startswith('doble'):
        return 'X2' if ' o empate' in a else '12'
    return 'local'


def evaluar(pick: Dict) -> Dict:
    """Qué dice el selector de esta apuesta. NUNCA lanza.

        {'p': probabilidad corregida (o la del modelo si no hay selector),
         'hay': si de verdad opinó,
         'delta': cuánto movió la probabilidad,
         'tomar': True/False/None — el veredicto,
         'razon': texto para la pantalla}

    `tomar` es None cuando el selector no está disponible: no se inventa un
    veredicto. Falta de opinión no es una opinión.
    """
    base = pick.get('prob')
    fuera = {'p': base, 'hay': False, 'delta': 0.0, 'tomar': None, 'razon': ''}
    d = cargar()
    b = d.get('booster')
    if not b:
        return fuera
    f = _fila(pick)
    if not f:
        return fuera
    try:
        import pandas as pd
        cats = d.get('categorias') or {}
        fila = {}
        for k in FEATS:
            v = f.get(k)
            if k in CATEGORICAS:
                # una categoría que el modelo no vio en el entrenamiento entra
                # como desconocida, no como un valor cualquiera: inventarle un
                # código la haría parecer otra liga.
                vals = cats.get(k) or []
                fila[k] = pd.Categorical([v], categories=vals)
            else:
                # v264.1 — EL TIPO SE FIJA A FLOAT, SIEMPRE.
                #
                # Con una sola fila, un `None` convierte la columna en
                # `object` y LightGBM la rechaza entera. Se veía sólo en los
                # mercados SIN línea —BTTS y 1X2—: el selector no opinaba y
                # el `except` se tragaba el error, así que la apuesta salía
                # con la probabilidad del modelo como si el selector
                # estuviera de acuerdo. Un fallo que se disfraza de acuerdo
                # es peor que uno que se ve.
                fila[k] = pd.array([v], dtype='float64')
        X = pd.DataFrame(fila)
        p = float(b.predict(X[FEATS])[0])
    except Exception as e:
        logger.debug('[selector] evaluando %s: %s', pick.get('apuesta'), e)
        return fuera
    p = max(0.005, min(0.995, p))
    try:
        delta = p - float(base)
    except (TypeError, ValueError):
        delta = 0.0
    return {'p': round(p, 4), 'hay': True, 'delta': round(delta, 4),
            'tomar': _veredicto(p, pick.get('cuota')),
            'razon': _razon(p, float(base) if base else p, delta)}


def evaluar_lote(picks: List[Dict]) -> List[Dict]:
    """Lo mismo que `evaluar`, pero para varios de golpe. NUNCA lanza.

    POR QUE EXISTE: el coste de predecir con LightGBM no esta en el arbol sino
    en construir el DataFrame. Medido sobre 40 partidos reales, una llamada
    por candidata costaba **40,6 ms por partido** — unos 12 s en un barrido de
    300, para un modelo que tarda microsegundos en decidir. Por lotes, ese
    coste se paga UNA vez por partido.

    Devuelve una lista alineada con la de entrada; los picks que no se pueden
    evaluar salen con el esquema vacio, nunca se omiten (si se omitieran, el
    llamante tendria que emparejar a mano y ahi es donde se cruzan las filas).
    """
    fuera = [{'p': p.get('prob'), 'hay': False, 'delta': 0.0,
              'tomar': None, 'razon': ''} for p in (picks or [])]
    if not picks:
        return fuera
    d = cargar()
    b = d.get('booster')
    if not b:
        return fuera
    filas, idx = [], []
    for i, pk in enumerate(picks):
        f = _fila(pk)
        if f:
            filas.append(f)
            idx.append(i)
    if not filas:
        return fuera
    try:
        import pandas as pd
        cats = d.get('categorias') or {}
        cols = {}
        for k in FEATS:
            vals = [f.get(k) for f in filas]
            if k in CATEGORICAS:
                cols[k] = pd.Categorical(vals, categories=cats.get(k) or [])
            else:
                cols[k] = pd.array(vals, dtype='float64')
        X = pd.DataFrame(cols)
        ps = b.predict(X[FEATS])
    except Exception as e:
        logger.debug('[selector] lote de %d: %s', len(filas), e)
        return fuera
    for j, i in enumerate(idx):
        try:
            p = max(0.005, min(0.995, float(ps[j])))
            base = float(picks[i].get('prob'))
        except (TypeError, ValueError, IndexError):
            continue
        fuera[i] = {'p': round(p, 4), 'hay': True,
                    'delta': round(p - base, 4),
                    'tomar': _veredicto(p, picks[i].get('cuota')),
                    'razon': _razon(p, base, p - base)}
    return fuera


def _veredicto(p: float, cuota) -> Optional[bool]:
    """Con precio, manda el precio. Sin precio, manda la probabilidad."""
    try:
        c = float(cuota) if cuota else None
    except (TypeError, ValueError):
        c = None
    if c and c > 1:
        return bool(p * c >= 1.0)
    return bool(p >= 0.60)


def _razon(p: float, base: float, delta: float) -> str:
    """En cristiano, y contando partidos: lo lee quien apuesta."""
    if abs(delta) < 0.02:
        return ('Mirando cómo han salido apuestas parecidas, este número se '
                'sostiene: sale **%d de cada 100 veces**.' % round(p * 100))
    if delta < 0:
        return ('⚠️ Apuestas parecidas a ésta han salido peor de lo que dice '
                'el número: **%d de cada 100 veces**, no %d. Cuenta con '
                'menos.' % (round(p * 100), round(base * 100)))
    return ('👍 Apuestas parecidas a ésta han salido mejor de lo que dice el '
            'número: **%d de cada 100 veces**, no %d.'
            % (round(p * 100), round(base * 100)))


# ---------------------------------------------------------------------------
# EL UNIVERSO DE ENTRENAMIENTO
# ---------------------------------------------------------------------------
def construir_universo() -> 'pd.DataFrame':
    """Cada fila de los ledgers, convertida en una apuesta con resultado.

    No se usan los picks publicados: son 568 y de dos dias. Los ledgers son
    1,9 millones de apuestas entre 2013 y 2026, que es lo que hace falta para
    que un modelo aprenda donde se equivoca el otro.
    """
    import numpy as np
    import pandas as pd

    filas = []

    # v265 - EL SESGO DE CADA EQUIPO, TAL COMO SE CONOCIA ANTES DE CADA
    # PARTIDO. Usar el sesgo de HOY seria mirar el futuro: el equipo que
    # marco de mas en octubre no se sabia en marzo.
    sesgos = {}
    try:
        import collections
        import memoria_equipos as me
        _t = None
        import calibrador_goles as _cg0
        _t = _cg0._datos()
        if {'lam_h', 'lam_a', 'goles_local', 'goles_visit'} <= set(_t.columns):
            _t = _t.sort_values('fecha')
            _h, _a = zip(*_t['match_id'].map(
                lambda m: tuple(str(m).split('_')[1:3])
                if len(str(m).split('_')) >= 3 else (None, None)))
            _eh = (_t['goles_local'] - _t['lam_h']).to_numpy(dtype=float)
            _ea = (_t['goles_visit'] - _t['lam_a']).to_numpy(dtype=float)
            _hist = collections.defaultdict(list)
            _mid = _t['match_id'].tolist()
            for _i in range(len(_t)):
                _kh, _ka = me._clave(_h[_i]), me._clave(_a[_i])
                _sh = (float(np.mean(_hist[_kh][-me.VENTANA:]))
                       if len(_hist[_kh]) >= me.MIN_PARTIDOS else np.nan)
                _sa = (float(np.mean(_hist[_ka][-me.VENTANA:]))
                       if len(_hist[_ka]) >= me.MIN_PARTIDOS else np.nan)
                sesgos[_mid[_i]] = (_sh, _sa)
                _hist[_kh].append(_eh[_i])
                _hist[_ka].append(_ea[_i])
            logger.info('[selector] sesgo previo para %d partidos', len(sesgos))
    except Exception as e:
        logger.warning('[selector] memoria de equipos: %s', e)
        sesgos = {}

    def _ses(mids, lado):
        """El sesgo ANTERIOR del bando que toca, alineado con las filas."""
        i = 0 if lado == 'local' else 1
        return np.array([sesgos.get(m, (np.nan, np.nan))[i] for m in mids])

    # --- goles y BTTS, desde el ledger de totales con la lambda de produccion
    try:
        import calibrador_goles as cg
        t = cg._datos()
        lam = t['lam'].to_numpy()
        for L in ('1.5', '2.5', '3.5'):
            col = 'over_%s_real' % L
            if col not in t.columns:
                continue
            m = t[col].notna().to_numpy()
            y = t.loc[t[col].notna(), col].to_numpy(dtype=float)
            p = cg._p_over(lam[m], float(L))
            base = t[m]
            for lado, pp, yy in (('mas', p, y), ('menos', 1 - p, 1 - y)):
                cu = np.nan
                if L == '2.5':
                    cu = (base['cuota_over25'].values if lado == 'mas'
                          else base['cuota_under25'].values)
                filas.append(pd.DataFrame({
                    'fecha': base['fecha'].values, 'liga': base['liga'].values,
                    'deporte': 'Futbol', 'mercado': 'Goles',
                    'seleccion': lado, 'linea': float(L),
                    'p_modelo': pp, 'acierto': yy, 'cuota': cu,
                    'sesgo_local': _ses(base['match_id'].values, 'local'),
                    'sesgo_visita': _ses(base['match_id'].values, 'visita')}))
        if 'p_btts' in t.columns and 'btts_real' in t.columns:
            b = t[t['btts_real'].notna()]
            for lado, pp, yy in (
                    ('si', b['p_btts'].to_numpy(),
                     b['btts_real'].to_numpy(dtype=float)),
                    ('no', 1 - b['p_btts'].to_numpy(),
                     1 - b['btts_real'].to_numpy(dtype=float))):
                filas.append(pd.DataFrame({
                    'fecha': b['fecha'].values, 'liga': b['liga'].values,
                    'deporte': 'Futbol', 'mercado': 'BTTS', 'seleccion': lado,
                    'linea': np.nan, 'p_modelo': pp, 'acierto': yy,
                    'cuota': np.nan,
                    'sesgo_local': _ses(b['match_id'].values, 'local'),
                    'sesgo_visita': _ses(b['match_id'].values, 'visita')}))
    except Exception as e:
        logger.warning('[selector] goles/btts: %s', e)

    # --- 1X2 y doble oportunidad de futbol
    try:
        import pandas as pd
        l = pd.read_csv('pick_ledger.csv', low_memory=False)
        l = l.dropna(subset=['p_home', 'p_draw', 'p_away', 'resultado'])
        for lado, cp, cc, res in (('local', 'p_home', 'cuota_home', 0),
                                  ('empate', 'p_draw', 'cuota_draw', 1),
                                  ('visita', 'p_away', 'cuota_away', 2)):
            filas.append(pd.DataFrame({
                'fecha': l['fecha'].values, 'liga': l['liga'].values,
                'deporte': 'Futbol', 'mercado': '1X2', 'seleccion': lado,
                'linea': np.nan, 'p_modelo': l[cp].values,
                'acierto': (l['resultado'] == res).astype(float).values,
                'cuota': l[cc].values if cc in l.columns else np.nan}))
        for etq, a, b2, cs in (('1X', 'p_home', 'p_draw', (0, 1)),
                               ('12', 'p_home', 'p_away', (0, 2)),
                               ('X2', 'p_draw', 'p_away', (1, 2))):
            filas.append(pd.DataFrame({
                'fecha': l['fecha'].values, 'liga': l['liga'].values,
                'deporte': 'Futbol', 'mercado': 'Doble', 'seleccion': etq,
                'linea': np.nan, 'p_modelo': (l[a] + l[b2]).values,
                'acierto': l['resultado'].isin(cs).astype(float).values,
                'cuota': np.nan}))
    except Exception as e:
        logger.warning('[selector] 1X2 de futbol: %s', e)

    # --- tenis y MLB
    try:
        import pandas as pd
        dd = pd.read_csv('pick_ledger_deportes.csv', low_memory=False)
        dd = dd.dropna(subset=['p_home', 'resultado'])
        for lado, cp, cc, res in (('local', 'p_home', 'cuota_home', 0),
                                  ('visita', 'p_away', 'cuota_away', 2)):
            if cp not in dd.columns:
                continue
            filas.append(pd.DataFrame({
                'fecha': dd['fecha'].values, 'liga': dd['liga'].values,
                'deporte': dd['deporte'].values, 'mercado': '1X2',
                'seleccion': lado, 'linea': np.nan, 'p_modelo': dd[cp].values,
                'acierto': (dd['resultado'] == res).astype(float).values,
                'cuota': dd[cc].values if cc in dd.columns else np.nan}))
    except Exception as e:
        logger.warning('[selector] deportes: %s', e)

    # --- handicap asiatico
    try:
        import pandas as pd
        h = pd.read_csv('pick_ledger_handicap.csv', low_memory=False)
        for c in h.columns:
            if not c.startswith('p_ah_'):
                continue
            cr = 'ah_%s_real' % c[5:]
            if cr not in h.columns:
                continue
            m = h[c].notna() & h[cr].notna()
            if int(m.sum()) < 500:
                continue
            g = h[m]
            filas.append(pd.DataFrame({
                'fecha': g['fecha'].values, 'liga': g['liga'].values,
                'deporte': 'Futbol', 'mercado': 'Handicap',
                'seleccion': c[5:], 'linea': np.nan,
                'p_modelo': g[c].values,
                'acierto': g[cr].astype(float).values, 'cuota': np.nan}))
    except Exception as e:
        logger.warning('[selector] handicap: %s', e)

    if not filas:
        import pandas as pd
        return pd.DataFrame()
    import pandas as pd
    d = pd.concat(filas, ignore_index=True)
    # los ledgers que no son el de totales no traen sesgo de equipo: entran
    # como NaN y LightGBM los reparte solo. Es preferible a inventarles un 0,
    # que el arbol leeria como «este equipo esta perfectamente ajustado».
    for c in ('sesgo_local', 'sesgo_visita'):
        if c not in d.columns:
            d[c] = np.nan
    d = d.dropna(subset=['p_modelo', 'acierto'])
    d = d[(d['p_modelo'] > 0) & (d['p_modelo'] < 1)]
    d['fecha'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['fecha']).sort_values('fecha').reset_index(drop=True)
    return d


def _preparar(d):
    """Las variables derivadas, iguales en entrenamiento y en produccion."""
    import numpy as np
    d = d.copy()
    d['p_mercado'] = np.where(d['cuota'].notna() & (d['cuota'] > 1),
                              1.0 / d['cuota'], np.nan)
    d['brecha'] = d['p_modelo'] - d['p_mercado']
    d['logit_p'] = np.log(d['p_modelo'] / (1 - d['p_modelo']))
    for c in CATEGORICAS:
        d[c] = d[c].astype('category')
    return d


def _perdida(p, y):
    import numpy as np
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def entrenar(cortes: int = 4) -> Dict:
    """Ajusta el selector, lo juzga fuera de muestra y sólo lo publica si gana.

    El juicio es walk-forward por FECHA: se entrena con lo anterior y se mide
    con lo posterior. Y la referencia no es «acertar mucho» —con la
    probabilidad del modelo como entrada eso es trivial— sino **batir a esa
    probabilidad**. Si no la bate en el remuestreo, no se publica y todo
    sigue como estaba.
    """
    import numpy as np
    import lightgbm as lgb

    d = construir_universo()
    if d is None or len(d) < 50_000:
        logger.warning('[selector] universo insuficiente (%d)', len(d or []))
        return {}
    d = _preparar(d)
    n = len(d)
    bordes = np.linspace(int(n * 0.50), n, cortes + 1).astype(int)
    L_base, L_sel, Y, P_sel, CU = [], [], [], [], []
    for k in range(cortes):
        ini, fin = int(bordes[k]), int(bordes[k + 1])
        tr, te = d.iloc[:ini], d.iloc[ini:fin]
        if len(te) < 5_000:
            continue
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05,
                               num_leaves=63, min_child_samples=200,
                               subsample=0.8, colsample_bytree=0.8,
                               verbose=-1, random_state=7)
        m.fit(tr[FEATS], tr['acierto'])
        p = m.predict_proba(te[FEATS])[:, 1]
        y = te['acierto'].to_numpy(dtype=float)
        L_base.append(_perdida(te['p_modelo'].to_numpy(dtype=float), y))
        L_sel.append(_perdida(p, y))
        Y.append(y)
        P_sel.append(p)
        CU.append(te['cuota'].to_numpy(dtype=float))
    if not Y:
        return {}
    L_base = np.concatenate(L_base)
    L_sel = np.concatenate(L_sel)
    Y = np.concatenate(Y)
    P_sel = np.concatenate(P_sel)
    CU = np.concatenate(CU)

    g = L_base - L_sel
    rng = np.random.default_rng(3)
    xs = np.array([g[rng.integers(0, len(g), len(g))].mean()
                   for _ in range(300)])
    p5 = float(np.percentile(xs, 5))

    med = {
        'n_fuera_de_muestra': int(len(Y)),
        'log_loss_modelo': round(float(L_base.mean()), 5),
        'log_loss_selector': round(float(L_sel.mean()), 5),
        'mejora': round(float(g.mean()), 5),
        'p5': round(p5, 5),
        'a_favor': round(float((xs > 0).mean()), 3),
        'brier_selector': round(float(((P_sel - Y) ** 2).mean()), 5),
    }
    # el dinero, sobre las que tienen cuota real
    hay = np.isfinite(CU) & (CU > 1)
    if hay.sum() > 1000:
        sel = (P_sel[hay] * CU[hay] - 1.0) > 0
        if sel.sum() > 200:
            r = np.where(Y[hay][sel] == 1, CU[hay][sel] - 1.0, -1.0)
            med['roi_selector'] = round(float(r.mean()), 4)
            med['n_roi'] = int(sel.sum())

    activo = p5 > P5_MINIMO
    med['activo'] = bool(activo)
    if not activo:
        logger.warning('[selector] no bate a la probabilidad del modelo '
                       '(p5 %+.5f): no se publica', p5)
        with open(META, 'w', encoding='utf-8') as f:
            json.dump({'activo': False, 'medicion': med}, f,
                      ensure_ascii=False, indent=1)
        olvidar()
        return {'activo': False, 'medicion': med}

    # validado el metodo, el modelo de produccion se ajusta con TODO
    final = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05,
                               num_leaves=63, min_child_samples=200,
                               subsample=0.8, colsample_bytree=0.8,
                               verbose=-1, random_state=7)
    final.fit(d[FEATS], d['acierto'])
    final.booster_.save_model(MODELO)
    doc = {
        'activo': True,
        'generado': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'n_entrenamiento': int(len(d)),
        'desde': str(d['fecha'].min())[:10],
        'hasta': str(d['fecha'].max())[:10],
        'feats': list(FEATS),
        # las categorias se guardan para que produccion codifique IGUAL que el
        # entrenamiento: sin esto, «laliga» podria entrar como otra liga
        'categorias': {c: [str(x) for x in d[c].cat.categories]
                       for c in CATEGORICAS},
        'medicion': med,
    }
    with open(META, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    olvidar()
    return doc


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    doc = entrenar()
    if not doc:
        print('sin universo suficiente')
        return 1
    m = doc.get('medicion') or {}
    print('entrenamiento: %s apuestas (%s a %s)'
          % (format(doc.get('n_entrenamiento', 0), ',d'),
             doc.get('desde'), doc.get('hasta')))
    print('log-loss  modelo %.5f -> selector %.5f  (%+.5f)'
          % (m.get('log_loss_modelo', 0), m.get('log_loss_selector', 0),
             m.get('mejora', 0)))
    print('p5 %+.5f · a favor %.0f %%'
          % (m.get('p5', 0), (m.get('a_favor') or 0) * 100))
    if 'roi_selector' in m:
        print('ROI del selector sobre las que tienen cuota: %+.2f %% (n=%s)'
              % (100 * m['roi_selector'], format(m.get('n_roi', 0), ',d')))
    print('activo:', doc.get('activo'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
