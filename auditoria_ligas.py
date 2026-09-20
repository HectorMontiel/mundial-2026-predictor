#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v230 — QUÉ HACE CADA LIGA, Y DÓNDE EL MODELO NO LA ENTIENDE.

DE DÓNDE SALE ESTO
------------------
El usuario armó un parley de diez patas y perdió dos. Las dos eran de la MLS:

    NE 4 - 2 ORL    «Under 4.5 goles»   →  seis goles
    POR 0 - 1 ATL   «Gana o empata POR» →  perdió

Y la pregunta que hizo es la correcta: ¿está bien calibrada esa liga, o hay
ligas con un carácter propio que el modelo no está recogiendo? Porque en la MLS
es notoriamente común que marquen los dos, y en otras competiciones lo habitual
son las tarjetas o los córners.

QUÉ MIDE ESTE MÓDULO
--------------------
Para CADA liga y CADA mercado, lo que el modelo prometió contra lo que pasó:

    prometido   la media de la probabilidad que publicó el modelo
    real        la frecuencia con que ocurrió de verdad
    sesgo       prometido − real, en puntos porcentuales

Un sesgo positivo significa que el modelo dice «Over» —o «BTTS», o lo que sea—
más de lo que ocurre, y por tanto empuja al usuario a un lado que no se cumple.
Negativo, al revés: la liga da MÁS de lo que el modelo cree, y ahí es donde se
están perdiendo apuestas al Over que sí habrían entrado.

POR QUÉ WILSON Y NO UN PORCENTAJE SUELTO
----------------------------------------
Con 1.830 partidos de MLS un sesgo de dos puntos significa algo; con 180 de una
liga pequeña, no significa nada. El intervalo de Wilson lo dice sin que haya
que fiarse del ojo: si el cero cae dentro, el sesgo es compatible con el azar y
NO se toca la liga. Es la misma disciplina que gobierna el resto del proyecto,
y la que evita «arreglar» cincuenta y cinco ligas persiguiendo ruido.

Y BENJAMINI-HOCHBERG, PORQUE SON CINCUENTA Y CINCO LIGAS
--------------------------------------------------------
Mirando 55 ligas × 4 mercados son 220 pruebas. A un 5 % de falsos positivos,
once saldrían «significativas» sin que pase nada. La corrección de
Benjamini-Hochberg controla la proporción de falsos hallazgos sobre el conjunto
en vez de sobre cada prueba suelta, que es lo que hace falta cuando se busca en
una rejilla. Sin ella, este fichero sería una máquina de fabricar patrones.

ESTO NO CAMBIA NADA. Mide y escribe `auditoria_ligas.json`.
"""
import io
import json
import logging
import math
import sys
from typing import Dict, List, Optional

logger = logging.getLogger('auditoria_ligas')

SALIDA = 'auditoria_ligas.json'
# Por debajo de esto, una liga no tiene con qué contestar. 150 partidos dan un
# intervalo de Wilson de ±8 puntos sobre una base del 50 %, que ya es demasiado
# ancho para decidir nada; por debajo es puro ruido.
MIN_PARTIDOS = 150
# Umbral de la tasa de falsos hallazgos de Benjamini-Hochberg.
FDR = 0.10

# Los mercados que el ledger puede juzgar, con la columna de lo prometido y la
# de lo que pasó. Córners y tarjetas NO están aquí: viven en los históricos por
# competición y los audita `_corners_tarjetas`.
MERCADOS = (
    ('over_1.5', 'p_over_1.5', 'over_1.5_real', 'Más de 1,5 goles'),
    ('over_2.5', 'p_over_2.5', 'over_2.5_real', 'Más de 2,5 goles'),
    ('over_3.5', 'p_over_3.5', 'over_3.5_real', 'Más de 3,5 goles'),
    ('btts', 'p_btts', 'btts_real', 'Ambos marcan'),
)


def wilson(exitos: int, n: int, z: float = 1.96):
    """Intervalo de Wilson. Con n pequeño, el normal se sale de [0,1]."""
    if n <= 0:
        return (0.0, 1.0)
    p = exitos / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    medio = (z / d) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centro - medio), min(1.0, centro + medio))


def _p_valor(prometido: float, exitos: int, n: int) -> float:
    """Prueba binomial aproximada de que la tasa real sea `prometido`.

    Normal con corrección de continuidad. Con n >= 150 y p lejos de los
    extremos la aproximación es buena, y es lo que permite no arrastrar scipy
    a un módulo que sólo cuenta.
    """
    if n <= 0:
        return 1.0
    p0 = min(max(float(prometido), 1e-6), 1 - 1e-6)
    sigma = math.sqrt(p0 * (1 - p0) * n)
    if sigma <= 0:
        return 1.0
    z = (abs(exitos - p0 * n) - 0.5) / sigma
    if z <= 0:
        return 1.0
    # 2 * (1 - Phi(z)), con la Phi de la libreria estandar
    return max(0.0, min(1.0, 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2))))))


def benjamini_hochberg(filas: List[Dict], alfa: float = FDR) -> None:
    """Marca `significativo` en las filas que sobreviven a la corrección.

    Se ordena por p-valor y se busca el mayor `k` tal que p(k) <= k/m * alfa.
    Todo lo que esté por debajo de ese corte se declara hallazgo; el resto, no.
    Se escribe el propio umbral en cada fila para que quien lea el informe vea
    por cuánto pasó o por cuánto no.
    """
    vivas = [f for f in filas if f.get('p_valor') is not None]
    m = len(vivas)
    if not m:
        return
    vivas.sort(key=lambda f: f['p_valor'])
    corte = 0
    for i, f in enumerate(vivas, start=1):
        f['umbral_bh'] = round(i / m * alfa, 6)
        if f['p_valor'] <= i / m * alfa:
            corte = i
    for i, f in enumerate(vivas, start=1):
        f['significativo'] = i <= corte


def por_liga(minimo: int = MIN_PARTIDOS) -> Dict:
    """La ficha de cada liga: qué prometió el modelo y qué pasó."""
    import calibrador_goles as cg

    t = cg._datos()
    fuera: Dict[str, Dict] = {}
    todas: List[Dict] = []

    for liga, sub in t.groupby('liga'):
        if len(sub) < minimo:
            continue
        ficha = {'liga': str(liga), 'n': int(len(sub)), 'mercados': {}}
        for clave, col_p, col_y, etiqueta in MERCADOS:
            if col_p not in sub.columns or col_y not in sub.columns:
                continue
            m = sub[col_p].notna() & sub[col_y].notna()
            n = int(m.sum())
            if n < minimo:
                continue
            prometido = float(sub.loc[m, col_p].mean())
            exitos = int(sub.loc[m, col_y].sum())
            real = exitos / n
            lo, hi = wilson(exitos, n)
            fila = {
                'liga': str(liga), 'mercado': clave, 'etiqueta': etiqueta,
                'n': n,
                'prometido': round(prometido, 4),
                'real': round(real, 4),
                'sesgo': round(prometido - real, 4),
                'wilson_bajo': round(lo, 4), 'wilson_alto': round(hi, 4),
                # ¿la promesa cae DENTRO del intervalo de lo observado? si sí,
                # el desvío es compatible con el azar y no hay nada que tocar
                'dentro_del_intervalo': bool(lo <= prometido <= hi),
                'p_valor': _p_valor(prometido, exitos, n),
            }
            ficha['mercados'][clave] = fila
            todas.append(fila)
        if ficha['mercados']:
            fuera[str(liga)] = ficha

    benjamini_hochberg(todas)
    return {'ligas': fuera, 'filas': todas, 'minimo': minimo, 'fdr': FDR}


def caracter_de_liga(doc: Dict) -> List[Dict]:
    """Las ligas cuyo carácter se aparta de la media, medido y no supuesto.

    «En la MLS marcan los dos» es una frase que todo el mundo repite; esto la
    convierte en un número y, sobre todo, dice si el MODELO ya lo sabe. Una
    liga puede ser muy goleadora y estar perfectamente calibrada —el modelo ya
    lo recoge— y eso NO es un hallazgo. El hallazgo es la liga donde lo real se
    aparta de lo prometido.
    """
    fuera = []
    for fila in doc.get('filas', []):
        if not fila.get('significativo'):
            continue
        fuera.append({
            'liga': fila['liga'], 'mercado': fila['mercado'],
            'etiqueta': fila['etiqueta'], 'n': fila['n'],
            'prometido': fila['prometido'], 'real': fila['real'],
            'sesgo': fila['sesgo'],
            # el lado al que hay que corregir, dicho en el idioma del que apuesta
            'lado': ('el modelo se queda CORTO: la liga da más'
                     if fila['sesgo'] < 0 else
                     'el modelo se pasa: la liga da menos'),
        })
    fuera.sort(key=lambda f: -abs(f['sesgo']))
    return fuera


# Lo que define el carácter de una competición, y de dónde sale cada cosa en
# los históricos por liga. El par de columnas se suma: lo que se apuesta es el
# TOTAL del partido, no el de un bando.
_NO_SON_LIGAS = {'partidos', 'jugadores', 'agrupado'}

RASGOS = (
    ('goles', 'home_goals', 'away_goals', 'goles por partido'),
    ('corners', 'home_corners', 'away_corners', 'córners por partido'),
    ('amarillas', 'home_yellow', 'away_yellow', 'amarillas por partido'),
    ('rojas', 'home_red', 'away_red', 'rojas por partido'),
    ('remates_arco', 'home_shots_on', 'away_shots_on', 'remates a puerta'),
    ('faltas', 'home_fouls', 'away_fouls', 'faltas por partido'),
)


def caracter_por_historico(minimo: int = MIN_PARTIDOS) -> Dict:
    """Cuánto da CADA liga de cada cosa, y cuánto se aparta de la media.

    Esto no juzga al modelo: describe la competición. Sirve para lo que el
    usuario pidió —«hay ligas donde es muy común que marquen los dos, o donde
    hay más tarjetas»— y para saber a qué línea conviene irse: en una liga de
    3,1 goles por partido, el «más de 2,5» es otra apuesta distinta que en una
    de 2,972.

    Se mide en DESVIACIONES TÍPICAS sobre el conjunto de ligas, no en unidades.
    Decir «la Champions tiene 4,2 amarillas» no dice nada por sí solo; decir que
    está a 1,8 sigmas por encima de la media de las competiciones sí.
    """
    import glob
    import os
    import pandas as pd

    filas: Dict[str, Dict] = {}
    for ruta in sorted(glob.glob('historico_*.csv')):
        liga = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        # `historico_partidos.csv` no es una competición: es el agregado de
        # todas. Colarlo entre las ligas lo pondría a competir consigo mismo en
        # la comparación de sigmas y falsearía la media del conjunto.
        if liga in _NO_SON_LIGAS:
            continue
        try:
            df = pd.read_csv(ruta)
        except Exception as e:
            logger.debug('[caracter] %s ilegible: %s', ruta, e)
            continue
        if len(df) < minimo:
            continue
        ficha = {'liga': liga, 'n': int(len(df)), 'rasgos': {}}
        for clave, ch, ca, etiqueta in RASGOS:
            if ch not in df.columns or ca not in df.columns:
                continue
            serie = (pd.to_numeric(df[ch], errors='coerce')
                     + pd.to_numeric(df[ca], errors='coerce')).dropna()
            if len(serie) < minimo:
                continue
            ficha['rasgos'][clave] = {'etiqueta': etiqueta,
                                      'media': round(float(serie.mean()), 3),
                                      'n': int(len(serie))}
        # «Ambos marcan» no es una media: es una frecuencia, y es el rasgo por
        # el que empezó todo esto.
        if {'home_goals', 'away_goals'} <= set(df.columns):
            gh = pd.to_numeric(df.home_goals, errors='coerce')
            ga = pd.to_numeric(df.away_goals, errors='coerce')
            m = gh.notna() & ga.notna()
            if int(m.sum()) >= minimo:
                ficha['rasgos']['btts'] = {
                    'etiqueta': 'ambos marcan',
                    'media': round(float(((gh[m] >= 1) & (ga[m] >= 1)).mean()), 4),
                    'n': int(m.sum())}
        if ficha['rasgos']:
            filas[liga] = ficha

    # Normalización: cuántas sigmas se aparta cada liga de la media de ligas.
    for clave in [r[0] for r in RASGOS] + ['btts']:
        vals = [f['rasgos'][clave]['media'] for f in filas.values()
                if clave in f['rasgos']]
        if len(vals) < 5:
            continue
        mu = sum(vals) / len(vals)
        var = sum((v - mu) ** 2 for v in vals) / max(1, len(vals) - 1)
        sd = math.sqrt(var)
        for f in filas.values():
            if clave not in f['rasgos']:
                continue
            f['rasgos'][clave]['media_de_ligas'] = round(mu, 4)
            f['rasgos'][clave]['sigmas'] = (
                round((f['rasgos'][clave]['media'] - mu) / sd, 2) if sd > 0
                else 0.0)
    return filas


def extremos(caracter: Dict, clave: str, n: int = 6):
    """Las `n` ligas que más y las que menos dan de ese rasgo."""
    vivas = [(f['liga'], f['rasgos'][clave]['media'],
              f['rasgos'][clave].get('sigmas', 0.0), f['rasgos'][clave]['n'])
             for f in caracter.values() if clave in f['rasgos']]
    vivas.sort(key=lambda x: -x[1])
    return vivas[:n], vivas[-n:]


# ---------------------------------------------------------------------------
# LO QUE LEE LA PANTALLA
# ---------------------------------------------------------------------------
# Qué rasgo mira cada mercado. Sin este puente, el informe se queda en un JSON
# que nadie abre: el usuario pidió que los patrones «se reflejen en el semáforo
# de las apuestas del día», y esto es lo que los lleva hasta allí.
_RASGO_DE_MERCADO = (
    ('corner', 'corners'),
    ('córner', 'corners'),
    ('tarjeta', 'amarillas'),
    ('ambos marcan', 'btts'),
    ('btts', 'btts'),
    ('gol', 'goles'),
)
# Por debajo de una sigma, la liga no tiene nada particular que contar y
# decirlo sería ruido en la tarjeta. El usuario ya avisó de que sobra texto.
MIN_SIGMAS = 1.0

_CACHE_CAR: Optional[Dict] = None


def _caracter_cacheado() -> Dict:
    global _CACHE_CAR
    if _CACHE_CAR is not None:
        return _CACHE_CAR
    _CACHE_CAR = {}
    try:
        import os
        if os.path.exists(SALIDA):
            with open(SALIDA, encoding='utf-8') as f:
                _CACHE_CAR = (json.load(f) or {}).get('caracter') or {}
    except Exception as e:
        logger.debug('[caracter] no se pudo leer %s: %s', SALIDA, e)
    return _CACHE_CAR


def rasgo_de_liga(clave_liga, mercado) -> str:
    """Una línea sobre lo que esa liga hace en ese mercado, o ''.

    Devuelve '' cuando la liga no se aparta de la media: una competición del
    montón no tiene nada que añadir, y rellenar con «está en la media» sería
    gastar renglón sin informar.
    """
    car = _caracter_cacheado().get(str(clave_liga or '').strip().lower())
    if not car:
        return ''
    txt = str(mercado or '').lower()
    clave = next((r for pista, r in _RASGO_DE_MERCADO if pista in txt), None)
    if not clave:
        return ''
    r = (car.get('rasgos') or {}).get(clave)
    if not r:
        return ''
    s = float(r.get('sigmas') or 0.0)
    if abs(s) < MIN_SIGMAS:
        return ''
    valor = float(r.get('media'))
    if clave == 'btts':
        cifra = '%.0f %% de los partidos' % (valor * 100)
    else:
        cifra = ('%.1f' % valor).replace('.', ',')
    return ('%s: %s %s — %s que la media de ligas (%+.1f σ)'
            % (str(clave_liga).replace('_', ' ').upper(), cifra,
               r.get('etiqueta', clave),
               'más' if s > 0 else 'menos', s))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    doc = por_liga()
    hallazgos = caracter_de_liga(doc)
    doc['hallazgos'] = hallazgos

    print('ligas con al menos %d partidos: %d' % (MIN_PARTIDOS,
                                                  len(doc['ligas'])))
    print('pruebas: %d · corrección de Benjamini-Hochberg al %.0f %%'
          % (len(doc['filas']), FDR * 100))
    print()
    print('HALLAZGOS (%d): ligas donde lo real se aparta de lo prometido'
          % len(hallazgos))
    print('%-22s %-18s %6s %10s %8s %9s' % ('liga', 'mercado', 'n',
                                            'prometido', 'real', 'sesgo'))
    for h in hallazgos[:30]:
        print('%-22s %-18s %6d %10.4f %8.4f %+9.4f'
              % (h['liga'], h['mercado'], h['n'], h['prometido'],
                 h['real'], h['sesgo']))

    car = caracter_por_historico()
    doc['caracter'] = car
    print()
    print('=' * 72)
    print('CARÁCTER DE CADA COMPETICIÓN (%d ligas con histórico)' % len(car))
    for clave, etq in (('goles', 'GOLES'), ('btts', 'AMBOS MARCAN'),
                       ('corners', 'CÓRNERS'), ('amarillas', 'AMARILLAS')):
        alto, bajo = extremos(car, clave)
        if not alto:
            continue
        print()
        print('%s — más:' % etq)
        for l, v, s, n in alto:
            print('   %-24s %7.3f  (%+.1f sigmas, n=%d)' % (l, v, s, n))
        print('%s — menos:' % etq)
        for l, v, s, n in reversed(bajo):
            print('   %-24s %7.3f  (%+.1f sigmas, n=%d)' % (l, v, s, n))

    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print('-> %s' % SALIDA)
    return 0


if __name__ == '__main__':
    sys.exit(main())
