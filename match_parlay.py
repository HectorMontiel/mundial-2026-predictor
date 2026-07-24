#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Asistente de Parlay POR PARTIDO (v15) — agnóstico de competición.

Extrae todas las selecciones apostables de la plantilla del partido (Mundial:
`motor.plantilla`; clubes: `motor.plantilla_club`), filtra por el umbral del
perfil de riesgo, descarta combinaciones lógicamente incompatibles o
redundantes, aplica un haircut de correlación (0.95 por pareja correlacionada)
y devuelve el parlay del tamaño pedido (4-8) que maximiza el EV (con cuotas
reales) o la probabilidad conjunta (con cuotas justas).

El parlay multi-partido del fixture (parlay_builder.py) queda intacto.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import sgp_correlation

logger = logging.getLogger(__name__)

# v20 (SmartParlayBuilder): cada perfil tiene una ZONA OBJETIVO de
# probabilidad conjunta, no solo un umbral individual. Motivo: con cuotas
# justas (cuota = 1/prob) cualquier score prob*cuota^alpha es monótono en la
# probabilidad, así que el greedy de v16 hacía que conservador y medio
# eligieran EXACTAMENTE lo mismo. Las zonas disjuntas garantizan perfiles
# distintos por construcción:
#   conservador -> max prob conjunta, PISO conjunto 60 % (si no alcanza,
#                  reduce el número de picks en lugar de relajar)
#   medio       -> max prob_conj * cuota_comb^0.3 DENTRO de la zona 15-60 %
#                  (el techo del 60 % evita que colisione con el conservador)
#   agresivo    -> max cuota combinada con PISO conjunto del 5 % y umbral
#                  individual del 30 % (momio alto pero factible, nunca la
#                  quimera del 0.2 %)
PERFILES = {
    # v37 (§3): "Super Seguro" prioriza mercados de alta probabilidad
    # (doble oportunidad, hándicap +0.5, BTTS bien calibrado) para maximizar
    # el PFP — el criterio rey del cambio de paradigma "de no perder a ganar".
    'super_seguro': {'min_prob': 0.70, 'zona': (0.55, 1.01), 'objetivo': 'prob',
                     'reduce_picks': True, 'preferir_alta_prob': True},
    'conservador': {'min_prob': 0.65, 'zona': (0.60, 1.01), 'objetivo': 'prob',
                    'reduce_picks': True},
    'medio':       {'min_prob': 0.50, 'zona': (0.15, 0.60), 'objetivo': 'balance',
                    'alpha': 0.3},
    'agresivo':    {'min_prob': 0.30, 'zona': (0.05, 1.01), 'objetivo': 'cuota'},
}

# v37 (§2): PFP = Parlay Force Point = probabilidad conjunta REAL de acertar
# todas las patas (ya ajustada por correlación). Es el criterio rey: solo se
# sugieren parlays con PFP ≥ este umbral, salvo modo avanzado.
PFP_MINIMO = 0.45

# v37 (§3): mercados de ALTA probabilidad individual — con ellos se arma un
# PFP elevado aunque la cuota sea moderada. Son la "lista blanca" del perfil
# Super Seguro.
MERCADOS_ALTA_PROB = {
    'dc_1x', 'dc_x2', 'home_or_draw_prob', 'draw_or_away_prob',
    'home_plus05_prob', 'away_plus05_prob', 'ah_home_mas05', 'ah_away_mas05',
    'over05', 'over15', 'under35', 'btts_si', 'btts_no',
    'btts_yes_prob', 'btts_no_prob',
}
# v25: el haircut fijo 0.95 fue reemplazado por factores de correlación
# EMPÍRICOS por pareja de mercados (sgp_correlation.py, cópula gaussiana
# simplificada con φ de 3 temporadas; validado fuera de muestra: el error de
# la conjunta baja de 0.049 a 0.003). La constante queda solo como respaldo
# para parejas sin dato (dentro de sgp_correlation.factor_par).
HAIRCUT_CORRELACION = 0.95
CUOTA_MAXIMA_COMBINADA = 1000.0
MIN_SELECCIONES = 2
# Estados vivos por nivel en la búsqueda combinatoria. Las podas (piso con
# lookahead por grupos, contradicciones, topes de familia) dejan el árbol en
# ~10-20k estados, así que este ancho es en la práctica EXHAUSTIVO — un haz
# chico (160) devolvía cuotas muy por debajo del óptimo en el perfil agresivo.
ANCHO_HAZ = 20000

# v20: diversidad de categorías (macro-familias) obligatoria y tope por
# familia — nunca más de un mercado de córners ni de tarjetas por parlay
# (la causa de que "siempre salieran córners y remates").
MAX_POR_FAMILIA = {'corners': 1, 'tarjetas': 1}


def _min_familias(n: int) -> int:
    """Diversidad mínima: al menos min(3, N-1) categorías distintas."""
    return max(1, min(3, n - 1))

# ---------------------------------------------------------------------------
# Semántica de los campos de la plantilla
# ---------------------------------------------------------------------------
# grupo   -> solo UNA selección por grupo (opciones mutuamente excluyentes)
# familia -> selecciones de familias distintas de la MISMA macro-familia se
#            consideran correlacionadas (haircut); p. ej. 1X2 con hándicap.
# Los ids no listados aquí se clasifican por heurística de prefijo.
_RESULTADO = 'resultado'      # macro-familia: todo lo que depende del ganador
_GOLES = 'goles'              # macro-familia: volumen de goles
_CORNERS = 'corners'
_TARJETAS = 'tarjetas'

CAMPOS = {
    # --- comunes (Mundial y clubes) ---
    'home_win_prob': ('1x2', _RESULTADO), 'draw_prob': ('1x2', _RESULTADO),
    'away_win_prob': ('1x2', _RESULTADO),
    # doble oportunidad (Mundial usa *_or_*; clubes usa dc_*)
    'home_or_draw_prob': ('dc', _RESULTADO), 'home_or_away_prob': ('dc', _RESULTADO),
    'draw_or_away_prob': ('dc', _RESULTADO),
    'dc_1x': ('dc', _RESULTADO), 'dc_12': ('dc', _RESULTADO), 'dc_x2': ('dc', _RESULTADO),
    # total de goles — v16: UNA sola línea o/u de goles por parlay (las líneas
    # del mismo stat son redundantes entre sí: over 2.5 ⊂ over 1.5)
    'over25_prob': ('ou_goles', _GOLES), 'under25_prob': ('ou_goles', _GOLES),
    'over05': ('ou_goles', _GOLES), 'over15': ('ou_goles', _GOLES),
    'over25': ('ou_goles', _GOLES), 'over35': ('ou_goles', _GOLES),
    'over45': ('ou_goles', _GOLES), 'over55': ('ou_goles', _GOLES),
    'over15_goles': ('ou_goles', _GOLES), 'over35_goles': ('ou_goles', _GOLES),
    # btts / momentos de gol / paridad
    'btts_yes_prob': ('btts', _GOLES), 'btts_no_prob': ('btts', _GOLES),
    'btts_si': ('btts', _GOLES), 'btts_no': ('btts', _GOLES),
    'sin_goles': ('btts', _GOLES),
    'primer_gol_home': ('primer_gol', _GOLES), 'primer_gol_away': ('primer_gol', _GOLES),
    'ultimo_gol_home': ('ultimo_gol', _GOLES),
    'total_par': ('paridad', _GOLES), 'total_impar': ('paridad', _GOLES),
    # córners — v16: UNA sola línea o/u de córners por parlay
    'over65_corners': ('ou_ck', _CORNERS), 'over75_corners': ('ou_ck', _CORNERS),
    'over85_corners': ('ou_ck', _CORNERS), 'over95_corners': ('ou_ck', _CORNERS),
    'ck_o85': ('ou_ck', _CORNERS), 'ck_o95': ('ou_ck', _CORNERS),
    'ck_o105': ('ou_ck', _CORNERS),
    'corners_par_prob': ('ck_paridad', _CORNERS),
    'corners_1h_par_prob': ('ck_paridad_1h', _CORNERS),
    'first_corner_home_prob': ('primer_ck', _CORNERS),
    'last_corner_home_prob': ('ultimo_ck', _CORNERS),
    'last_corner_1h_home_prob': ('ultimo_ck_1h', _CORNERS),
    # tarjetas — v16: UNA sola línea o/u de tarjetas por parlay
    'over35_tarjetas': ('ou_cards', _TARJETAS), 'over55_tarjetas': ('ou_cards', _TARJETAS),
    'cards_over45_prob': ('ou_cards', _TARJETAS),
    'cards_o35': ('ou_cards', _TARJETAS), 'cards_o45': ('ou_cards', _TARJETAS),
    'penalty_prob': ('penalty', _TARJETAS),
}

_PREFIJOS = [
    # (prefijo, grupo, familia). v16: TODOS los prefijos colapsan a un grupo
    # único por mercado — nunca dos líneas del mismo stat en el parlay.
    ('ah_', 'ah', _RESULTADO), ('h1x2_', 'h1x2', _RESULTADO),
    ('home_plus', 'ah', _RESULTADO), ('home_minus', 'ah', _RESULTADO),
    ('away_plus', 'ah', _RESULTADO), ('away_minus', 'ah', _RESULTADO),
    ('score_', 'score', _RESULTADO), ('mv_', 'margen', _RESULTADO),
    ('htft_', 'htft', _RESULTADO),
    ('th_o', 'th', _GOLES), ('ta_o', 'ta', _GOLES),
    ('multi_', 'multi', _GOLES),
    ('player_', 'goleador', _GOLES), ('shooter_', 'rematador', _GOLES),
]

# Parejas EQUIVALENTES entre grupos (misma apuesta con otro nombre): nunca
# juntas; se queda la de mayor probabilidad. AH ±0.5 == 1X2/DC.
EQUIVALENCIAS = [
    ({'home_minus05_prob', 'ah_home_1'}, {'home_win_prob'}),
    ({'away_minus05_prob'}, {'away_win_prob'}),
    ({'home_plus05_prob', 'ah_home_mas05'}, {'home_or_draw_prob', 'dc_1x'}),
    ({'away_plus05_prob', 'ah_away_mas05'}, {'draw_or_away_prob', 'dc_x2'}),
]

# 1X2 vs doble oportunidad CONTRADICTORIAS (estrictamente incompatibles)
CONTRADICCIONES = [
    ({'home_win_prob'}, {'draw_or_away_prob', 'dc_x2'}),
    ({'draw_prob'}, {'home_or_away_prob', 'dc_12'}),
    ({'away_win_prob'}, {'home_or_draw_prob', 'dc_1x'}),
    ({'btts_si', 'btts_yes_prob'}, {'sin_goles', 'under25_prob'}),  # btts≥2 goles
    ({'btts_si', 'btts_yes_prob'}, {'over05', 'over15', 'over15_goles'}),  # redundante
]


@dataclass
class Seleccion:
    id: str
    mercado: str          # título de la sección
    apuesta: str          # etiqueta legible del campo
    prob: float           # 0-1
    cuota: float
    cuota_fuente: str     # 'justa' | 'real'
    grupo: str
    familia: str
    ev: float = 0.0


def _clasificar(id_: str):
    if id_ in CAMPOS:
        return CAMPOS[id_]
    for prefijo, grupo, familia in _PREFIJOS:
        if id_.startswith(prefijo):
            return grupo, familia
    return None, None


def _cuotas_reales_del_partido(pl: Dict) -> Dict[str, float]:
    """Cuotas reales de odds_actuales.json para ESTE partido, por campo.

    El MATCH_ID lleva fecha, que la plantilla no fija: se busca por sufijo
    de nombres de equipo. Cubre 1X2 y over/under 2.5 (lo que publican las
    fuentes gratuitas).
    """
    if not os.path.exists('odds_actuales.json'):
        return {}
    try:
        with open('odds_actuales.json', encoding='utf-8') as f:
            cuotas = json.load(f).get('cuotas', {})
    except Exception:
        return {}
    cod = pl.get('codigos', {})
    h = str(cod.get('home', '')).replace(' ', '-')
    a = str(cod.get('away', '')).replace(' ', '-')
    if not h or not a:
        return {}
    sufijo = f"_{h}_{a}"
    for mid, o in cuotas.items():
        if mid.endswith(sufijo):
            reales = {}
            if o.get('odd_home'):
                reales['home_win_prob'] = float(o['odd_home'])
                reales['draw_prob'] = float(o['odd_draw'])
                reales['away_win_prob'] = float(o['odd_away'])
            if o.get('odd_over25'):
                reales['over25_prob'] = reales['over25'] = float(o['odd_over25'])
            if o.get('odd_under25'):
                reales['under25_prob'] = float(o['odd_under25'])
            # v25: BTTS real (The Odds API vía almacén CLV)
            if o.get('odd_btts_yes'):
                reales['btts_si'] = reales['btts_yes_prob'] = float(o['odd_btts_yes'])
            if o.get('odd_btts_no'):
                reales['btts_no'] = reales['btts_no_prob'] = float(o['odd_btts_no'])
            # v19: hándicap asiático — solo cuando la línea es exactamente
            # ±0.5 (los campos de la plantilla son de esa línea)
            linea = o.get('ah_linea')
            if linea is not None and o.get('odd_ah_home') and o.get('odd_ah_away'):
                try:
                    linea = float(linea)
                except (TypeError, ValueError):
                    linea = None
                if linea == -0.5:      # local −0.5 / visitante +0.5
                    reales['home_minus05_prob'] = float(o['odd_ah_home'])
                    reales['away_plus05_prob'] = float(o['odd_ah_away'])
                    reales['ah_away_mas05'] = float(o['odd_ah_away'])
                elif linea == 0.5:     # local +0.5 / visitante −0.5
                    reales['home_plus05_prob'] = float(o['odd_ah_home'])
                    reales['ah_home_mas05'] = float(o['odd_ah_home'])
                    reales['away_minus05_prob'] = float(o['odd_ah_away'])
            return reales
    return {}


def obtener_selecciones(pl: Dict) -> List[Seleccion]:
    """Convierte la plantilla (Mundial o club) en selecciones apostables."""
    reales = _cuotas_reales_del_partido(pl)
    out: List[Seleccion] = []
    for seccion in pl.get('secciones', []):
        for c in seccion.get('campos', []):
            if c.get('tipo') != 'pct':
                continue
            grupo, familia = _clasificar(c['id'])
            if grupo is None:
                continue
            try:
                prob = float(c['valor']) / 100.0
            except (TypeError, ValueError):
                continue
            if not (0.0 < prob < 1.0):
                continue
            if c['id'] in reales:
                cuota, fuente = reales[c['id']], 'real'
            else:
                cuota, fuente = round(1.0 / prob, 2), 'justa'
            out.append(Seleccion(
                id=c['id'], mercado=seccion.get('titulo', ''),
                apuesta=c.get('etiqueta', c['id']), prob=prob,
                cuota=cuota, cuota_fuente=fuente,
                grupo=grupo, familia=familia,
                ev=round(cuota * prob - 1.0, 3),
            ))
    return out


def _ids_en(par_conjuntos, id_a: str, id_b: str) -> bool:
    for lado_a, lado_b in par_conjuntos:
        if (id_a in lado_a and id_b in lado_b) or (id_b in lado_a and id_a in lado_b):
            return True
    return False


def _compatibles(a: Seleccion, b: Seleccion) -> bool:
    if a.grupo == b.grupo:
        return False                       # opciones excluyentes del mismo grupo
    if _ids_en(CONTRADICCIONES, a.id, b.id):
        return False
    if _ids_en(EQUIVALENCIAS, a.id, b.id):
        return False                       # misma apuesta con otro nombre
    return True


def _correlacionadas(a: Seleccion, b: Seleccion) -> bool:
    """Correlación no excluyente -> haircut. Misma macro-familia."""
    return a.familia == b.familia


def _riesgo_partido(pl: Dict) -> str:
    try:
        with open('risk_flags.json', encoding='utf-8') as f:
            flags = json.load(f)
        cod = pl.get('codigos', {})
        h, a = cod.get('home', ''), cod.get('away', '')
        return flags.get(f"{h}|{a}") or flags.get(f"{a}|{h}") or 'bajo'
    except Exception:
        return 'bajo'


# ---------------------------------------------------------------------------
# v20 — SmartParlayBuilder: búsqueda combinatoria por haz (beam search)
# ---------------------------------------------------------------------------

def _score_combo(sels: tuple, prob_adj: float, cuota: float, cfg: Dict,
                 hay_reales: bool) -> float:
    """Puntuación de una combinación según el objetivo del perfil."""
    objetivo = cfg['objetivo']
    if objetivo == 'prob':
        return prob_adj
    if objetivo == 'cuota':
        if hay_reales:
            ev = sum(max(s.ev, 0.0) for s in sels)
            return cuota * (1.0 + 0.1 * ev)
        return cuota
    alpha = cfg.get('alpha', 0.3)
    score = prob_adj * cuota ** alpha
    if hay_reales:
        score *= 1.0 + max(sum(s.ev for s in sels), 0.0)
    return score


def _buscar_combinaciones(candidatas: List[Seleccion], n: int, cfg: Dict,
                          hay_reales: bool, exigir_diversidad: bool) -> List[tuple]:
    """
    Beam search sobre combinaciones de tamaño n. Cada estado es
    (sels, prob_ajustada_con_haircut, cuota, n_haircuts). Respeta grupos
    excluyentes, contradicciones, topes por familia y (opcional) que la
    diversidad mínima de categorías siga siendo alcanzable.
    """
    import math
    min_fam = _min_familias(n) if exigir_diversidad else 1
    piso = cfg['zona'][0]
    zona_hi = cfg['zona'][1]
    # Para el perfil MEDIO el haz se guía hacia el CENTRO de su zona (no hacia
    # la prob máxima): con cuotas justas el score es monótono en la prob y el
    # haz convergería a los mismos picks que el conservador.
    log_objetivo = None
    if cfg['objetivo'] == 'balance' and zona_hi <= 1.0:
        log_objetivo = math.log(math.sqrt(piso * zona_hi))   # media geométrica
    # Orden de enumeración (determinista; id desempata). La enumeración va
    # por índice creciente, así que un estado solo puede AÑADIR candidatos
    # posteriores: el perfil agresivo enumera de menor a mayor probabilidad
    # (arranca por los picks de cuota alta y se "rescata" con picks seguros
    # para cumplir el piso); el resto, de mayor a menor.
    if cfg['objetivo'] == 'cuota':
        cands = sorted(candidatas, key=lambda s: (s.prob, s.id))
    else:
        cands = sorted(candidatas, key=lambda s: (-s.prob, s.id))
    # Lookahead de factibilidad del piso: mejor producto alcanzable con los
    # k picks restantes. Optimista pero AJUSTADO a las reglas: máximo una
    # selección por grupo y tope por familia (córners/tarjetas). Sin esto,
    # el haz del perfil agresivo se llena de estados de cuota máxima que
    # mueren TODOS contra el piso en los últimos niveles.
    mejor_por_grupo: Dict[str, Seleccion] = {}
    for s in candidatas:
        if s.grupo not in mejor_por_grupo or s.prob > mejor_por_grupo[s.grupo].prob:
            mejor_por_grupo[s.grupo] = s
    disponibles = []
    usadas_familia: Dict[str, int] = {}
    for s in sorted(mejor_por_grupo.values(), key=lambda s: -s.prob):
        tope_fam = MAX_POR_FAMILIA.get(s.familia)
        if tope_fam is not None and usadas_familia.get(s.familia, 0) >= tope_fam:
            continue
        usadas_familia[s.familia] = usadas_familia.get(s.familia, 0) + 1
        disponibles.append(s.prob)
    mejor_resto = [1.0]
    for p in disponibles:
        mejor_resto.append(mejor_resto[-1] * p)

    # Estructuras precomputadas (la compatibilidad par a par domina el costo)
    m = len(cands)
    probs = [s.prob for s in cands]
    cuotas = [s.cuota for s in cands]
    fams = [s.familia for s in cands]
    compat = [[True] * m for _ in range(m)]
    # v25: factor multiplicativo de correlación por pareja (≤1, empírico)
    factor = [[1.0] * m for _ in range(m)]
    for i in range(m):
        for j in range(i + 1, m):
            c = _compatibles(cands[i], cands[j])
            compat[i][j] = compat[j][i] = c
            f = sgp_correlation.factor_par(
                cands[i].id, cands[i].prob, cands[j].id, cands[j].prob,
                misma_familia=_correlacionadas(cands[i], cands[j]))
            factor[i][j] = factor[j][i] = f

    objetivo = cfg['objetivo']
    alpha = cfg.get('alpha', 0.3)
    # estado: (índices, prob con haircut, cuota, n_haircuts, familias usadas)
    estados = [((), 1.0, 1.0, 0, frozenset())]
    for nivel in range(n):
        restantes = n - nivel - 1
        tope_resto = mejor_resto[min(restantes, len(mejor_resto) - 1)]
        siguientes = []
        for idxs, prob, cuota, n_hc, famset in estados:
            inicio = idxs[-1] + 1 if idxs else 0
            for j in range(inicio, m):
                fila_c = compat[j]
                if not all(fila_c[i] for i in idxs):
                    continue
                fj = fams[j]
                tope = MAX_POR_FAMILIA.get(fj)
                if tope is not None and sum(1 for i in idxs if fams[i] == fj) >= tope:
                    continue
                f_par = 1.0
                add_hc = 0
                for i in idxs:
                    fij = factor[j][i]
                    f_par *= fij
                    add_hc += fij < 0.999
                prob2 = prob * probs[j] * f_par
                if prob2 * tope_resto < piso:   # ya no puede cumplir el piso
                    continue
                famset2 = famset | {fj}
                if len(famset2) + restantes < min_fam:
                    continue              # ya no puede alcanzar la diversidad
                siguientes.append((idxs + (j,), prob2, cuota * cuotas[j],
                                   n_hc + add_hc, famset2))
        if not siguientes:
            return []
        if len(siguientes) > ANCHO_HAZ:
            if log_objetivo is not None:
                # trayectoria ideal: prob parcial que aterriza en el centro de la zona
                objetivo_nivel = log_objetivo * (nivel + 1) / n
                clave_haz = lambda e: (abs(math.log(max(e[1], 1e-12)) - objetivo_nivel), e[0])
            elif objetivo == 'cuota':
                clave_haz = lambda e: (-e[2], e[0])
            else:
                clave_haz = lambda e: (-e[1], e[0])
            siguientes.sort(key=clave_haz)
            siguientes = siguientes[:ANCHO_HAZ]
        estados = siguientes
    if exigir_diversidad:
        estados = [e for e in estados if len(e[4]) >= min_fam]
    return [(tuple(cands[i] for i in idxs), prob, cuota, n_hc)
            for idxs, prob, cuota, n_hc, _ in estados]


def _elegir_combo(candidatas: List[Seleccion], n: int, cfg: Dict,
                  hay_reales: bool):
    """
    Devuelve (estado, avisos). Tres niveles de degradación honesta:
      1. combinación en la ZONA del perfil con diversidad de categorías
      2. ídem sin diversidad (avisa)
      3. sin piso de probabilidad: la combinación más segura posible (avisa)
    """
    zona_lo, zona_hi = cfg['zona']
    for diversidad in (True, False):
        finales = _buscar_combinaciones(candidatas, n, cfg, hay_reales, diversidad)
        en_zona = [e for e in finales if zona_lo <= e[1] < zona_hi]
        if en_zona:
            mejor = max(en_zona, key=lambda e: _score_combo(e[0], e[1], e[2], cfg, hay_reales))
            avisos = [] if diversidad else \
                [f"⚠️ Este partido no permite {_min_familias(n)} categorías distintas "
                 f"con el perfil elegido: se relajó la diversidad."]
            return mejor, avisos
    # nivel 3: ignorar el piso — buscar la combinación MÁS PROBABLE posible
    cfg_libre = dict(cfg, zona=(0.0, 1.01), objetivo='prob')
    for diversidad in (True, False):
        finales = _buscar_combinaciones(candidatas, n, cfg_libre, hay_reales, diversidad)
        if finales:
            mejor = max(finales, key=lambda e: e[1])
            avisos = [(f"⚠️ Ninguna combinación de {n} picks alcanza el piso de "
                       f"probabilidad conjunta del perfil ({zona_lo*100:.0f} %): "
                       f"se muestra la más segura disponible "
                       f"({mejor[1]*100:.1f} %).")]
            if not diversidad:
                avisos.append("⚠️ Tampoco fue posible la diversidad mínima de categorías.")
            return mejor, avisos
    return None, []


_NOMBRE_FAMILIA = {'resultado': 'Resultado', 'goles': 'Goles',
                   'corners': 'Córners', 'tarjetas': 'Tarjetas/Disciplina'}


def _explicar_categorias(sels: List[Seleccion]) -> List[str]:
    """Explica qué categorías eligió el parlay y qué apuesta las ancla."""
    lineas = []
    for fam in ('resultado', 'goles', 'corners', 'tarjetas'):
        del_fam = [s for s in sels if s.familia == fam]
        if not del_fam:
            continue
        ancla = max(del_fam, key=lambda s: s.prob)
        lineas.append(f"{_NOMBRE_FAMILIA[fam]} ({len(del_fam)}): ancla "
                      f"«{ancla.apuesta}» con {ancla.prob*100:.0f} % según el modelo.")
    return lineas


def limite_patas_por_bankroll(bankroll: float, n_pedido: int,
                              cuota_combinada_tipica: float = 6.0) -> int:
    """v37 (§4): degradación dinámica del nº de patas según el bankroll.

    Si el stake mínimo razonable de un parlay de N patas superaría el 10 %
    del capital, se recorta el número de patas para proteger la banca. Con
    bankroll 0 o desconocido no se recorta (el usuario no lo configuró).
    """
    if not bankroll or bankroll <= 0:
        return n_pedido
    # unidad mínima práctica ≈ 1 % del bankroll; un parlay largo de cuota alta
    # es una apuesta de baja probabilidad → limitar exposición al 10 %.
    # Regla escalonada del spec: 4→3, 3→2, 2→simple según agresividad.
    if bankroll < 50:
        return min(n_pedido, 2)
    if bankroll < 150:
        return min(n_pedido, 3)
    return n_pedido


def construir_parlay_partido(motor, home: str, away: str,
                             num_selecciones: int = 6,
                             perfil: str = 'medio',
                             usar_cuotas_reales: bool = True,
                             excluir_alto_riesgo: bool = True,
                             solo_cuotas_reales: bool = False,
                             categorias: Optional[Set[str]] = None,
                             bankroll: float = 0.0,
                             aplicar_pfp: bool = True,
                             modo_avanzado: bool = False) -> Dict:
    """Parlay óptimo dentro de UN partido (v20: SmartParlayBuilder).

    v25 (§2.1):
      solo_cuotas_reales — lista blanca dinámica: solo mercados presentes en
        odds_actuales.json (1X2, O/U 2.5, BTTS, AH ±0.5); el EV es 100 %
        accionable pero hay menos mercados disponibles.
      categorias — macro-familias permitidas ({'resultado','goles','corners',
        'tarjetas'}); None = todas.
    v37:
      bankroll — si >0, recorta las patas para no exponer >10 % del capital (§4).
      aplicar_pfp — si True (defecto), rechaza parlays con PFP < 45 % salvo
        que modo_avanzado sea True (§2).
    """
    num_pedido = max(MIN_SELECCIONES, min(8, int(num_selecciones)))
    # §4: límite dinámico por bankroll ANTES de construir
    num_selecciones = limite_patas_por_bankroll(bankroll, num_pedido)
    aviso_bankroll = None
    if num_selecciones < num_pedido:
        aviso_bankroll = ("💡 Tu bankroll actual favorece apuestas de menor "
                          "riesgo para hacer crecer tu capital de forma "
                          f"consistente: el parlay se limitó a {num_selecciones} "
                          f"patas (pediste {num_pedido}).")
    cfg = PERFILES.get(perfil, PERFILES['medio'])
    umbral = cfg['min_prob']

    # plantilla según el tipo de motor (clubes primero: ClubEngine no tiene .plantilla)
    if hasattr(motor, 'plantilla_club'):
        pl = motor.plantilla_club(home, away)
    else:
        pl = motor.plantilla(home, away)
    if 'error' in pl:
        return {'error': pl['error']}

    riesgo = _riesgo_partido(pl)
    if riesgo == 'alto' and excluir_alto_riesgo:
        return {'error': '🔴 Este partido tiene riesgo de mercado ALTO '
                         '(divergencia/liquidez en mercados de predicción). '
                         'Desactiva la exclusión de riesgo si aun así quieres el parlay.'}

    todas = obtener_selecciones(pl)
    if not usar_cuotas_reales:
        for s in todas:
            if s.cuota_fuente == 'real':
                s.cuota, s.cuota_fuente = round(1.0 / s.prob, 2), 'justa'
                s.ev = 0.0

    candidatas = [s for s in todas if s.prob >= umbral]
    # v37 (§3): el perfil Super Seguro prioriza mercados de alta probabilidad
    # (doble oportunidad, hándicap +0.5, BTTS) — si hay al menos MIN de ellos,
    # se restringe a esos; si no, se usa todo para no quedarse sin parlay.
    if cfg.get('preferir_alta_prob'):
        alta = [s for s in candidatas if s.id in MERCADOS_ALTA_PROB]
        if len(alta) >= MIN_SELECCIONES:
            candidatas = alta
    # v25 (§2.1): lista blanca dinámica y control de categorías
    if solo_cuotas_reales:
        candidatas = [s for s in candidatas if s.cuota_fuente == 'real']
        if len(candidatas) < MIN_SELECCIONES:
            return {'error': 'Con la lista blanca de cuotas reales no hay '
                             'suficientes mercados vigentes para este partido '
                             '(llegan a diario en temporada). Desactívala para '
                             'usar también cuotas justas del modelo.'}
    if categorias:
        candidatas = [s for s in candidatas if s.familia in categorias]
        if len(candidatas) < MIN_SELECCIONES:
            return {'error': 'Las categorías elegidas dejan menos de 2 mercados '
                             'con la probabilidad mínima del perfil.'}
    if len(candidatas) < MIN_SELECCIONES:
        return {'error': 'Este partido no tiene suficientes mercados con la '
                         'probabilidad mínima del perfil elegido.'}
    hay_reales = any(s.cuota_fuente == 'real' for s in candidatas)

    # búsqueda: el conservador reduce el nº de picks antes que bajar su piso;
    # cualquier perfil reduce si simplemente no existen N picks compatibles.
    avisos: List[str] = []
    estado = None
    reduccion_por_piso = False
    n_obj = num_selecciones
    while n_obj >= MIN_SELECCIONES:
        estado, avisos_n = _elegir_combo(candidatas, n_obj, cfg, hay_reales)
        if estado is None:                       # no hay N picks compatibles
            n_obj -= 1
            continue
        piso_ok = estado[1] >= cfg['zona'][0]
        if piso_ok or not cfg.get('reduce_picks') or n_obj == MIN_SELECCIONES:
            avisos = avisos_n
            break
        reduccion_por_piso = True
        n_obj -= 1
    if estado is None:
        return {'error': 'No hay suficientes selecciones compatibles en este partido.'}
    if n_obj < num_selecciones:
        if reduccion_por_piso:
            avisos.insert(0, (f"⚠️ Con {num_selecciones} picks no se alcanzaba el piso del "
                              f"{cfg['zona'][0]*100:.0f} % de probabilidad conjunta: el parlay "
                              f"se redujo a {n_obj} picks (filosofía conservadora)."))
        else:
            avisos.insert(0, (f"⚠️ Solo hay {n_obj} selecciones compatibles con el "
                              f"perfil {perfil} (pediste {num_selecciones})."))

    elegidas, prob_conjunta, cuota_combinada, n_haircuts = estado
    elegidas = sorted(elegidas, key=lambda s: -s.prob)
    cuota_combinada = min(cuota_combinada, CUOTA_MAXIMA_COMBINADA)
    ev_parlay = round(cuota_combinada * prob_conjunta - 1.0, 3) if hay_reales else 0.0

    if aviso_bankroll:
        avisos.insert(0, aviso_bankroll)

    # v37 (§2): PFP = probabilidad conjunta real. El PFP SIEMPRE se muestra
    # (criterio rey). El filtro duro del 45 % solo bloquea los perfiles cuya
    # razón de ser es la seguridad (super_seguro, conservador); elegir MEDIO o
    # AGRESIVO ya es optar por el riesgo — son el "modo avanzado" del spec §2.2,
    # donde el PFP se avisa pero no oculta.
    es_avanzado = modo_avanzado or perfil in ('agresivo', 'medio')
    pfp = round(float(prob_conjunta), 4)
    cumple_pfp = pfp >= PFP_MINIMO
    if aplicar_pfp and not cumple_pfp and len(elegidas) > 1 and not es_avanzado:
        return {'error': (f"🛡️ El parlay más seguro posible para este partido "
                          f"tiene un PFP (probabilidad real de acertar todas "
                          f"las patas) del {pfp*100:.0f} %, por debajo del "
                          f"umbral del {PFP_MINIMO*100:.0f} %. Activa el modo "
                          f"avanzado si aun así quieres verlo, o reduce el "
                          f"número de patas / elige el perfil Super Seguro."),
                'pfp': pfp, 'pfp_bajo': True}
    if aplicar_pfp and not cumple_pfp and es_avanzado:
        avisos.insert(0, f"⚠️ MODO AVANZADO: PFP {pfp*100:.0f} % < "
                         f"{PFP_MINIMO*100:.0f} % — parlay de riesgo elevado.")

    return {
        'partido': pl.get('partido', f'{home} vs {away}'),
        'perfil': perfil, 'umbral_usado': umbral,
        'piso_conjunto': cfg['zona'][0],
        'pfp': pfp, 'cumple_pfp': cumple_pfp, 'pfp_minimo': PFP_MINIMO,
        'riesgo_partido': riesgo,
        'selecciones': [{
            'mercado': s.mercado, 'apuesta': s.apuesta,
            'prob': round(s.prob, 3), 'cuota': s.cuota,
            'cuota_fuente': s.cuota_fuente, 'ev': s.ev,
            'categoria': _NOMBRE_FAMILIA.get(s.familia, s.familia),
        } for s in elegidas],
        'n_selecciones': len(elegidas),
        'categorias': sorted({_NOMBRE_FAMILIA.get(s.familia, s.familia) for s in elegidas}),
        'explicacion': _explicar_categorias(list(elegidas)),
        'cuota_combinada': round(cuota_combinada, 2),
        'prob_conjunta': round(prob_conjunta, 4),
        'n_parejas_correlacionadas': n_haircuts,
        'ev_parlay': ev_parlay,
        'cuotas_reales': hay_reales,
        'avisos': avisos,
        'nota': ('EV calculado con cuotas reales de mercado.' if hay_reales else
                 '⚠️ EV teórico (cuotas justas del modelo) — no accionable; '
                 'compara contra las cuotas de tu casa para encontrar valor.'),
    }


# ---------------------------------------------------------------------------
# v37 (§1): constructor de SGP+ — pares correlacionados POSITIVAMENTE del
# mismo partido que las casas tienden a infrapreciar. A diferencia del parlay
# diversificado (que busca patas independientes), aquí buscamos DOS patas
# correlacionadas cuya prob conjunta real supera lo que la casa paga.
# ---------------------------------------------------------------------------
def combinar_patas(patas: List[Dict], bankroll: float = 0.0) -> Dict:
    """v41 (§3.2): combina 2-4 patas elegidas por el usuario (de 'Mejores
    Patas') en un parlay, calculando el PFP real. Aplica el factor de
    correlación empírico a los pares del MISMO partido (SGP), la cuota
    combinada, el EV y el riesgo por PFP. Las patas son dicts con al menos
    {partido, apuesta, prob, cuota, mercado}.
    """
    patas = [p for p in patas if p.get('prob') and p.get('cuota')]
    if len(patas) < 2:
        return {'error': 'Elige al menos 2 patas para combinar.'}
    if len(patas) > 6:
        return {'error': 'Máximo 6 patas (un parlay más largo casi nunca acierta).'}

    # detectar pares del mismo partido y aplicar factor de correlación (≤1)
    from collections import defaultdict
    por_partido = defaultdict(list)
    for i, p in enumerate(patas):
        por_partido[p.get('partido', f'_{i}')].append(i)
    # incompatibilidad: dos patas del mismo partido y mismo "grupo" (1X2 con
    # 1X2) o mutuamente excluyentes → se avisa
    avisos = []
    prob = 1.0
    for p in patas:
        prob *= float(p['prob'])
    pares_corr = 0
    for partido, idxs in por_partido.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                pa, pb = patas[idxs[a]], patas[idxs[b]]
                # mismo mercado en el mismo partido = casi seguro excluyente
                if pa.get('mercado') and pa.get('mercado') == pb.get('mercado'):
                    avisos.append(f"⚠️ '{pa['apuesta']}' y '{pb['apuesta']}' son del "
                                  f"mismo mercado del mismo partido: probablemente "
                                  f"excluyentes (no se pueden dar a la vez).")
                ida = _id_desde_apuesta(pa)
                idb = _id_desde_apuesta(pb)
                pares_corr += 1
                if ida and idb:
                    prob *= sgp_correlation.factor_par(
                        ida, pa['prob'], idb, pb['prob'], misma_familia=True)
                else:
                    prob *= HAIRCUT_CORRELACION

    cuota = 1.0
    for p in patas:
        cuota *= float(p['cuota'])
    cuota = min(cuota, CUOTA_MAXIMA_COMBINADA)
    pfp = round(float(prob), 4)
    ev = round(cuota * prob - 1.0, 3)
    riesgo = ('🟢 PFP alto' if pfp >= 0.45 else
              '🟡 PFP medio' if pfp >= 0.30 else '🔴 PFP bajo')
    if pfp < 0.30:
        avisos.append("🔴 Este parlay tiene BAJA probabilidad de acierto "
                      "(PFP < 30 %). Considera reducir patas o elegir opciones "
                      "más seguras.")
    salida = {
        'n_patas': len(patas), 'pfp': pfp, 'cuota_combinada': round(cuota, 2),
        'ev_parlay': ev, 'riesgo': riesgo, 'pares_mismo_partido': pares_corr,
        'patas': [{'partido': p.get('partido'), 'apuesta': p.get('apuesta'),
                   'mercado': p.get('mercado'), 'prob': round(p['prob'], 3),
                   'cuota': p['cuota']} for p in patas],
        'avisos': avisos,
    }
    if bankroll and pfp > 0:
        from bankroll_manager import calcular_stake
        k = calcular_stake(pfp, cuota, bankroll)
        salida['stake'] = k
    return salida


def _id_desde_apuesta(p: Dict) -> Optional[str]:
    """Mapea una pata (mercado + etiqueta) a un id canónico de sgp_correlation
    para el factor de correlación. Devuelve None si no se reconoce."""
    m = str(p.get('mercado', '')).upper()
    ap = str(p.get('apuesta', '')).lower()
    if m == '1X2':
        if ap.startswith('gana'):
            return None            # ganador local/visit (ambiguo sin lado)
        if 'empate' in ap:
            return 'draw_prob'
    if m == 'BTTS':
        return 'btts_si' if ('sí' in ap or 'si' in ap.split()) else 'btts_no'
    if m == 'GOLES':
        if 'más de 2.5' in ap:
            return 'over25'
        if 'menos de 2.5' in ap:
            return 'under25'
    return None


def construir_sgp_plus(motor, home: str, away: str) -> Dict:
    """Mejor SGP+ de 2 patas del partido (o aviso si no hay ninguno).

    EXIGE cuotas REALES en ambas patas: sin precio de mercado no se puede
    afirmar que la casa infraprecia, y con cuotas justas (1/prob) el EV
    degenera en un artefacto (la trampa de EV+ ilusorio de la v25). Recorre
    parejas compatibles y devuelve la de mayor EV estimado que supere el +5 %
    conjunto (spec §1.2).
    """
    if hasattr(motor, 'plantilla_club'):
        pl = motor.plantilla_club(home, away)
    else:
        pl = motor.plantilla(home, away)
    if 'error' in pl:
        return {'error': pl['error']}

    todas = obtener_selecciones(pl)
    reales = [s for s in todas if s.cuota_fuente == 'real']   # SIEMPRE reales
    if len(reales) < 2:
        return {'error': ('SGP+ necesita cuotas REALES en al menos 2 mercados '
                          'del partido (1X2, O/U 2.5, BTTS, AH ±0.5). Hoy no '
                          'hay suficientes cuotas vigentes para este partido.')}

    mejor = None
    evaluadas = 0
    for i in range(len(reales)):
        for j in range(i + 1, len(reales)):
            a, b = reales[i], reales[j]
            if not _compatibles(a, b):
                continue
            evaluadas += 1
            señal = sgp_correlation.senal_sgp_plus(
                a.id, a.prob, a.cuota, b.id, b.prob, b.cuota)
            if señal is None:
                continue
            if mejor is None or señal['ev_estimado'] > mejor['senal']['ev_estimado']:
                mejor = {'a': a, 'b': b, 'senal': señal}
    if mejor is None:
        return {'error': ('Sin SGP+ accionable en este partido: ninguna pareja '
                          'de mercados con cuota real muestra correlación '
                          'positiva infravalorada (EV conjunto > +5 %). Esto es '
                          'lo normal — un SGP+ real es infrecuente.'),
                'sin_senal': True, 'parejas_evaluadas': evaluadas}
    a, b, s = mejor['a'], mejor['b'], mejor['senal']
    return {
        'partido': pl.get('partido', f'{home} vs {away}'),
        'tipo': 'SGP+',
        'selecciones': [
            {'mercado': a.mercado, 'apuesta': a.apuesta, 'prob': round(a.prob, 3),
             'cuota': a.cuota},
            {'mercado': b.mercado, 'apuesta': b.apuesta, 'prob': round(b.prob, 3),
             'cuota': b.cuota}],
        'phi': s['phi'],
        'prob_conjunta_real': s['prob_conjunta_real'],
        'prob_si_independientes': s['prob_producto'],
        'boost_correlacion': s['boost_correlacion'],
        'cuota_sgp_estimada': s['cuota_sgp_estimada'],
        'ev_estimado': s['ev_estimado'],
        'parejas_evaluadas': evaluadas,
        'nota': ('Prob conjunta REAL ajustada por correlación empírica (φ de 3 '
                 'temporadas). La casa suele preciar el SGP como producto × '
                 'recorte genérico; cuando la correlación real es más fuerte, '
                 'infraprecia. Verifica el precio del SGP en tu libro: si es '
                 'cercano al producto de cuotas, tiene EV+ esperado. Sin feed '
                 'histórico de SGP no se puede backtestear el ROI (documentado).'),
    }


# ---------------------------------------------------------------------------
# v53 — COMBINADOR MANUAL: el usuario elige los mercados y la app calcula la
# probabilidad conjunta REAL (ajustada por correlación entre mercados del mismo
# partido) y la cuota combinada. Funciona en cualquier liga/deporte cuya
# plantilla exponga 'secciones' con campos 'pct' (todas las de clubes y Mundial).
# ---------------------------------------------------------------------------
def combinar_manual(pl: Dict, ids: List[str]) -> Dict:
    """Combina las selecciones elegidas por el usuario (por id) del MISMO
    partido y devuelve la probabilidad conjunta ajustada por correlación, la
    cuota combinada (justa y real si la hay) y el EV. Avisa de picks
    incompatibles (excluyentes/contradictorios)."""
    sels = {s.id: s for s in obtener_selecciones(pl)}
    elegidas = [sels[i] for i in ids if i in sels]
    if len(elegidas) < 2:
        return {'error': 'Elige al menos 2 mercados para combinar.'}

    # incompatibilidades (mismo grupo excluyente / contradicciones / equivalencias)
    incompatibles = []
    for i in range(len(elegidas)):
        for j in range(i + 1, len(elegidas)):
            if not _compatibles(elegidas[i], elegidas[j]):
                incompatibles.append((elegidas[i].apuesta, elegidas[j].apuesta))

    # probabilidad conjunta con corrección de correlación por pareja (mismo
    # motor empírico φ que usa el proponedor automático y el SGP+)
    prob = 1.0
    for s in elegidas:
        prob *= s.prob
    factores = []
    for i in range(len(elegidas)):
        for j in range(i + 1, len(elegidas)):
            f = sgp_correlation.factor_par(
                elegidas[i].id, elegidas[i].prob,
                elegidas[j].id, elegidas[j].prob,
                misma_familia=_correlacionadas(elegidas[i], elegidas[j]))
            prob *= f
            if f < 0.999 or f > 1.001:
                factores.append(round(f, 3))
    prob = max(min(prob, 1.0), 1e-9)

    cuota_justa_comb = round(1.0 / prob, 2)               # combinada "justa"
    hay_reales = all(s.cuota_fuente == 'real' for s in elegidas)
    cuota_real_comb = None
    ev = None
    if hay_reales:
        cuota_real_comb = 1.0
        for s in elegidas:
            cuota_real_comb *= s.cuota
        cuota_real_comb = round(cuota_real_comb, 2)
        ev = round(cuota_real_comb * prob - 1.0, 3)

    return {
        'n': len(elegidas),
        'prob_conjunta': round(prob, 4),
        'cuota_justa_combinada': cuota_justa_comb,
        'cuota_real_combinada': cuota_real_comb,
        'ev': ev,
        'hay_cuotas_reales': hay_reales,
        'correlacion_aplicada': bool(factores),
        'patas': [{'mercado': s.mercado, 'apuesta': s.apuesta,
                   'prob': round(s.prob, 3), 'cuota': s.cuota,
                   'cuota_fuente': s.cuota_fuente} for s in elegidas],
        'incompatibles': incompatibles,
        'nota': ('Probabilidad conjunta REAL ajustada por la correlación entre '
                 'mercados del mismo partido (no es el simple producto). Cuota '
                 'justa = 1/prob. Si hay cuotas reales, el EV es accionable; '
                 'si no, compara la cuota combinada contra tu casa.'),
    }
