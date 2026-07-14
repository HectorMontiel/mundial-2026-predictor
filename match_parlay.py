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
    'conservador': {'min_prob': 0.65, 'zona': (0.60, 1.01), 'objetivo': 'prob',
                    'reduce_picks': True},
    'medio':       {'min_prob': 0.50, 'zona': (0.15, 0.60), 'objetivo': 'balance',
                    'alpha': 0.3},
    'agresivo':    {'min_prob': 0.30, 'zona': (0.05, 1.01), 'objetivo': 'cuota'},
}
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
    corr = [[False] * m for _ in range(m)]
    for i in range(m):
        for j in range(i + 1, m):
            c = _compatibles(cands[i], cands[j])
            compat[i][j] = compat[j][i] = c
            r = _correlacionadas(cands[i], cands[j])
            corr[i][j] = corr[j][i] = r

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
                add_hc = sum(1 for i in idxs if corr[j][i])
                prob2 = prob * probs[j] * HAIRCUT_CORRELACION ** add_hc
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


def construir_parlay_partido(motor, home: str, away: str,
                             num_selecciones: int = 6,
                             perfil: str = 'medio',
                             usar_cuotas_reales: bool = True,
                             excluir_alto_riesgo: bool = True) -> Dict:
    """Parlay óptimo dentro de UN partido (v20: SmartParlayBuilder)."""
    num_selecciones = max(MIN_SELECCIONES, min(8, int(num_selecciones)))
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

    return {
        'partido': pl.get('partido', f'{home} vs {away}'),
        'perfil': perfil, 'umbral_usado': umbral,
        'piso_conjunto': cfg['zona'][0],
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
