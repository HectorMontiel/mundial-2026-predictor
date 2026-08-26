#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v172 — EL CONTEXTO DEL PARTIDO: H2H, FORMA Y NIVEL.

El caso que lo provoca
----------------------
La aplicación recomendó «AmaZulu o empate» con Score 1,35 en un
Mamelodi Sundowns – AmaZulu. Mirado el histórico, Mamelodi ha ganado **8 de los
últimos 10** cruces (1 empate, 1 derrota). La recomendación era una trampa.

QUÉ FALLÓ DE VERDAD, Y NO ERA EL H2H
------------------------------------
La casa ya sabía todo esto. Su propio precio daba:

    Mamelodi 78,85 %  ·  empate 14,72 %  ·  AmaZulu 6,43 %

o sea que «AmaZulu o empate» vale **21,15 %**, y a cuota 3,00 su Score real es
0,63 — de los peores del partido. La aplicación le calculó 1,35 porque la doble
oportunidad era el ÚNICO mercado que no se contrastaba contra el precio de la
casa: entraba con `implicita=None`, sin encogimiento y sin control de cordura.

Así que el arreglo de raíz es ése —la doble oportunidad se contrasta como todo
lo demás, y su implícita sale de sumar los dos lados del 1X2 devigado, no de
devigar la familia de dobles (sus tres selecciones suman 2, no 1)— y este módulo
es lo que se añade encima: el contexto que el usuario quiere VER, y una veto
para lo que contradice al histórico.

CÓMO SE USA EL FACTOR, Y POR QUÉ NO MULTIPLICA SIEMPRE
-------------------------------------------------------
Multiplicar la probabilidad por un factor de H2H **cuando ya hay precio de la
casa** es contar la misma información dos veces: la casa le da a AmaZulu un
6,43 % precisamente porque pierde siempre. Y rompe la calibración, que es lo que
esta aplicación lleva seis versiones arreglando — dos probabilidades
multiplicadas por factores distintos dejan de sumar 1.

Por eso el factor:

  · **modula** la probabilidad sólo donde NO hay precio con el que contrastar,
    que es donde el modelo va solo y el H2H sí añade algo;
  · **veta** las recomendaciones que contradicen un H2H dominante, tenga el
    precio que tenga — que es lo que el usuario pidió y no cuesta calibración
    ninguna, porque un filtro no cambia ningún número;
  · y **se enseña siempre**, que era la otra mitad del encargo.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger('contexto_partido')

N_H2H = 10          # cruces que se miran
N_FORMA = 5         # partidos recientes por equipo
MIN_H2H = 4         # con menos cruces no se afirma nada

# Los dos cortes del veto. Un equipo que gana menos de un tercio de los cruces
# frente a un rival que gana más de dos tercios no es «ligeramente peor».
DOMINIO_CLARO = 0.65
FACTOR_MINIMO = 0.40        # el suelo del factor, como se pidió
FACTOR_MAXIMO = 1.30        # y su techo

_CACHE: Dict[str, Dict] = {}


def _resultado(gh, ga) -> str:
    if gh is None or ga is None:
        return ''
    return 'G' if gh > ga else ('P' if gh < ga else 'E')


def h2h(clave_liga: str, home: str, away: str, n: int = N_H2H) -> Dict:
    """
    Los últimos cruces entre los dos, mire quién jugara en casa.

    Devuelve `{'n', 'v_home', 'empates', 'v_away', 'goles', 'racha'}` con el
    recuento SIEMPRE desde el punto de vista del local de HOY: si el cruce se
    jugó al revés, el resultado se da la vuelta. Sin esa vuelta, un 3-0 del
    visitante de hoy en su casa contaría como victoria del local.
    """
    vacio = {'n': 0, 'v_home': 0, 'empates': 0, 'v_away': 0, 'goles': None,
             'racha': ''}
    if not (clave_liga and home and away):
        return vacio
    ck = 'h2h|%s|%s|%s|%d' % (clave_liga, home, away, n)
    if ck in _CACHE:
        return _CACHE[ck]
    try:
        import pandas as pd
        import rendimiento_equipos as rq
        d = rq._historico(clave_liga)
        if d is None or getattr(d, 'empty', True):
            _CACHE[ck] = vacio
            return vacio
        m = d[((d['home_team'] == home) & (d['away_team'] == away))
              | ((d['home_team'] == away) & (d['away_team'] == home))]
        m = m.sort_values('date').tail(n)
        v_h = v_a = emp = 0
        goles, racha = [], []
        for _, r in m.iterrows():
            gh = pd.to_numeric(r.get('home_goals'), errors='coerce')
            ga = pd.to_numeric(r.get('away_goals'), errors='coerce')
            if pd.isna(gh) or pd.isna(ga):
                continue
            goles.append(float(gh) + float(ga))
            # se pone SIEMPRE en el marco del local de hoy
            if r['home_team'] == home:
                res = _resultado(gh, ga)
            else:
                res = _resultado(ga, gh)
            racha.append(res)
            if res == 'G':
                v_h += 1
            elif res == 'P':
                v_a += 1
            else:
                emp += 1
        total = v_h + v_a + emp
        salida = {'n': total, 'v_home': v_h, 'empates': emp, 'v_away': v_a,
                  'goles': (round(sum(goles) / len(goles), 2) if goles
                            else None),
                  'racha': ''.join(racha[-6:])}
    except Exception as e:
        logger.debug('[contexto] h2h %s-%s: %s', home, away, e)
        salida = vacio
    _CACHE[ck] = salida
    return salida


def forma(clave_liga: str, equipo: str, n: int = N_FORMA) -> Dict:
    """
    Los últimos partidos del equipo, con sus puntos por partido.

    Se apoya en `rendimiento_equipos.forma`, que es de donde salen las rachas
    que la tarjeta ya pinta. Dos caminos al mismo número acaban divergiendo.
    """
    vacio = {'n': 0, 'racha': '', 'ppp': None, 'gf': None, 'gc': None}
    try:
        import rendimiento_equipos as rq
        f = rq.forma(clave_liga, equipo, n=n) or {}
    except Exception as e:
        logger.debug('[contexto] forma %s: %s', equipo, e)
        return vacio
    racha = str(f.get('racha') or '')
    if not racha:
        return vacio
    pts = sum(3 if c == 'G' else (1 if c == 'E' else 0) for c in racha)
    return {'n': f.get('n') or len(racha), 'racha': racha,
            'ppp': round(pts / max(len(racha), 1), 2),
            'gf': f.get('gf_media'), 'gc': f.get('gc_media')}


def elo(clave_liga: str, home: str, away: str) -> Optional[float]:
    """Diferencia de ELO entre los dos, o `None`. Positiva = local mejor."""
    try:
        import pandas as pd
        d = pd.read_csv('elo_actual.csv')
        col_eq = 'equipo' if 'equipo' in d.columns else d.columns[0]
        col_el = 'elo' if 'elo' in d.columns else d.columns[-1]
        m = {str(r[col_eq]): float(r[col_el]) for _, r in d.iterrows()}
        if home in m and away in m:
            return round(m[home] - m[away], 1)
    except Exception as e:
        logger.debug('[contexto] elo: %s', e)
    return None


def de_partido(clave_liga: str, home: str, away: str) -> Dict:
    """Todo el contexto de un partido, listo para pintar y para vetar."""
    cr = h2h(clave_liga, home, away)
    fh = forma(clave_liga, home)
    fa = forma(clave_liga, away)
    d_elo = elo(clave_liga, home, away)
    dominio = None
    if cr['n'] >= MIN_H2H:
        dominio = cr['v_home'] / cr['n']
    return {'h2h': cr, 'forma_home': fh, 'forma_away': fa, 'elo': d_elo,
            'dominio_home': dominio,
            'factor_home': _factor(dominio, fh, fa, d_elo, True),
            'factor_away': _factor(dominio, fh, fa, d_elo, False)}


def _factor(dominio, fh, fa, d_elo, es_home: bool) -> float:
    """
    El multiplicador de ese bando: 0,40 si nunca gana, 1,30 si gana casi todo.

    Se construye con las tres piezas y se recorta a la horquilla pedida. Con
    pocos cruces el H2H pesa poco: la muestra manda sobre la opinión.
    """
    f = 1.0
    if dominio is not None:
        d = dominio if es_home else (1.0 - dominio)
        # 0,5 de dominio -> 1,0; 0,9 -> 1,3; 0,1 -> 0,55
        f *= 1.0 + (d - 0.5) * 1.5
    ppp_h = (fh or {}).get('ppp')
    ppp_a = (fa or {}).get('ppp')
    if ppp_h is not None and ppp_a is not None:
        mio, suyo = (ppp_h, ppp_a) if es_home else (ppp_a, ppp_h)
        f *= 1.0 + (mio - suyo) * 0.10
    if d_elo is not None:
        mio = d_elo if es_home else -d_elo
        f *= 1.0 + max(-0.20, min(0.20, mio / 1000.0))
    return round(max(FACTOR_MINIMO, min(FACTOR_MAXIMO, f)), 3)


# El recorte del factor de lambda. Cinco partidos son POCOS: un equipo que
# metio 2 goles en cinco no es un equipo de 0,4 goles, es un equipo con una
# mala racha de cinco partidos. Sin recorte, la media movil de cinco haria
# saltar la lambda un 60 % arriba y abajo cada semana.
LAMBDA_MIN, LAMBDA_MAX = 0.80, 1.20


def factor_lambda(clave_liga: str, equipo: str, mercado: str = 'goles',
                  n: int = N_FORMA) -> float:
    """
    v173 — CUANTO SE DESVIA ESTE EQUIPO DE SI MISMO EN LOS ULTIMOS `n`.

    Se pidio que la lambda esperada baje cuando un equipo no anota y suba
    cuando esta en racha. Se hace comparando su media RECIENTE contra su media
    LARGA —no contra la de la liga—, porque lo que se quiere capturar es un
    cambio de estado del equipo, no lo bueno que es en absoluto: eso ya esta en
    la lambda base.

    Recortado a [0,80 · 1,20]. Cinco partidos son pocos y sin recorte la lambda
    saltaria un 60 % cada semana.

    Devuelve 1,0 —sin efecto— cuando no hay muestra para comparar.
    """
    try:
        import pandas as pd
        import rendimiento_equipos as rq
        d = rq._historico(clave_liga)
        if d is None or getattr(d, 'empty', True):
            return 1.0
        col_h, col_a = {'goles': ('home_goals', 'away_goals'),
                        'corners': ('home_corners', 'away_corners'),
                        'tarjetas': ('home_yellow', 'away_yellow'),
                        }.get(mercado, ('home_goals', 'away_goals'))
        if col_h not in d.columns:
            return 1.0
        suyos = d[(d['home_team'] == equipo) | (d['away_team'] == equipo)]
        suyos = suyos.sort_values('date')
        if len(suyos) < 12:
            return 1.0

        def _serie(df):
            v = []
            for _, row in df.iterrows():
                x = (row.get(col_h) if row['home_team'] == equipo
                     else row.get(col_a))
                x = pd.to_numeric(x, errors='coerce')
                if not pd.isna(x):
                    v.append(float(x))
            return v
        largo = _serie(suyos.tail(40))
        corto = _serie(suyos.tail(n))
        if len(corto) < 3 or len(largo) < 10:
            return 1.0
        m_l = sum(largo) / len(largo)
        m_c = sum(corto) / len(corto)
        if m_l <= 0:
            return 1.0
        return round(max(LAMBDA_MIN, min(LAMBDA_MAX, m_c / m_l)), 3)
    except Exception as e:
        logger.debug('[contexto] factor lambda %s/%s: %s', equipo, mercado, e)
        return 1.0


def veta(ctx: Dict, apuesta: str, home: str, away: str) -> Optional[str]:
    """
    ¿Contradice esta apuesta al histórico? Devuelve el motivo, o `None`.

    Es un FILTRO, no un ajuste: no cambia ninguna probabilidad, así que no
    puede romper la calibración. Sólo dice «esto no se propone».
    """
    if not ctx:
        return None
    cr = ctx.get('h2h') or {}
    dom = ctx.get('dominio_home')
    if dom is None or cr.get('n', 0) < MIN_H2H:
        return None
    etq = str(apuesta or '')
    if max(dom, 1 - dom) < DOMINIO_CLARO:
        return None
    if dom >= DOMINIO_CLARO:
        debil, fuerte, ganados = away, home, cr['v_home']
    else:
        debil, fuerte, ganados = home, away, cr['v_away']
    # Se veta la apuesta que NOMBRA al debil sin nombrar al fuerte. Eso cubre
    # «Gana AmaZulu» y «AmaZulu o empate» —la doble del debil, que es la
    # trampa— y deja pasar «AmaZulu o Mamelodi», que los nombra a los dos.
    if debil and debil in etq and fuerte not in etq:
        return ('%s ha ganado %d de los ultimos %d cruces'
                % (fuerte, ganados, cr['n']))
    return None
