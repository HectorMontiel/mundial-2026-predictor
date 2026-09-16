#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Índice de riesgo por competición: qué liga hace daño a un parlay y cuál no.

DE DÓNDE SALE EL ENCARGO, Y QUÉ SALIÓ AL MEDIRLO
------------------------------------------------
El encargo pedía un «Índice de Volatilidad por Liga» definido así:

    IVL = desviación_estándar_goles / media_goles

con tres tramos: alta varianza por encima de 1,5 · media entre 1,2 y 1,5 ·
baja por debajo de 1,2. Y una lista de sospechosas: Brasileirão B, Liga
BetPlay, Libertadores, Primera Nacional.

**Medido sobre las 69 competiciones de fútbol con histórico (tres años):**

    IVL  mínimo 0,5408   mediana 0,6082   máximo 0,7237

Ninguna llega a 1,2, así que con esos cortes **las 69 salen «varianza baja» y
el filtro no bloquea nada nunca**. No es que el umbral esté un poco alto: la
fórmula no puede dar eso. El total de goles de un partido se parece a una
Poisson, y en una Poisson el coeficiente de variación es 1/√media. Con medias
de 1,8 a 3,3 goles, el IVL está condenado al rango 0,55-0,74.

Y hay algo peor que el rango. **El IVL no mide caos: mide cuántos goles se
marcan.** Ordena las ligas por 1/√media, así que la liga «más volátil» del
mundo es simplemente la que menos goles mete —Primera Nacional argentina,
1,84 de media, IVL 0,724—. La coincidencia con la lista de sospechosas del
encargo es real, pero es una coincidencia: las ligas sudamericanas y de
ascenso marcan menos goles, no son más impredecibles.

LA COMPROBACIÓN QUE LO ZANJA
----------------------------
Se cruzó el IVL con el ROI REAL de una pata en esa competición —ledger con
cuota de cierre y resultado, 34 competiciones, 14.647 patas del filtro de la
Soñadora—:

    IVL        vs ROI:  Pearson −0,031   Spearman −0,113
    peor cuartil de IVL  ROI −4,65 %  ·  mejor cuartil  ROI −3,69 %

Un punto de diferencia, y el peor cuartil incluye LaLiga mientras el mejor
incluye la Eredivisie. El IVL no separa nada.

LO QUE SÍ SEPARA, Y ES LO QUE ESTE MÓDULO USA
---------------------------------------------
El ERROR DE CALIBRACIÓN del modelo en esa competición, promediado sobre las
tres líneas que el ledger sin cuotas cubre (Más de 1,5 · Más de 2,5 · Ambos
marcan) — 47.794 partidos, 55 competiciones, sin necesidad de precio:

    ECE medio  vs ROI:  Pearson −0,460   Spearman −0,563
    peor cuartil de ECE   ROI −6,20 %   (3.105 patas)
    mejor cuartil de ECE  ROI −1,01 %   (5.469 patas)

**5,19 puntos de diferencia por pata**, que en un parlay de cuatro son −22,5 %
contra −4,0 %. Ésa es la señal, y no es nueva: es la misma idea que
`sonadora_motor.calibracion_floja` ya aplica pata a pata contra la
distribución de su mercado. Lo que faltaba era el agregado por COMPETICIÓN,
que es la unidad en la que se decide si una pata entra en una combinada.

Y ordena distinto que la intuición del encargo. Peor cuartil medido:
Conference League, Libertadores, AFC Champions, Sudamericana, Champions y la
**Premier League**. Mejor mitad: Brasileirão B, Argentina y Primera Nacional
— las tres que el encargo quería excluir.

QUÉ SE PUBLICA
--------------
El IVL se calcula y se publica igual, como DESCRIPTOR: sirve para decir «en
esta liga se marcan pocos goles», que es información real para una pata de
Más de 2,5. Lo que no hace es decidir bloqueos, y el JSON lleva el número que
lo justifica para que nadie lo vuelva a intentar sin medirlo.

Uso:
    python riesgo_liga.py              # mide y escribe el JSON
    python riesgo_liga.py --informe    # sólo imprime
"""

import argparse
import datetime as _dt
import glob
import json
import logging
import os
import sys
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = 'indice_volatilidad_liga.json'
LEDGER_TOT = 'pick_ledger_totales.csv'

# Años de histórico de goles para el IVL descriptivo.
ANIOS_IVL = 3

# Partidos mínimos para publicar el IVL de una competición.
N_MINIMO_IVL = 50

# Partidos mínimos para que el ECE de una competición sea una medición y no
# ruido. Es el mismo criterio que `mercado_estabilidad.MIN_N`.
N_MINIMO_ECE = 200

# Las tres líneas que el ledger sin cuotas cubre en todas las competiciones.
LINEAS_ECE = (('Goles 1.5', 'p_over_1.5', 'over_1.5_real'),
              ('Goles 2.5', 'p_over_2.5', 'over_2.5_real'),
              ('BTTS', 'p_btts', 'btts_real'))

ALTA, MEDIA, BAJA, SIN_MEDIR = 'alta', 'media', 'baja', 'sin_medir'

# Lo medido el 2026-09-15 al cruzar cada índice con el ROI real de la pata.
# Va dentro del JSON para que la decisión de usar el ECE y no el IVL viaje con
# el dato y no haya que fiarse de la bitácora.
CORRELACION_MEDIDA = {
    'fecha': '2026-09-15',
    'n_competiciones': 34,
    'n_patas': 14647,
    'fuente': 'pick_ledger.csv + pick_ledger_totales.csv (cuota de cierre real)',
    'ivl_vs_roi': {'pearson': -0.031, 'spearman': -0.113,
                   'roi_peor_cuartil': -0.0465, 'roi_mejor_cuartil': -0.0369},
    'ece_vs_roi': {'pearson': -0.460, 'spearman': -0.563,
                   'roi_peor_cuartil': -0.0620, 'roi_mejor_cuartil': -0.0101},
    'conclusion': 'el nivel de riesgo lo fija el ECE; el IVL se publica como '
                  'descriptor y no bloquea',
}


# ---------------------------------------------------------------------------
# El IVL, que se publica como descriptor
# ---------------------------------------------------------------------------
def _ivl_de_historicos(hoy: Optional[_dt.date] = None) -> Dict[str, Dict]:
    """Media, desviación e IVL del total de goles de cada competición."""
    import pandas as pd

    hoy = hoy or _dt.date.today()
    corte = pd.Timestamp(hoy) - pd.Timedelta(days=365 * ANIOS_IVL)
    fuera: Dict[str, Dict] = {}
    for ruta in sorted(glob.glob('historico_*.csv')):
        clave = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        try:
            d = pd.read_csv(ruta, usecols=['date', 'home_goals', 'away_goals'])
        except Exception:
            # los históricos que no son de fútbol (mlb, nba, nfl, tenis…) no
            # tienen esas columnas: no tienen IVL y no es un fallo
            continue
        d = d.dropna(subset=['home_goals', 'away_goals'])
        if not len(d):
            continue
        d['_f'] = pd.to_datetime(d['date'], errors='coerce')
        r = d.dropna(subset=['_f'])
        r = r[r['_f'] >= corte]
        # una competición que ya no se juega conserva su IVL de toda la serie
        # antes que quedarse sin número
        if len(r) < N_MINIMO_IVL:
            r = d.dropna(subset=['_f'])
        if len(r) < N_MINIMO_IVL:
            continue
        g = (r['home_goals'] + r['away_goals']).astype(float)
        media = float(g.mean())
        if media <= 0:
            continue
        sd = float(g.std(ddof=1))
        fuera[clave] = {
            'n_partidos': int(len(g)),
            'media_goles': round(media, 4),
            'sd_goles': round(sd, 4),
            'ivl': round(sd / media, 4),
            # varianza sobre media: 1,0 es una Poisson exacta. A diferencia del
            # IVL, éste sí quita el efecto del ritmo goleador — y tampoco
            # predijo el ROI (Pearson +0,158), así que también es descriptor.
            'vmr': round(float(g.var(ddof=1)) / media, 4),
            'desde': str(r['_f'].min().date()),
            'hasta': str(r['_f'].max().date()),
        }
    return fuera


# ---------------------------------------------------------------------------
# El ECE por competición, que es lo que decide
# ---------------------------------------------------------------------------
def _ece(p, y, n_cajas: int = 10) -> Optional[float]:
    """Error de calibración esperado. Misma cuenta que `validar_sonadora.ece`."""
    import numpy as np

    p, y = np.asarray(p, float), np.asarray(y, float)
    if not len(p):
        return None
    bordes = np.linspace(0.0, 1.0, n_cajas + 1)
    total = 0.0
    for i in range(n_cajas):
        lo, hi = bordes[i], bordes[i + 1]
        dentro = (p > lo) & (p <= hi) if i else (p >= lo) & (p <= hi)
        if not dentro.any():
            continue
        total += dentro.mean() * abs(p[dentro].mean() - y[dentro].mean())
    return float(total)


def _ece_de_ledger(ruta: str = LEDGER_TOT) -> Dict[str, Dict]:
    """ECE de cada competición en las tres líneas que el ledger cubre.

    NO NECESITA CUOTAS, y por eso llega donde el ROI no llega: el ledger con
    precio de cierre cubre 34 competiciones europeas y asiáticas, y deja fuera
    justo las sudamericanas que el encargo señalaba. Éste cubre 55.
    """
    import pandas as pd

    try:
        t = pd.read_csv(ruta)
    except Exception as e:
        logger.warning('[riesgo] sin %s: %s', ruta, e)
        return {}
    fuera: Dict[str, Dict] = {}
    for liga, g in t.groupby('liga'):
        detalle, errores = {}, []
        for etiqueta, pcol, rcol in LINEAS_ECE:
            if pcol not in g.columns or rcol not in g.columns:
                continue
            sub = g[g[pcol].notna() & g[rcol].notna()]
            if len(sub) < N_MINIMO_ECE:
                continue
            p = sub[pcol].astype(float).values
            y = sub[rcol].astype(float).round().values
            e = _ece(p, y)
            if e is None:
                continue
            detalle[etiqueta] = {'n': int(len(sub)), 'ece': round(e, 4),
                                 'sesgo': round(float(y.mean() - p.mean()), 4)}
            errores.append(e)
        if not errores:
            continue
        fuera[str(liga)] = {
            'ece_medio': round(sum(errores) / len(errores), 4),
            'n_lineas': len(errores),
            'n_partidos': int(len(g)),
            'por_linea': detalle,
        }
    return fuera


def _cuartiles(valores: List[float]) -> Optional[Dict[str, float]]:
    """p25 y p75 de la distribución observada, o None si no hay muestra.

    POR QUÉ CUARTILES Y NO UN UMBRAL FIJO. Es la lección que este proyecto ya
    pagó dos veces: el encargo del semáforo pedía «ECE < 0,05» y dejaba cero
    patas verdes, y el de este módulo pedía «IVL > 1,5» y deja cero ligas
    bloqueadas. Un umbral absoluto sobre un número cuya escala nadie midió es
    una regla que no puede fallar o que no puede pasar nadie. El cuartil no
    tiene ese problema: por construcción siempre marca a un cuarto.
    """
    v = sorted(float(x) for x in valores)
    if len(v) < 8:
        return None

    def _q(p):
        return round(v[int(p * (len(v) - 1))], 4)

    return {'p25': _q(0.25), 'mediana': _q(0.50), 'p75': _q(0.75),
            'min': round(v[0], 4), 'max': round(v[-1], 4), 'n_ligas': len(v)}


def construir(hoy: Optional[_dt.date] = None) -> Dict:
    """El índice entero: IVL descriptivo y nivel de riesgo medido."""
    hoy = hoy or _dt.date.today()
    ivl = _ivl_de_historicos(hoy)
    ece = _ece_de_ledger()
    cortes_ece = _cuartiles([v['ece_medio'] for v in ece.values()])
    cortes_ivl = _cuartiles([v['ivl'] for v in ivl.values()])

    ligas: Dict[str, Dict] = {}
    for clave in sorted(set(ivl) | set(ece)):
        a, b = ivl.get(clave) or {}, ece.get(clave) or {}
        e = b.get('ece_medio')
        nivel, motivo = SIN_MEDIR, 'sin ECE medido en esta competición'
        if e is not None and cortes_ece:
            if e > cortes_ece['p75']:
                nivel = ALTA
                motivo = (f"ECE {e} — peor cuarto de las "
                          f"{cortes_ece['n_ligas']} competiciones medidas "
                          f"(corte {cortes_ece['p75']})")
            elif e < cortes_ece['p25']:
                nivel = BAJA
                motivo = (f"ECE {e} — mejor cuarto (corte "
                          f"{cortes_ece['p25']})")
            else:
                nivel = MEDIA
                motivo = (f"ECE {e} — entre el cuartil 1 y el 3 "
                          f"({cortes_ece['p25']}-{cortes_ece['p75']})")
        entrada = {'nivel': nivel, 'motivo': motivo}
        if e is not None:
            entrada.update({'ece_medio': e, 'n_lineas_ece': b.get('n_lineas'),
                            'n_partidos_ece': b.get('n_partidos'),
                            'ece_por_linea': b.get('por_linea')})
        if a:
            entrada.update({
                'ivl': a['ivl'], 'vmr': a['vmr'],
                'media_goles': a['media_goles'], 'sd_goles': a['sd_goles'],
                'n_partidos_goles': a['n_partidos'],
                'ventana_goles': [a['desde'], a['hasta']],
                # lo que el IVL SÍ dice, que es el ritmo goleador
                'liga_de_pocos_goles': bool(
                    cortes_ivl and a['ivl'] > cortes_ivl['p75']),
            })
        ligas[clave] = entrada

    conteo = {n: sum(1 for v in ligas.values() if v['nivel'] == n)
              for n in (ALTA, MEDIA, BAJA, SIN_MEDIR)}
    return {
        'medido': True,
        'fecha': hoy.isoformat(),
        'n_competiciones': len(ligas),
        'fuente_nivel': 'ECE medio de Más 1,5 / Más 2,5 / Ambos marcan en '
                        f'{LEDGER_TOT} (sin cuotas)',
        'fuente_ivl': f'historico_*.csv, últimos {ANIOS_IVL} años',
        'cortes_ece': cortes_ece,
        'cortes_ivl': cortes_ivl,
        'ivl_bloquea': False,
        'ivl_umbrales_del_encargo': {
            'alta': 1.5, 'media': 1.2,
            'ligas_que_los_superan': sum(1 for v in ivl.values()
                                         if v['ivl'] > 1.2),
            'nota': 'ninguna competición llega a 1,2 porque el IVL de un '
                    'marcador tipo Poisson vale 1/raíz(media de goles), y las '
                    'medias van de 1,8 a 3,3 goles',
        },
        'correlacion_medida': CORRELACION_MEDIDA,
        'conteo_nivel': conteo,
        'ligas': ligas,
    }


# ---------------------------------------------------------------------------
# Lectura — lo que consumen el motor y la pantalla
# ---------------------------------------------------------------------------
_CACHE: Optional[Dict] = None


def indice(ruta: str = SALIDA) -> Dict:
    """El JSON en memoria. Si no está, se devuelve vacío y nada bloquea."""
    global _CACHE
    if _CACHE is None:
        try:
            with open(ruta, encoding='utf-8') as f:
                _CACHE = json.load(f) or {}
        except Exception as e:
            logger.debug('[riesgo] sin índice: %s', e)
            _CACHE = {}
    return _CACHE


def _olvidar() -> None:
    """Tira la caché. Para los tests y para el que regenera el índice."""
    global _CACHE
    _CACHE = None


def nivel_liga(clave_liga: Optional[str]) -> str:
    """`alta` · `media` · `baja` · `sin_medir`. Nunca lanza."""
    if not clave_liga:
        return SIN_MEDIR
    e = (indice().get('ligas') or {}).get(str(clave_liga))
    if not isinstance(e, dict):
        return SIN_MEDIR
    n = e.get('nivel')
    return n if n in (ALTA, MEDIA, BAJA) else SIN_MEDIR


def es_alto_riesgo(clave_liga: Optional[str]) -> bool:
    """¿Esta competición está en el peor cuarto por error de calibración?

    `sin_medir` NO es alto riesgo. Una competición sin ECE es una competición
    de la que no se sabe nada, y tratar el desconocimiento como culpa dejaría
    fuera a las que acaban de entrar al catálogo. La penalización por no estar
    medido ya existe y está declarada: `sonadora_motor.PENALIZA_SIN_MEDIR`.
    """
    return nivel_liga(clave_liga) == ALTA


def ficha(clave_liga: Optional[str]) -> Dict:
    """Todo lo publicado de esa competición, o un diccionario vacío."""
    if not clave_liga:
        return {}
    return dict((indice().get('ligas') or {}).get(str(clave_liga)) or {})


def explicacion(clave_liga: Optional[str]) -> str:
    """Una línea para la pantalla. Cadena vacía si no hay nada que decir."""
    f = ficha(clave_liga)
    if not f:
        return ''
    if f.get('nivel') == ALTA:
        return f"⚠️ Competición de alto riesgo: {f.get('motivo', '')}"
    if f.get('liga_de_pocos_goles') and f.get('media_goles'):
        return (f"ℹ️ Liga de pocos goles: {f['media_goles']:.2f} de media "
                f"por partido")
    return ''


# ---------------------------------------------------------------------------
def _imprimir(doc: Dict) -> None:
    print('=' * 86)
    print('ÍNDICE DE RIESGO POR COMPETICIÓN')
    print('=' * 86)
    print(f"{doc['n_competiciones']} competiciones   ·   "
          f"nivel por {doc['fuente_nivel']}")
    c = doc.get('conteo_nivel') or {}
    print(f"alta {c.get('alta', 0)}   media {c.get('media', 0)}   "
          f"baja {c.get('baja', 0)}   sin medir {c.get('sin_medir', 0)}")
    u = doc.get('ivl_umbrales_del_encargo') or {}
    ci = doc.get('cortes_ivl') or {}
    print(f"\nIVL medido: {ci.get('min')} a {ci.get('max')} "
          f"(mediana {ci.get('mediana')}) — competiciones por encima de 1,2: "
          f"{u.get('ligas_que_los_superan')}")
    print()
    print(f"{'competición':24s} {'nivel':9s} {'ECE':>7s} {'IVL':>7s} "
          f"{'goles':>6s} {'VMR':>6s}")
    orden = sorted((doc.get('ligas') or {}).items(),
                   key=lambda kv: (-(kv[1].get('ece_medio') or -1), kv[0]))
    for clave, v in orden:
        print(f"{clave[:24]:24s} {v['nivel']:9s} "
              f"{(v.get('ece_medio') or 0):>7.4f} {(v.get('ivl') or 0):>7.4f} "
              f"{(v.get('media_goles') or 0):>6.2f} "
              f"{(v.get('vmr') or 0):>6.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--informe', action='store_true', help='no escribe el JSON')
    args = ap.parse_args()
    doc = construir()
    try:
        _imprimir(doc)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            json.dumps(doc, ensure_ascii=False, indent=1).encode('utf-8'))
    if not args.informe:
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        _olvidar()
        print(f'\nEscrito {SALIDA}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
