# -*- coding: utf-8 -*-
"""
v270 — RADAR: dónde es probable que una casa se haya descolgado.

LA PREGUNTA DEL USUARIO, QUE ERA LA CORRECTA
«Si tenemos un histórico muy amplio, ¿por qué no ocupamos eso?»

Tenía razón y el planteamiento anterior era mío y estaba mal. Yo decía que
hacía falta esperar a acumular TRAYECTORIAS de precio —el mismo partido, la
misma casa, en varios momentos— porque quería contestar «¿CUÁNDO se descuelga
una casa?». Y de eso hay poco: 12.653 pares.

Pero la pregunta útil es otra: **¿en QUÉ partidos habrá discrepancia?** Y para
eso basta UNA foto por partido con Pinnacle y casa blanda a la vez. De esas hay
**26.647 desde 2021** en `pick_ledger.csv`, que llevaban ahí todo el tiempo.

LO QUE SE MIDE, FUERA DE MUESTRA Y POR FECHA
Entrenado con el 70 % más antiguo y juzgado con el 30 % reciente (desde
2025-03-09, n=7.995):

    tasa base (mirar a ciegas) ....... 12,7 % de los partidos tienen error
    AUC del radar .................... 0,7316

    barriendo sólo el   5 % mejor ....  39,8 %  ->  3,13x sobre la base
                       10 % .........  33,9 %  ->  2,67x
                       20 % .........  26,3 %  ->  2,07x
                       50 % .........  20,7 %  ->  1,63x

PARA QUÉ SIRVE, EN CONCRETO
El cuello de la Capa 1 no es el algoritmo: son las peticiones. Barrer siete
días cada dos horas serían ~340.000 peticiones diarias y una casa nos cortaría.
Con el radar, barriendo el 20 % más prometedor se encuentran el DOBLE de
errores por petición — o, al revés, se cubre una semana entera con el
presupuesto que hoy cubre dos días.

LO QUE **NO** HACE, Y CONVIENE QUE ESTÉ ESCRITO
No dice que la apuesta sea rentable. Dice dónde MIRAR. Que lo encontrado sea
jugable lo sigue decidiendo `valor_vs_sharp` con su regla validada, y esa no se
toca. Un radar que además decidiera qué apostar sería dos cosas a la vez y
ninguna medida.

Y no usa el modelo de predicción para nada: sus variables son el margen de
Pinnacle, quién es favorito, cuán igualado está el partido, la liga, el mes y
el día de la semana. Todo eso se sabe antes de mirar el precio de la casa.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODELO = 'radar_errores.txt'
META = 'radar_errores.json'
LEDGER = 'pick_ledger.csv'

FEATS = ['dow', 'mes', 'margen_pin', 'favorito', 'equilibrio', 'q_home',
         'q_away', 'liga_c']
CATEGORICAS = ['liga_c']

# El radar sólo se publica si de verdad ordena mejor que el azar. 0,55 es el
# mínimo que tiene sentido: por debajo, priorizar con él es ruido caro.
AUC_MINIMO = 0.55

# Cuantas capturas propias hacen falta para que la medicion sobre el tablero
# real signifique algo. Con 99 (un dia) el remuestreo daba p5 -7,4 pp: la
# mejora era de +8,0 pp de media pero cabia el cero de sobra. 1.000 son unos
# diez dias de barridos.
MIN_CAPTURAS_TABLERO = 1000

_CACHE: Dict = {}


def cargar(recargar: bool = False) -> Dict:
    """El modelo y su ficha, o {} si no hay. Nunca lanza."""
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
            fuera['ligas'] = (fuera['meta'].get('ligas') or [])
    except Exception as e:
        logger.warning('[radar] no se pudo cargar: %s', e)
        fuera = {}
    _CACHE = fuera
    return _CACHE


def olvidar() -> None:
    global _CACHE
    _CACHE = {}


def disponible() -> bool:
    return bool(cargar().get('booster'))


def _fila(pin: Dict, liga, cuando) -> Optional[Dict]:
    """Las variables de un partido, desde el precio de PINNACLE.

    Sólo entra lo que se sabe antes de mirar la casa blanda: si entrara su
    precio, el radar estaría mirando la respuesta.
    """
    try:
        h = float(pin.get('home'))
        a = float(pin.get('away'))
    except (TypeError, ValueError):
        return None
    if not (h > 1 and a > 1):
        return None
    dr = pin.get('draw')
    try:
        dr = float(dr) if dr else None
    except (TypeError, ValueError):
        dr = None
    s = 1.0 / h + 1.0 / a + (1.0 / dr if dr and dr > 1 else 0.0)
    if s <= 0:
        return None
    qh, qa = (1.0 / h) / s, (1.0 / a) / s
    import datetime as _dt
    try:
        f = (cuando if isinstance(cuando, _dt.datetime)
             else _dt.datetime.fromtimestamp(float(cuando)))
    except (TypeError, ValueError, OSError):
        f = _dt.datetime.now()
    return {'dow': f.weekday(), 'mes': f.month, 'margen_pin': s - 1.0,
            'favorito': max(qh, qa), 'equilibrio': abs(qh - qa),
            'q_home': qh, 'q_away': qa, 'liga_c': str(liga or '')}


def puntuar(partidos: List[Dict]) -> List[float]:
    """Probabilidad de que cada partido esconda un error. NUNCA lanza.

    `partidos` son diccionarios con al menos `pinnacle` (home/draw/away),
    `liga` e `inicio`. Devuelve una lista alineada; los que no se pueden
    puntuar salen con 0,5 —ni prioridad ni castigo— porque no saber no es lo
    mismo que saber que no.
    """
    fuera = [0.5] * len(partidos or [])
    if not partidos:
        return fuera
    d = cargar()
    b = d.get('booster')
    if not b:
        return fuera
    filas, idx = [], []
    for i, p in enumerate(partidos):
        f = _fila(p.get('pinnacle') or {}, p.get('liga'), p.get('inicio'))
        if f:
            filas.append(f)
            idx.append(i)
    if not filas:
        return fuera
    try:
        import pandas as pd
        cols = {}
        for k in FEATS:
            vals = [f[k] for f in filas]
            if k in CATEGORICAS:
                cols[k] = pd.Categorical(vals, categories=d.get('ligas') or [])
            else:
                cols[k] = pd.array(vals, dtype='float64')
        ps = b.predict(pd.DataFrame(cols)[FEATS])
    except Exception as e:
        logger.debug('[radar] puntuando %d: %s', len(filas), e)
        return fuera
    for j, i in enumerate(idx):
        try:
            fuera[i] = float(ps[j])
        except (TypeError, ValueError, IndexError):
            pass
    return fuera


def ordenar(partidos: List[Dict]) -> List[Dict]:
    """Los mismos partidos, con los prometedores delante. Nunca lanza."""
    if not partidos:
        return partidos
    try:
        ps = puntuar(partidos)
        # el indice desempata: sin el, dos puntuaciones iguales hacen que
        # `sorted` intente comparar los diccionarios y reviente
        orden = sorted(range(len(partidos)), key=lambda i: (-ps[i], i))
        return [partidos[i] for i in orden]
    except Exception as e:
        logger.debug('[radar] ordenando: %s', e)
        return partidos


# ---------------------------------------------------------------------------
# EL ENTRENAMIENTO
# ---------------------------------------------------------------------------
def _del_ledger():
    """El pasado: 26.647 partidos de `pick_ledger.csv` desde 2021.

    Es mucho y es gratis, pero esta congelado: son las casas de football-data,
    no las que el usuario juega, y termina donde termina el fichero.
    """
    import pandas as pd

    if not os.path.exists(LEDGER):
        logger.warning('[radar] sin %s', LEDGER)
        return None
    d = pd.read_csv(LEDGER, low_memory=False)
    faltan = [c for c in ('pin_home', 'pin_draw', 'pin_away', 'cuota_home',
                          'cuota_away', 'fecha', 'liga')
              if c not in d.columns]
    if faltan:
        logger.warning('[radar] al ledger le faltan columnas: %s', faltan)
        return None
    d = d.dropna(subset=['pin_home', 'pin_draw', 'pin_away', 'cuota_home',
                         'cuota_away', 'fecha', 'liga'])
    if d.empty:
        return None
    s = 1 / d['pin_home'] + 1 / d['pin_draw'] + 1 / d['pin_away']
    d['q_home'] = (1 / d['pin_home']) / s
    d['q_away'] = (1 / d['pin_away']) / s
    ev_h = d['q_home'] * d['cuota_home'] - 1.0
    ev_a = d['q_away'] * d['cuota_away'] - 1.0
    # el mismo umbral que la Capa 1 usa desde la v269
    d['hay_error'] = (((ev_h > 0.005) & (d['q_home'] >= 0.30))
                      | ((ev_a > 0.005) & (d['q_away'] >= 0.30))).astype(int)
    d['margen_pin'] = s - 1.0
    d['fuente'] = 'ledger'
    return d[['fecha', 'liga', 'q_home', 'q_away', 'margen_pin', 'hay_error',
              'fuente']]


def _de_capturas():
    """El presente: lo que cada barrido de la Capa 1 ve y anota.

    Crece solo, con las casas que el usuario juega de verdad. Ver
    `radar_capturas`, que es quien lo escribe.
    """
    import pandas as pd

    try:
        import radar_capturas as cap
    except Exception as e:
        logger.debug('[radar] sin radar_capturas: %s', e)
        return None
    if not os.path.exists(cap.FICHERO):
        return None
    try:
        d = pd.read_csv(cap.FICHERO, low_memory=False)
    except Exception as e:
        logger.warning('[radar] no se pudo leer %s: %s', cap.FICHERO, e)
        return None
    faltan = [c for c in ('fecha', 'liga', 'q_home', 'q_away', 'margen_pin',
                          'hay_error') if c not in d.columns]
    if faltan or d.empty:
        return None
    d = d.dropna(subset=['fecha', 'q_home', 'q_away', 'margen_pin',
                         'hay_error'])
    if d.empty:
        return None
    # una fila por partido y dia: doce pasadas del mismo partido son doce
    # filas casi identicas, y al modelo eso le pesa como si fueran doce
    # partidos distintos. Si CUALQUIERA de las pasadas vio error, hubo error:
    # la pregunta operativa es «si barro esto hoy, encontrare algo».
    d['hay_error'] = d['hay_error'].astype(int)
    if 'home' in d.columns and 'away' in d.columns:
        d = (d.sort_values('hay_error')
              .drop_duplicates(subset=['fecha', 'home', 'away'],
                               keep='last'))
    d['liga'] = d['liga'].fillna('')
    d['fuente'] = 'capturas'
    return d[['fecha', 'liga', 'q_home', 'q_away', 'margen_pin', 'hay_error',
              'fuente']]


def construir_universo():
    """Las DOS fuentes juntas: el pasado congelado y el presente que crece.

    POR QUE LAS DOS, QUE ES LO QUE PIDIO EL USUARIO
    «Para el entrenamiento ocupamos el pasado, y para fechas posteriores las
    capturas que dia con dia van a estar aumentando.»

    El ledger da volumen desde el primer dia —26.647 partidos— y sin el no
    habria modelo que entrenar. Las capturas dan pertinencia: son Novibet,
    Winpot, Caliente, 1xBet y Sportium, las casas que el usuario juega, y son
    las unicas que traen el vocabulario de ligas con el que produccion
    pregunta. Con el tiempo la segunda fuente pasa a la primera en tamano; de
    momento la complementa.

    UNA DIFERENCIA QUE CONVIENE TENER ESCRITA
    «Hay error» no se mide identico en las dos. En el ledger es la mejor cuota
    que publico football-data contra el justo de Pinnacle; en las capturas es
    el EV que calcula `valor_vs_sharp` sobre el precio accionable. Son la
    misma idea —una casa paga por encima del justo— medida con la regla de
    cada sitio. El modelo aprende DONDE pasa, no cuanto, y para eso sirve.
    """
    import pandas as pd

    trozos = [t for t in (_del_ledger(), _de_capturas()) if t is not None]
    if not trozos:
        return None
    d = pd.concat(trozos, ignore_index=True)
    d['dt'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['dt']).sort_values('dt').reset_index(drop=True)
    if d.empty:
        return None
    d['dow'] = d['dt'].dt.dayofweek
    d['mes'] = d['dt'].dt.month
    d['favorito'] = d[['q_home', 'q_away']].max(axis=1)
    d['equilibrio'] = (d['q_home'] - d['q_away']).abs()
    d['liga_c'] = d['liga'].astype(str).astype('category')
    return d


def _medir_tablero(led, cap) -> Dict:
    """El pasado congelado, ¿sirve para el tablón que el usuario juega?

    POR QUÉ HACE FALTA ESTA SEGUNDA MEDICIÓN
    La del `entrenar` es fuera de muestra por fecha, pero dentro de la misma
    fuente: entrena con football-data y juzga con football-data. Eso no
    contesta si transfiere a Novibet, Winpot, Caliente, 1xBet y Sportium, que
    son otras casas, otras ligas y otro vocabulario.

    Aquí se entrena SOLO con el ledger, sin ver una captura, y se juzga sobre
    las capturas. Medido el 2026-09-20 con un único día (n=99): AUC 0,6286 y
    el 20 % mejor daba 26,3 % de aciertos contra 19,2 % de base —pero el
    remuestreo daba p5 -7,4 pp, o sea que con un día no se puede afirmar. Por
    eso esto se recalcula cada semana y se guarda: para verlo apretarse solo
    conforme las capturas crecen.
    """
    fuera = {'n': 0 if cap is None else int(len(cap))}
    try:
        if cap is None or len(cap) < MIN_CAPTURAS_TABLERO or led is None:
            fuera['suficiente'] = False
            return fuera
        import numpy as np
        import lightgbm as lgb
        from sklearn.metrics import roc_auc_score
        tr = _variables(led.copy())
        cats = sorted(set(tr['liga'].astype(str)) | set(cap['liga'].astype(str)))
        tr = _categoriza(tr, cats)
        te = _categoriza(_variables(cap.copy()), cats)
        if te['hay_error'].nunique() < 2:
            fuera['suficiente'] = False
            return fuera
        m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05,
                               num_leaves=31, min_child_samples=100,
                               subsample=0.8, colsample_bytree=0.8,
                               verbose=-1, random_state=7)
        m.fit(tr[FEATS], tr['hay_error'])
        p = m.predict_proba(te[FEATS])[:, 1]
        y = te['hay_error'].to_numpy()
        base = float(y.mean())
        k = max(1, int(len(p) * 0.20))
        rng = np.random.default_rng(3)
        xs = []
        for _ in range(2000):
            i = rng.integers(0, len(p), len(p))
            idx = np.argsort(-p[i])[:k]
            xs.append(y[i][idx].mean() - y[i].mean())
        xs = np.array(xs)
        fuera.update({
            'suficiente': True,
            'auc': round(float(roc_auc_score(y, p)), 4),
            'tasa_base': round(base, 4),
            'top_20': round(float(y[np.argsort(-p)[:k]].mean()), 4),
            'mejora_pp': round(100 * float(xs.mean()), 2),
            'p5_pp': round(100 * float(np.percentile(xs, 5)), 2),
        })
    except Exception as e:
        logger.warning('[radar] no se pudo medir sobre el tablero: %s', e)
        fuera['suficiente'] = False
    return fuera


def _variables(d):
    """Las columnas derivadas, iguales en las dos fuentes."""
    import pandas as pd
    d['dt'] = pd.to_datetime(d['fecha'], errors='coerce')
    d = d.dropna(subset=['dt'])
    d['dow'] = d['dt'].dt.dayofweek
    d['mes'] = d['dt'].dt.month
    d['favorito'] = d[['q_home', 'q_away']].max(axis=1)
    d['equilibrio'] = (d['q_home'] - d['q_away']).abs()
    return d


def _categoriza(d, cats):
    import pandas as pd
    d['liga_c'] = pd.Categorical(d['liga'].astype(str), categories=cats)
    return d


def entrenar(ruta_modelo: str = MODELO, ruta_meta: str = META) -> Dict:
    """Ajusta el radar, lo juzga por fecha y solo lo publica si ordena mejor.

    La referencia no es «acierta mucho» —con un 12 % de casos positivos, decir
    siempre que no acierta el 88 %— sino ORDENAR: que los partidos que pone
    delante escondan mas errores que los de detras. Eso es el AUC, y por
    debajo de `AUC_MINIMO` no se publica.
    """
    import numpy as np
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score

    d = construir_universo()
    if d is None or len(d) < 5_000:
        logger.warning('[radar] universo insuficiente')
        return {}
    corte = int(len(d) * 0.70)
    tr, te = d.iloc[:corte], d.iloc[corte:]
    if len(te) < 1_000 or te['hay_error'].nunique() < 2:
        logger.warning('[radar] tramo de juicio insuficiente')
        return {}

    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05,
                           num_leaves=31, min_child_samples=100,
                           subsample=0.8, colsample_bytree=0.8,
                           verbose=-1, random_state=7)
    m.fit(tr[FEATS], tr['hay_error'])
    p = m.predict_proba(te[FEATS])[:, 1]
    y = te['hay_error'].to_numpy()
    auc = float(roc_auc_score(y, p))
    base = float(y.mean())

    ganancia = {}
    for q in (0.05, 0.10, 0.20, 0.50):
        k = max(1, int(len(p) * q))
        idx = np.argsort(-p)[:k]
        tasa = float(y[idx].mean())
        ganancia['top_%02d' % int(q * 100)] = {
            'n': int(k), 'tasa': round(tasa, 4),
            'veces': round(tasa / base, 2) if base else None}

    # la segunda medicion: ¿esto transfiere al tablon que se juega?
    tablero = _medir_tablero(_del_ledger(), _de_capturas())

    med = {'n_entrenamiento': int(len(tr)), 'n_juicio': int(len(te)),
           'tablero_real': tablero,
           'desde_juicio': str(te['fecha'].iloc[0])[:10],
           'tasa_base': round(base, 4), 'auc': round(auc, 4),
           'ganancia': ganancia, 'activo': bool(auc >= AUC_MINIMO)}

    if auc < AUC_MINIMO:
        logger.warning('[radar] AUC %.4f por debajo de %.2f: no se publica',
                       auc, AUC_MINIMO)
        with open(ruta_meta, 'w', encoding='utf-8') as f:
            json.dump({'activo': False, 'medicion': med}, f,
                      ensure_ascii=False, indent=1)
        olvidar()
        return {'activo': False, 'medicion': med}

    # validado el metodo, el radar de produccion se ajusta con TODO
    final = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05,
                               num_leaves=31, min_child_samples=100,
                               subsample=0.8, colsample_bytree=0.8,
                               verbose=-1, random_state=7)
    final.fit(d[FEATS], d['hay_error'])
    final.booster_.save_model(ruta_modelo)
    doc = {
        'activo': True,
        'generado': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'n_total': int(len(d)),
        'desde': str(d['fecha'].min())[:10],
        'hasta': str(d['fecha'].max())[:10],
        # las categorias se guardan para que produccion codifique IGUAL
        'ligas': [str(x) for x in d['liga_c'].cat.categories],
        'medicion': med,
    }
    with open(ruta_meta, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    olvidar()
    return doc


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    doc = entrenar()
    if not doc:
        print('sin universo')
        return 1
    m = doc.get('medicion') or {}
    print('universo: %s partidos · juicio desde %s (n=%s)'
          % (format(doc.get('n_total', 0), ',d'), m.get('desde_juicio'),
             format(m.get('n_juicio', 0), ',d')))
    print('tasa base %.1f %% · AUC %.4f'
          % (100 * m.get('tasa_base', 0), m.get('auc', 0)))
    for k, v in (m.get('ganancia') or {}).items():
        print('   %-8s n=%-6s aciertos %.1f %% (x%s)'
              % (k, format(v['n'], ',d'), 100 * v['tasa'], v['veces']))
    t = m.get('tablero_real') or {}
    if t.get('suficiente'):
        print('sobre el tablero REAL (n=%s): AUC %.4f · el 20 %% mejor '
              '%.1f %% contra %.1f %% de base · mejora %+.1f pp (p5 %+.1f pp)'
              % (format(t.get('n', 0), ',d'), t.get('auc', 0),
                 100 * t.get('top_20', 0), 100 * t.get('tasa_base', 0),
                 t.get('mejora_pp', 0), t.get('p5_pp', 0)))
    else:
        print('sobre el tablero REAL: %s capturas, hacen falta %s'
              % (format(t.get('n', 0), ',d'),
                 format(MIN_CAPTURAS_TABLERO, ',d')))
    print('activo:', doc.get('activo'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
