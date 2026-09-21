#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v209 — LA CAPA DE AUDITORÍA: cada pick del día, explicado y con su riesgo.

QUÉ ES ESTO Y QUÉ NO ES
-----------------------
Es una capa de LECTURA sobre un pick que el barrido ya produjo. No entrena, no
predice y no reordena la Sección 1: recibe el diccionario del pick, le pregunta
a los módulos que ya miden cada cosa, y devuelve una ficha con el veredicto,
las banderas, el stake y el porqué en texto llano.

El encargo la pedía como ocho módulos. Siete de los ocho YA EXISTÍAN en este
repositorio, medidos, y lo que faltaba era el ensamblador. Esto es ese
ensamblador, más las cuatro reglas que de verdad no estaban escritas:
divergencia con el mercado, cuota inflada, racha negativa y el tope de dos
patas por partido.

DE DÓNDE SALE CADA CAPA DEL ENCARGO
-----------------------------------
    M1 correlación con el mercado ... `clasificador.consenso_sin_margen` para
                                      el devig, `cuota_justa` del propio pick.
                                      NUEVO aquí: la bandera de divergencia.
    M2 contexto en tiempo real ...... `contexto_ampliado` (aclimatación, lo
                                      único medido) y `filtro_contexto` (el
                                      entrenador). NUEVO aquí: enchufar la
                                      fuente, que estaba escrita y suelta.
    M3 volatilidad por liga ......... `riesgo_liga`. Ver la nota de abajo.
    M4 correlación entre mercados ... `match_parlay`. NUEVO aquí: el tope de
                                      dos patas del mismo partido.
    M5 filtros anti-trampa .......... `clasificador.semaforo` ya traía dos.
                                      NUEVO aquí: cuota inflada y racha.
    M6 calibración .................. `alpha_finder.brier_liga` y el ECE por
                                      competición de `riesgo_liga`.
    M7 explicabilidad ............... este módulo, entero.
    M8 banca ........................ `bankroll_manager` (Kelly fraccional) y
                                      `montecarlo_sim` (probabilidad de ruina).

LAS DOS COSAS DEL ENCARGO QUE NO SE IMPLEMENTAN COMO PEDÍA, Y POR QUÉ
--------------------------------------------------------------------
1. **La tabla de riesgo por liga escrita a mano.** El encargo fija Premier y
   LaLiga en 1,0 y Brasileirão B, Liga BetPlay y Primera Nacional en 1,8. Este
   repositorio ya midió exactamente eso en `riesgo_liga.py`, cruzando el índice
   con el ROI real de 14.647 patas con cuota de cierre, y el orden sale AL
   REVÉS: el peor cuartil por error de calibración incluye la **Premier
   League**, la Champions y la Libertadores; en la mejor mitad están
   **Brasileirão B, Argentina y Primera Nacional**, las tres que el encargo
   quería bloquear.

   Así que el `factor_riesgo_liga` de la ficha SE PUBLICA con los valores que
   el encargo pide —1,0 · 1,3 · 1,8— pero quien decide cuál toca es el ECE
   medido de esa competición, no su nombre. La tabla literal queda abajo en
   `TABLA_DEL_ENCARGO`, marcada como refutada, para que nadie la reintroduzca
   sin volver a medir.

2. **«Nunca recomendar una apuesta con EV negativo».** El EV se calcula, se
   publica y se etiqueta tal y como pide el encargo, con sus tres tramos. Lo
   que esta capa NO hace es promover a la Sección 1 por EV positivo: elegir por
   EV sobre la probabilidad del modelo es el canal que este proyecto tiene
   medido como ANTI-INDICADOR (−4,66 % a −6,52 % sobre 37.158 apuestas, ver el
   §0 de `ARQUITECTURA.txt`). El reparto de secciones lo sigue decidiendo
   `clasificador`, por ventaja de precio, que es lo que tiene percentil 5
   positivo. Esta capa informa; no asciende.

   Donde el veredicto de EV sí manda es en la combinada: `apto_para_combinada`
   deja fuera lo que el encargo dice que hay que dejar fuera.

LO QUE ESTA CAPA NO PROMETE
---------------------------
Que gane dinero. Ninguna de las reglas nuevas de aquí está medida contra ROI
todavía —divergencia, cuota inflada y racha salen con `medido: False`— y se
publican como AVISO, no como corrección de probabilidad. La única que toca un
número es la aclimatación, que sí está medida fuera de muestra. Ver la
separación «medido / no medido» de `contexto_ampliado`, que es la misma de aquí.
"""

import logging
import re
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger('auditoria_pick')

# ---------------------------------------------------------------------------
# Los números del encargo, tal y como los fija
# ---------------------------------------------------------------------------
EV_VALOR = 0.03             # por encima: «recomendación de valor»
EV_DESCARTE = -0.02         # por debajo: «descartar»

UMBRAL_DIVERGENCIA = 0.15   # |p_modelo − p_mercado| que enciende la bandera
RECORTE_DIVERGENCIA = 0.20  # y el 20 % de confianza que se lleva

UMBRAL_CUOTA_INFLADA = 1.30  # cuota_casa / cuota_justa por encima de esto
RECORTE_CUOTA_INFLADA = 0.30

RACHA_SIN_GANAR = 5         # partidos sin ganar que encienden la bandera
PENALIZACION_RACHA = 0.10

MAX_PATAS_POR_PARTIDO = 2   # tope de patas del mismo partido en un boleto
CUOTA_MINIMA_RIESGO = 1.80  # cuota mínima exigida en competición de alto riesgo
EXPOSICION_MAXIMA = 0.05    # tope de banca en un solo boleto

# Mercados que el encargo bloquea en competición de alto riesgo.
MERCADOS_BLOQUEADOS_RIESGO = ('under', 'menos de', 'btts no', 'ambos marcan: no')

# El factor por nivel. Los valores son los del encargo; QUIÉN cae en cada uno
# lo decide `riesgo_liga`, que lo midió. Ver el encabezado.
FACTOR_RIESGO = {'baja': 1.0, 'media': 1.3, 'alta': 1.8, 'sin_medir': 1.3}

# La tabla literal del encargo. NO SE USA: se conserva porque la refutación es
# el dato valioso, y sin la tabla al lado no se entiende contra qué se refutó.
TABLA_DEL_ENCARGO = {
    'estado': 'REFUTADA el 2026-09-15 por riesgo_liga.CORRELACION_MEDIDA',
    'por_que': 'el ECE medido ordena al reves: Premier en el peor cuartil, '
               'Brasileirao B y Primera Nacional en la mejor mitad',
    'tabla': {'top': 1.0, 'medias': 1.3, 'volatiles': 1.8},
}

_CONFIANZA = (('ALTA', 0.75), ('MEDIA', 0.50), ('BAJA', 0.0))

# Los únicos canales que suben la confianza: los que `clasificador` deja subir
# a la Sección 1 porque tienen percentil 5 de bootstrap positivo. `ev_del_modelo`
# NO está aquí a propósito — es el anti-indicador medido.
# v297.4 — `precio_visitante` entra aqui el mismo dia que sube a la Seccion 1,
# y no despues: si sube alli y no esta en esta tupla, sus picks salen en la
# seccion de los medidos con la confianza de los que no lo estan.
CANALES_MEDIDOS = ('precio_local', 'precio_visitante', 'precio_nfl',
                   'tenis_90')


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _f(x) -> Optional[float]:
    """Float o None. Nunca lanza."""
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def equipos_del_pick(pick: Dict) -> tuple:
    """`('Gil Vicente', 'Maritimo')` a partir de `partido`. Vacío si no casa."""
    texto = str((pick or {}).get('partido') or '')
    partes = re.split(r'\s+vs\.?\s+', texto, maxsplit=1, flags=re.IGNORECASE)
    if len(partes) != 2:
        return ('', '')
    return (partes[0].strip(), partes[1].strip())


def lado_del_pick(pick: Dict) -> Optional[str]:
    """A qué equipo apunta la apuesta, si es que apunta a uno.

    Devuelve el nombre del equipo mencionado en la etiqueta, o None si la
    apuesta no es de resultado (un «Más de 2.5» no tiene lado).
    """
    home, away = equipos_del_pick(pick)
    etiqueta = str((pick or {}).get('apuesta') or '').lower()
    if not etiqueta:
        return None
    for equipo in (home, away):
        if equipo and equipo.lower() in etiqueta:
            return equipo
    return None


# ---------------------------------------------------------------------------
# MÓDULO 1 — correlación con el mercado
# ---------------------------------------------------------------------------
def probabilidad_mercado(pick: Dict) -> Optional[float]:
    """Probabilidad implícita SIN margen del mercado para esta apuesta.

    Prioriza `cuota_justa`, que es lo que `alpha_finder` ya dejó escrito tras
    el devig del consenso. Si no está, cae a 1/cuota, que SÍ lleva margen: en
    ese caso la cifra se marca aparte (`mercado_con_margen`) porque comparar
    contra ella infla la divergencia en el tamaño del vig.
    """
    justa = _f((pick or {}).get('cuota_justa'))
    if justa and justa > 1.0:
        return round(1.0 / justa, 4)
    cuota = _f((pick or {}).get('cuota'))
    if cuota and cuota > 1.0:
        return round(1.0 / cuota, 4)
    return None


def valor_esperado(prob: Optional[float], cuota: Optional[float]) -> Optional[float]:
    """EV = p × cuota − 1. None si falta cualquiera de los dos."""
    p, c = _f(prob), _f(cuota)
    if p is None or c is None or c <= 1.0 or not (0.0 < p <= 1.0):
        return None
    return round(p * c - 1.0, 4)


def veredicto_ev(ev: Optional[float]) -> str:
    """`valor` · `neutro` · `descartar` · `sin_dato`, con los cortes del encargo."""
    if ev is None:
        return 'sin_dato'
    if ev > EV_VALOR:
        return 'valor'
    if ev < EV_DESCARTE:
        return 'descartar'
    return 'neutro'


def divergencia(p_modelo: Optional[float],
                p_mercado: Optional[float]) -> Dict:
    """Bandera de «divergencia extrema» y el recorte de confianza que trae."""
    pm, pk = _f(p_modelo), _f(p_mercado)
    if pm is None or pk is None:
        return {'activa': False, 'delta': None, 'recorte': 0.0}
    delta = round(pm - pk, 4)
    activa = abs(delta) > UMBRAL_DIVERGENCIA
    return {'activa': activa, 'delta': delta,
            'recorte': RECORTE_DIVERGENCIA if activa else 0.0,
            'medido': False}


# ---------------------------------------------------------------------------
# MÓDULO 3 — riesgo de la competición (por ECE medido, no por nombre)
# ---------------------------------------------------------------------------
def riesgo_de_liga(clave_liga: Optional[str]) -> Dict:
    """Nivel, factor y explicación de la competición. Nunca lanza."""
    nivel = 'sin_medir'
    ficha: Dict = {}
    try:
        import riesgo_liga as rl
        nivel = rl.nivel_liga(clave_liga)
        ficha = rl.ficha(clave_liga) or {}
    except Exception as e:
        logger.debug('[auditoria] riesgo_liga: %s', e)
    return {'nivel': nivel,
            'factor': FACTOR_RIESGO.get(nivel, 1.3),
            'motivo': ficha.get('motivo') or '',
            'media_goles': ficha.get('media_goles'),
            'ece': ficha.get('ece_medio'),
            'pocos_goles': bool(ficha.get('liga_de_pocos_goles'))}


def bloqueo_por_riesgo(pick: Dict, riesgo: Dict) -> Optional[str]:
    """La regla del encargo para competición de alto riesgo.

    Con factor > 1,5 se exige cuota >= 1,80, y los mercados de «Under» y
    «BTTS No» se bloquean directamente. Devuelve el motivo o None.
    """
    if (riesgo or {}).get('factor', 1.0) <= 1.5:
        return None
    etiqueta = f"{(pick or {}).get('mercado') or ''} {(pick or {}).get('apuesta') or ''}".lower()
    for prohibido in MERCADOS_BLOQUEADOS_RIESGO:
        if prohibido in etiqueta:
            return (f'competición de alto riesgo y mercado de {prohibido}: '
                    f'el encargo lo bloquea sin excepción')
    cuota = _f((pick or {}).get('cuota'))
    if cuota is not None and cuota < CUOTA_MINIMA_RIESGO:
        return (f'competición de alto riesgo con cuota {cuota:.2f}, por debajo '
                f'del mínimo de {CUOTA_MINIMA_RIESGO:.2f} que compensa la varianza')
    return None


# ---------------------------------------------------------------------------
# MÓDULO 5 — filtros anti-trampa
# ---------------------------------------------------------------------------
def cuota_inflada(cuota: Optional[float], prob: Optional[float]) -> Dict:
    """¿La casa paga más de 1,30 veces la cuota justa del modelo?

    Con la probabilidad del modelo, no con la del mercado: es el caso «esto
    paga demasiado bien para ser verdad», que casi siempre es el modelo
    equivocándose y no la casa regalando.
    """
    c, p = _f(cuota), _f(prob)
    if c is None or p is None or not (0.0 < p < 1.0):
        return {'activa': False, 'ratio': None, 'recorte': 0.0}
    justa = 1.0 / p
    ratio = round(c / justa, 3)
    activa = ratio > UMBRAL_CUOTA_INFLADA
    return {'activa': activa, 'ratio': ratio,
            'recorte': RECORTE_CUOTA_INFLADA if activa else 0.0,
            'medido': False}


def racha_negativa(clave_liga: Optional[str], equipo: Optional[str]) -> Dict:
    """¿Lleva `equipo` cinco o más partidos sin ganar?

    Lee la MISMA racha que la tarjeta ya pinta (`contexto_partido.forma`), para
    que la pantalla y la auditoría no puedan decir cosas distintas.
    """
    vacio = {'activa': False, 'sin_ganar': None, 'racha': '', 'penalizacion': 0.0}
    if not clave_liga or not equipo:
        return vacio
    try:
        import contexto_partido as cp
        f = cp.forma(str(clave_liga), str(equipo)) or {}
    except Exception as e:
        logger.debug('[auditoria] forma de %s: %s', equipo, e)
        return vacio
    racha = str(f.get('racha') or '')
    if not racha:
        return vacio
    # La racha viene del más antiguo al más reciente; se cuentan los últimos.
    sin_ganar = 0
    for marca in reversed(racha):
        if marca == 'G':
            break
        sin_ganar += 1
    activa = sin_ganar >= RACHA_SIN_GANAR
    return {'activa': activa, 'sin_ganar': sin_ganar, 'racha': racha,
            'penalizacion': PENALIZACION_RACHA if activa else 0.0,
            'medido': False}


def incertidumbre(clave_liga: Optional[str]) -> Dict:
    """La etiqueta de fiabilidad por Brier que el proyecto ya publica.

    `🔴 Alta incertidumbre` es Brier >= 0,22 sobre los picks REALES publicados
    en esa competición. Es la misma etiqueta que el encargo nombra, y se lee de
    donde ya estaba en vez de inventar una nueva.
    """
    brier, etiqueta = None, '⚪ Sin histórico'
    try:
        import alpha_finder as af
        brier = af.brier_liga(str(clave_liga)) if clave_liga else None
        etiqueta = af.etiqueta_fiabilidad(brier)
    except Exception as e:
        logger.debug('[auditoria] brier: %s', e)
    return {'brier': brier, 'etiqueta': etiqueta,
            'alta_incertidumbre': etiqueta.endswith('Alta incertidumbre')}


# ---------------------------------------------------------------------------
# MÓDULO 2 — contexto en tiempo real
# ---------------------------------------------------------------------------
_BUSCADOR_CONECTADO: Optional[bool] = None


def asegurar_fuente_entrenadores() -> bool:
    """Enchufa la fuente de cambios de entrenador UNA vez por proceso.

    `filtro_contexto` tenía la regla escrita, probada y con `conectar_buscador()`
    listo desde la v202, y no la llamaba nadie: la regla estaba viva y ciega.
    Esto es la llamada que faltaba. Devuelve si hay fuente de verdad.
    """
    global _BUSCADOR_CONECTADO
    if _BUSCADOR_CONECTADO is not None:
        return _BUSCADOR_CONECTADO
    _BUSCADOR_CONECTADO = False
    try:
        import filtro_contexto as fc
        _BUSCADOR_CONECTADO = bool(fc.hay_fuente() or fc.conectar_buscador())
    except Exception as e:
        logger.debug('[auditoria] fuente de entrenadores: %s', e)
    return _BUSCADOR_CONECTADO


def _casar_con_la_fuente(equipo: str, claves: Sequence[str]) -> str:
    """Traduce el nombre del barrido al que usa la fuente de entrenadores.

    HACE FALTA, Y ES LA DIFERENCIA ENTRE QUE LA REGLA VIVA O NO. Wikidata
    publica «Bologna Football Club 1909» y el barrido dice «Bologna»;
    `filtro_contexto.cambio_reciente` busca por igualdad exacta, así que sin
    esto la regla se conectaba, cargaba ocho cambios reales y no disparaba
    nunca — un no-op silencioso, que es el modo de fallo contra el que avisa
    todo este repositorio.

    Se usa `name_mapper`, que es el emparejador del proyecto. Si no casa,
    devuelve el nombre original y la regla simplemente no encuentra cambio.
    """
    if not equipo or not claves:
        return equipo
    try:
        import name_mapper as nm
        return nm.mapear(equipo, list(claves)) or equipo
    except Exception as e:
        logger.debug('[auditoria] emparejado de %s: %s', equipo, e)
        return equipo


def entrenador_nuevo(pick: Dict, dia: Optional[str] = None) -> Dict:
    """Efecto rebote por entrenador nuevo, con la regla que ya estaba escrita."""
    vacio = {'activa': False, 'equipo': None, 'dias': None, 'fuente': None}
    home, away = equipos_del_pick(pick)
    if not home or not away:
        return vacio
    if not asegurar_fuente_entrenadores():
        return vacio

    # EL LADO SE DECIDE CON LOS NOMBRES DEL BARRIDO, ANTES DE TRADUCIR NADA.
    # `rebote_entrenador` necesita saber QUIÉN es el favorito, porque el rebote
    # lo sufre él: el entrenador nuevo es el del rival. El pick sólo apunta a un
    # lado, así que el favorito es ese lado cuando la cuota lo respalda. Si se
    # traduce primero, `lado_del_pick` —que lee la etiqueta del pick— deja de
    # casar con `home`/`away` y la regla no dispara nunca.
    lado = lado_del_pick(pick)
    if lado == home:
        lado_favorito = 'local'
    elif lado == away:
        lado_favorito = 'visitante'
    else:
        return vacio

    try:
        import datetime as _dt
        import filtro_contexto as fc
        jornada = dia or str((pick or {}).get('fecha') or _dt.date.today())
        claves = list(fc.fuente_cambios(jornada) or {})
        # Y AHORA SÍ se traduce, que es lo que la fuente entiende.
        if claves:
            home = _casar_con_la_fuente(home, claves)
            away = _casar_con_la_fuente(away, claves)
        info = fc.rebote_entrenador(home, away, jornada,
                                    _f((pick or {}).get('cuota')),
                                    lado_favorito) or {}
    except Exception as e:
        logger.debug('[auditoria] rebote de entrenador: %s', e)
        return vacio
    if not info.get('activo'):
        return vacio
    return {'activa': True, 'equipo': info.get('equipo'),
            'dias': info.get('dias'), 'fuente': info.get('fuente'),
            'aviso': info.get('aviso') or '',
            'mercados_bloqueados': info.get('mercados_bloqueados') or [],
            'medido': bool(info.get('medido'))}


def contexto_medido(pick: Dict) -> Dict:
    """Lo único del contexto que corrige un número: la aclimatación."""
    try:
        import contexto_ampliado as ca
        home, away = equipos_del_pick(pick)
        if not home or not away:
            return {}
        return ca.de_partido(str((pick or {}).get('clave_liga') or ''),
                             home, away) or {}
    except Exception as e:
        logger.debug('[auditoria] contexto ampliado: %s', e)
        return {}


# ---------------------------------------------------------------------------
# MÓDULO 8 — banca
# ---------------------------------------------------------------------------
def stake_sugerido(prob: Optional[float], cuota: Optional[float],
                   bankroll: float = 100.0,
                   confianza: str = 'MEDIA',
                   alta_incertidumbre: bool = False) -> Dict:
    """Kelly fraccional con el ajuste por riesgo que pide el encargo."""
    p, c = _f(prob), _f(cuota)
    base = {'pct': 0.0, 'stake': 0.0, 'kelly_pleno': 0.0, 'texto': 'no apostar'}
    if p is None or c is None:
        return base
    try:
        import bankroll_manager as bm
        r = bm.calcular_stake(p, c, bankroll) or {}
    except Exception as e:
        logger.debug('[auditoria] kelly: %s', e)
        return base
    pct = float(r.get('pct') or 0.0)
    if alta_incertidumbre or confianza == 'BAJA':
        pct *= 0.5          # el ajuste por riesgo del encargo
    pct = min(pct, EXPOSICION_MAXIMA)
    return {'pct': round(pct, 4),
            'stake': round(bankroll * pct, 2),
            'kelly_pleno': r.get('kelly_pleno'),
            'texto': (f'{pct*100:.1f} % del bankroll' if pct > 0
                      else 'no apostar: sin valor a este precio')}


def probabilidad_de_ruina(prob: Optional[float], cuota: Optional[float],
                          apuestas_por_dia: int = 3,
                          dias: int = 10) -> Optional[float]:
    """Probabilidad de ruina a `dias`, con el simulador que ya existe."""
    p, c = _f(prob), _f(cuota)
    if p is None or c is None:
        return None
    try:
        import montecarlo_sim as ms
        sim = ms.simular_bankroll(bankroll=100.0, win_rate=p, odds_mean=c,
                                  odds_std=max(c * 0.15, 0.05),
                                  n_bets=max(1, apuestas_por_dia * dias)) or {}
    except Exception as e:
        logger.debug('[auditoria] montecarlo: %s', e)
        return None
    valor = sim.get('prob_ruina')
    if valor is None:
        valor = sim.get('prob_ruina_10d')
    return round(float(valor), 4) if valor is not None else None


# ---------------------------------------------------------------------------
# MÓDULO 4 — correlación entre mercados
# ---------------------------------------------------------------------------
def patas_compatibles(picks: Sequence[Dict],
                      max_por_partido: int = MAX_PATAS_POR_PARTIDO) -> List[Dict]:
    """Filtra una lista de picks para que pueda ser un boleto.

    Dos reglas, y las dos son del encargo:
      · no más de `max_por_partido` patas del mismo partido, y
      · nada lógicamente incompatible dentro de un partido, que lo decide
        `match_parlay` (sus grupos excluyentes y sus contradicciones), no una
        matriz nueva escrita aquí.

    El orden de entrada manda: se conserva el primero de cada conflicto.
    """
    salida: List[Dict] = []
    por_partido: Dict[str, List[Dict]] = {}
    for p in list(picks or []):
        if not isinstance(p, dict):
            continue
        clave = f"{p.get('deporte', '')}|{p.get('partido', '')}"
        hermanas = por_partido.setdefault(clave, [])
        if len(hermanas) >= max(1, int(max_por_partido)):
            continue
        if any(_incompatibles(p, otra) for otra in hermanas):
            continue
        hermanas.append(p)
        salida.append(p)
    return salida


def senal(pick: Dict) -> tuple:
    """Clasifica un pick del BARRIDO en `(grupo, opción)`.

    POR QUÉ NO SE REUSA `match_parlay._clasificar`. Esa función trabaja sobre
    los `id` de campo de la ficha del partido (`over25_prob`, `dc_1x`…), que es
    otro vocabulario: los picks del barrido sólo traen `mercado` y una etiqueta
    legible («Más de 1.5», «Gana Gil Vicente»). Son las mismas reglas aplicadas
    una capa más arriba, no una copia de la matriz.

    Grupos: `resultado` · `goles` · `btts`. Opción dentro del grupo.
    """
    p = pick or {}
    mercado = str(p.get('mercado') or '').lower()
    etiqueta = str(p.get('apuesta') or '').lower()
    home, away = equipos_del_pick(p)

    if 'btts' in mercado or 'ambos marcan' in mercado or 'ambos marcan' in etiqueta:
        return ('btts', 'no' if re.search(r'\bno\b', etiqueta) else 'si')

    if re.search(r'\b(más|mas|over)\b', etiqueta):
        return ('goles', 'over')
    if re.search(r'\b(menos|under)\b', etiqueta):
        return ('goles', 'under')

    if 'empate' in etiqueta and ' o ' not in etiqueta:
        return ('resultado', 'empate')
    if home and home.lower() in etiqueta:
        return ('resultado', 'local')
    if away and away.lower() in etiqueta:
        return ('resultado', 'visitante')
    return ('', '')


# Pares del MISMO partido que se anulan entre sí. El encargo los enumera y
# éstos son ésos, más los excluyentes obvios del mismo grupo.
CORRELACION_NEGATIVA = (
    (('resultado', 'local'), ('goles', 'under')),
    (('resultado', 'visitante'), ('goles', 'under')),
    (('btts', 'no'), ('goles', 'over')),
    (('btts', 'si'), ('goles', 'under')),
)


def _incompatibles(a: Dict, b: Dict) -> bool:
    """¿Estas dos patas del mismo partido se contradicen?

    Dos casos: la misma pregunta respondida de dos formas (gana A y gana B,
    over y under) y los pares de correlación negativa que el encargo lista.
    Si alguna de las dos no se puede clasificar, deja pasar: bloquear por no
    saber vaciaría el boleto, y el tope de dos patas ya limita el daño.
    """
    sa, sb = senal(a), senal(b)
    if not sa[0] or not sb[0]:
        return False
    if sa[0] == sb[0]:
        return sa[1] != sb[1]          # mismo grupo, distinta opción
    return (sa, sb) in CORRELACION_NEGATIVA or (sb, sa) in CORRELACION_NEGATIVA


def apto_para_combinada(auditoria: Dict) -> Dict:
    """Las reglas de oro del encargo, aplicadas al boleto.

    Fuera de una combinada: lo marcado `🔴 Alta incertidumbre`, lo que el
    riesgo de competición bloquea, y lo que tiene veredicto de EV `descartar`.
    """
    a = auditoria or {}
    if a.get('alta_incertidumbre'):
        return {'apto': False,
                'motivo': 'marcado 🔴 Alta incertidumbre: el encargo lo deja '
                          'fuera de toda combinada'}
    if a.get('bloqueo'):
        return {'apto': False, 'motivo': a['bloqueo']}
    if a.get('veredicto_ev') == 'descartar':
        # OJO: `EV` en la ficha ya viene en PUNTOS DE PORCENTAJE (−5,5), no en
        # fracción. Formatearlo con `%` lo multiplicaba otra vez por cien y la
        # pantalla decía «EV −550 %», que es la clase de número que hace dudar
        # de todo lo demás. Se vio con picks reales del barrido.
        ev = _f(a.get('EV'))
        cifra = f'{ev:+.1f} %' if ev is not None else 'negativo'
        return {'apto': False,
                'motivo': f"EV {cifra}, por debajo del "
                          f"{EV_DESCARTE*100:+.0f} % que el encargo descarta"}
    return {'apto': True, 'motivo': ''}


# ---------------------------------------------------------------------------
# MÓDULO 7 — el ensamblador
# ---------------------------------------------------------------------------
def _etiqueta_confianza(escalar: float) -> str:
    for nombre, corte in _CONFIANZA:
        if escalar >= corte:
            return nombre
    return 'BAJA'


def auditar(pick: Dict, bankroll: float = 100.0,
            dia: Optional[str] = None,
            con_contexto: bool = True) -> Dict:
    """La ficha completa de un pick, en el formato que pide el encargo.

    `con_contexto=False` salta las capas que tocan red o disco (entrenador,
    racha, aclimatación). Es lo que usa la pantalla cuando pinta cuarenta
    tarjetas y no puede pagar cuarenta lecturas de histórico.
    """
    p = dict(pick or {})
    clave_liga = p.get('clave_liga')
    prob = _f(p.get('prob'))
    cuota = _f(p.get('cuota'))

    p_mercado = probabilidad_mercado(p)
    ev = _f(p.get('ev'))
    if ev is None:
        ev = valor_esperado(prob, cuota)

    riesgo = riesgo_de_liga(clave_liga)
    inc = incertidumbre(clave_liga)
    div = divergencia(prob, p_mercado)
    infl = cuota_inflada(cuota, prob)

    racha: Dict = {'activa': False}
    coach: Dict = {'activa': False}
    if con_contexto:
        racha = racha_negativa(clave_liga, lado_del_pick(p))
        coach = entrenador_nuevo(p, dia)

    # --- la confianza, que empieza en el semáforo y sólo puede bajar --------
    escalar = {'verde': 0.85, 'amarillo': 0.55, 'rojo': 0.25}.get(
        str(p.get('luz') or '').lower(), 0.60)
    # SÓLO SUBEN LOS CANALES MEDIDOS. La primera versión subía con cualquier
    # `canal` presente, y el barrido etiqueta `ev_del_modelo` —el canal que
    # este proyecto tiene medido como anti-indicador— que salía con confianza
    # ALTA. Se vio con picks reales: un EV de −5,5 % leyéndose como ALTA.
    if p.get('seccion') == 1 and p.get('canal') in CANALES_MEDIDOS:
        escalar = max(escalar, 0.80)
    escalar *= (1.0 - div['recorte'])
    escalar *= (1.0 - infl['recorte'])
    if inc['alta_incertidumbre']:
        escalar *= 0.5
    if riesgo['factor'] > 1.5:
        escalar *= 0.8
    # Un pick que la propia capa manda descartar no puede leerse ALTA. Es lo
    # que hace el ejemplo del encargo: EV −13,5 % y «Confianza: BAJA».
    if veredicto_ev(ev) == 'descartar':
        escalar *= 0.6
    escalar = max(0.0, min(1.0, escalar))
    confianza = _etiqueta_confianza(escalar)

    # --- razones y banderas, que es lo que el usuario lee -------------------
    razones: List[str] = []
    banderas: List[str] = []

    if p.get('motivo'):
        razones.append(str(p['motivo']))
    if p_mercado is not None and prob is not None:
        razones.append(f'el modelo da {prob*100:.0f} % y el mercado '
                       f'{p_mercado*100:.0f} %')
    if racha.get('activa'):
        razones.append(f"{lado_del_pick(p)} lleva {racha['sin_ganar']} "
                       f"partidos sin ganar (`{racha['racha']}`)")
        banderas.append('Racha negativa')
    if coach.get('activa'):
        razones.append(f"{coach.get('equipo')} cambió de entrenador hace "
                       f"{coach.get('dias')} días")
        banderas.append('Entrenador nuevo')
    if div['activa']:
        razones.append(f"el modelo se separa {abs(div['delta'])*100:.0f} "
                       f"puntos del mercado, que es más de lo que suele "
                       f"aguantar una diferencia real")
        banderas.append('Divergencia extrema')
    if infl['activa']:
        razones.append(f"la casa paga {infl['ratio']:.2f} veces la cuota justa "
                       f"del modelo: casi siempre es el modelo equivocándose")
        banderas.append('Cuota inflada')
    if inc['alta_incertidumbre']:
        banderas.append('Alta incertidumbre')
    if riesgo['nivel'] == 'alta':
        banderas.append('Competición de alto riesgo')
        if riesgo.get('motivo'):
            razones.append(str(riesgo['motivo']))
    elif riesgo['nivel'] == 'sin_medir':
        banderas.append('Competición sin medir')

    bloqueo = bloqueo_por_riesgo(p, riesgo)

    stake = stake_sugerido(prob, cuota, bankroll, confianza,
                           inc['alta_incertidumbre'])
    ruina = probabilidad_de_ruina(prob, cuota)

    ficha = {
        'partido': p.get('partido'),
        'liga': p.get('liga'),
        'clave_liga': clave_liga,
        'factor_riesgo_liga': riesgo['factor'],
        'nivel_riesgo_liga': riesgo['nivel'],
        'apuesta': p.get('apuesta'),
        'mercado': p.get('mercado'),
        'cuota': cuota,
        'probabilidad_modelo': round(prob * 100, 1) if prob is not None else None,
        'probabilidad_mercado': round(p_mercado * 100, 1) if p_mercado is not None else None,
        'EV': round(ev * 100, 1) if ev is not None else None,
        'veredicto_ev': veredicto_ev(ev),
        'confianza': confianza,
        'confianza_escalar': round(escalar, 3),
        'razones': razones,
        'banderas': banderas,
        'bloqueo': bloqueo,
        'alta_incertidumbre': inc['alta_incertidumbre'],
        'brier': inc['brier'],
        'fiabilidad': inc['etiqueta'],
        'stake_sugerido': stake['texto'],
        'stake_pct': stake['pct'],
        'prob_ruina_10d': ruina,
        'explicabilidad': '',
    }
    ficha['explicabilidad'] = explicar(ficha)
    ficha['apto_combinada'] = apto_para_combinada(ficha)
    return ficha


def explicar(ficha: Dict) -> str:
    """Una frase que resume la ficha. Es lo que se lee antes de decidir."""
    f = ficha or {}
    ev = f.get('EV')
    veredicto = f.get('veredicto_ev')
    if f.get('bloqueo'):
        return f"Bloqueada: {f['bloqueo']}."
    if veredicto == 'descartar':
        return (f"El mercado paga menos de lo que la apuesta vale "
                f"({ev:+.1f} % de EV): a este precio no se juega.")
    if veredicto == 'valor':
        return (f"La casa paga por encima de lo que el modelo pide "
                f"({ev:+.1f} % de EV), con confianza {f.get('confianza','?')}.")
    if veredicto == 'neutro':
        return (f"Precio justo dentro del margen ({ev:+.1f} % de EV): ni valor "
                f"ni robo, y la decisión la manda el resto de la ficha.")
    return 'Sin precio con el que comparar: sólo pronóstico.'


def texto(ficha: Dict) -> str:
    """La ficha en el formato de bloque que el encargo enseña como ejemplo."""
    f = ficha or {}
    lineas = [
        f"Apuesta: {f.get('apuesta') or '?'}",
        f"Partido: {f.get('partido') or '?'} ({f.get('liga') or '?'})",
        f"Probabilidad modelo: {f.get('probabilidad_modelo')} %",
        f"Probabilidad mercado: {f.get('probabilidad_mercado')} %",
        f"EV: {f.get('EV')} % ({str(f.get('veredicto_ev') or '').upper()})",
    ]
    if f.get('razones'):
        lineas.append('Razones:')
        lineas.extend(f'- {r}' for r in f['razones'])
    if f.get('banderas'):
        lineas.append('Banderas: ' + ' · '.join(f['banderas']))
    lineas.append(f"Stake: {f.get('stake_sugerido')}")
    lineas.append(f"Confianza: {f.get('confianza')}")
    return '\n'.join(lineas)


# ---------------------------------------------------------------------------
def auditar_lista(picks: Sequence[Dict], bankroll: float = 100.0,
                  con_contexto: bool = False) -> List[Dict]:
    """Audita una lista entera. Sin contexto por defecto: lo pide la pantalla."""
    fuera = []
    for p in list(picks or []):
        if not isinstance(p, dict):
            continue
        try:
            fuera.append(auditar(p, bankroll=bankroll, con_contexto=con_contexto))
        except Exception as e:
            logger.warning('[auditoria] pick descartado por error: %s', e)
    return fuera


if __name__ == '__main__':
    ejemplo = {'partido': 'Gil Vicente vs Maritimo', 'liga': 'Primeira Liga',
               'clave_liga': 'portugal', 'mercado': 'Goles',
               'apuesta': 'Más de 1.5', 'prob': 0.68, 'cuota': 1.42,
               'cuota_justa': 1.42, 'luz': 'amarillo'}
    print(texto(auditar(ejemplo, con_contexto=False)))
