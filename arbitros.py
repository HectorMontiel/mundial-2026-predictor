#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de arbitraje — Mundial 2026 (lista ampliada: 51 árbitros centrales).

Fuente: FIFA + WorldReferee, partidos internacionales 2022-2025 normalizados
a promedios por 90 minutos.

Modelo de tarjetas v2 (interacción árbitro-equipo):
    El ANCLA es el promedio real del árbitro (dato medido sobre muchos
    partidos), modulado por la desviación disciplinaria del equipo:

        amarillas_equipo = (AMA_P90_árbitro / 2)
                           × (1 + 0.05 × (TARJ_AMA_MA5_equipo − 2.0))
                           × (1.08 si el equipo juega en bloque alto)
                           × (1.15 si el partido es de eliminación directa)
                           × ajuste por sesgo local del árbitro
                             (local ×(1−2·desvío), visitante ×(1+2·desvío);
                              p. ej. sesgo 55 % ⇒ local ×0.90, visitante ×1.10)

    Se prefiere el ancla arbitral porque el p90 del árbitro es señal REAL,
    mientras que las tarjetas MA5 de los equipos provienen del relleno
    calibrado (semi-sintéticas hasta que API-Football inyecte tarjetas reales).
"""

from typing import Dict, Optional, Tuple

import numpy as np

# Medias globales del cuerpo arbitral (para normalizar factores)
MEDIA_AMA_P90 = 3.8
MEDIA_ROJ_P90 = 0.12
MEDIA_PEN_P90 = 0.22

# Factores del modelo v2 de tarjetas
DESVIACION_EQUIPO_COEF = 0.05     # +5 % por cada amarilla MA5 por encima de 2.0
FACTOR_BLOQUE_ALTO = 1.08         # presión alta => más fricción y amarillas
FACTOR_ELIMINATORIA = 1.15        # tensión de vida o muerte
FACTOR_GRUPOS = 1.05              # torneo mundialista, fase de grupos

# Perfil que se usa cuando el usuario no elige árbitro
ARBITRO_PROMEDIO = {
    'pais': 'FIFA', 'confederacion': '—', 'ama_p90': 3.8, 'roj_p90': 0.12,
    'pen_p90': 0.22, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 41,
}

# sesgo_local: proporción de decisiones dudosas que favorecen al local
# (0.50 = sin sesgo). Lista oficial actualizada proporcionada por el analista.
ARBITROS: Dict[str, Dict] = {
    # ---------------------------- CONMEBOL ---------------------------- #
    'Facundo Tello':      {'pais': 'Argentina', 'confederacion': 'CONMEBOL', 'ama_p90': 4.2, 'roj_p90': 0.15, 'pen_p90': 0.25, 'criterio': 'Estricto', 'sesgo_local': 0.55, 'edad': 42},
    'Wilton Sampaio':     {'pais': 'Brasil', 'confederacion': 'CONMEBOL', 'ama_p90': 3.5, 'roj_p90': 0.10, 'pen_p90': 0.18, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 39},
    'Jesús Valenzuela':   {'pais': 'Venezuela', 'confederacion': 'CONMEBOL', 'ama_p90': 4.5, 'roj_p90': 0.18, 'pen_p90': 0.30, 'criterio': 'Muy estricto', 'sesgo_local': 0.50, 'edad': 40},
    'Andrés Matonte':     {'pais': 'Uruguay', 'confederacion': 'CONMEBOL', 'ama_p90': 4.0, 'roj_p90': 0.14, 'pen_p90': 0.22, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 38},
    'Raphael Claus':      {'pais': 'Brasil', 'confederacion': 'CONMEBOL', 'ama_p90': 3.8, 'roj_p90': 0.12, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 43},
    'Alexis Herrera':     {'pais': 'Venezuela', 'confederacion': 'CONMEBOL', 'ama_p90': 4.3, 'roj_p90': 0.16, 'pen_p90': 0.27, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 36},
    'Piero Maza':         {'pais': 'Chile', 'confederacion': 'CONMEBOL', 'ama_p90': 4.1, 'roj_p90': 0.13, 'pen_p90': 0.23, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 38},
    'Nicolás Lamolina':   {'pais': 'Argentina', 'confederacion': 'CONMEBOL', 'ama_p90': 3.8, 'roj_p90': 0.11, 'pen_p90': 0.21, 'criterio': 'Moderado', 'sesgo_local': 0.53, 'edad': 36},
    'Diego Haro':         {'pais': 'Perú', 'confederacion': 'CONMEBOL', 'ama_p90': 4.2, 'roj_p90': 0.14, 'pen_p90': 0.25, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 40},
    'Yamila Rodríguez':   {'pais': 'Argentina', 'confederacion': 'CONMEBOL', 'ama_p90': 4.0, 'roj_p90': 0.12, 'pen_p90': 0.23, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 35},
    # ------------------------------ UEFA ------------------------------ #
    'Clément Turpin':     {'pais': 'Francia', 'confederacion': 'UEFA', 'ama_p90': 3.8, 'roj_p90': 0.12, 'pen_p90': 0.22, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 41},
    'Michael Oliver':     {'pais': 'Inglaterra', 'confederacion': 'UEFA', 'ama_p90': 3.2, 'roj_p90': 0.08, 'pen_p90': 0.20, 'criterio': 'Permisivo', 'sesgo_local': 0.52, 'edad': 39},
    'Danny Makkelie':     {'pais': 'Países Bajos', 'confederacion': 'UEFA', 'ama_p90': 4.0, 'roj_p90': 0.14, 'pen_p90': 0.28, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 41},
    'Szymon Marciniak':   {'pais': 'Polonia', 'confederacion': 'UEFA', 'ama_p90': 3.6, 'roj_p90': 0.11, 'pen_p90': 0.19, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 44},
    'Daniele Orsato':     {'pais': 'Italia', 'confederacion': 'UEFA', 'ama_p90': 4.1, 'roj_p90': 0.13, 'pen_p90': 0.24, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 48},
    'Slavko Vinčić':      {'pais': 'Eslovenia', 'confederacion': 'UEFA', 'ama_p90': 3.9, 'roj_p90': 0.10, 'pen_p90': 0.21, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 44},
    'István Kovács':      {'pais': 'Rumanía', 'confederacion': 'UEFA', 'ama_p90': 4.2, 'roj_p90': 0.15, 'pen_p90': 0.23, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 39},
    'Felix Brych':        {'pais': 'Alemania', 'confederacion': 'UEFA', 'ama_p90': 3.5, 'roj_p90': 0.09, 'pen_p90': 0.17, 'criterio': 'Moderado', 'sesgo_local': 0.53, 'edad': 48},
    'Anthony Taylor':     {'pais': 'Inglaterra', 'confederacion': 'UEFA', 'ama_p90': 3.3, 'roj_p90': 0.07, 'pen_p90': 0.19, 'criterio': 'Permisivo', 'sesgo_local': 0.50, 'edad': 45},
    'Jesús Gil Manzano':  {'pais': 'España', 'confederacion': 'UEFA', 'ama_p90': 4.4, 'roj_p90': 0.17, 'pen_p90': 0.26, 'criterio': 'Muy estricto', 'sesgo_local': 0.50, 'edad': 41},
    'Sandro Schärer':     {'pais': 'Suiza', 'confederacion': 'UEFA', 'ama_p90': 3.7, 'roj_p90': 0.10, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 36},
    'Espen Eskås':        {'pais': 'Noruega', 'confederacion': 'UEFA', 'ama_p90': 3.6, 'roj_p90': 0.08, 'pen_p90': 0.19, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 37},
    'Glenn Nyberg':       {'pais': 'Suecia', 'confederacion': 'UEFA', 'ama_p90': 3.9, 'roj_p90': 0.11, 'pen_p90': 0.22, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 35},
    'Tobias Stieler':     {'pais': 'Alemania', 'confederacion': 'UEFA', 'ama_p90': 3.5, 'roj_p90': 0.08, 'pen_p90': 0.18, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 42},
    'Irfan Peljto':       {'pais': 'Bosnia', 'confederacion': 'UEFA', 'ama_p90': 4.2, 'roj_p90': 0.14, 'pen_p90': 0.24, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 39},
    'Benoît Bastien':     {'pais': 'Francia', 'confederacion': 'UEFA', 'ama_p90': 3.4, 'roj_p90': 0.07, 'pen_p90': 0.19, 'criterio': 'Permisivo', 'sesgo_local': 0.50, 'edad': 41},
    'Ovidiu Hațegan':     {'pais': 'Rumanía', 'confederacion': 'UEFA', 'ama_p90': 3.9, 'roj_p90': 0.10, 'pen_p90': 0.21, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 43},
    'Artur Soares Dias':  {'pais': 'Portugal', 'confederacion': 'UEFA', 'ama_p90': 4.1, 'roj_p90': 0.12, 'pen_p90': 0.23, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 45},
    'José María Sánchez': {'pais': 'España', 'confederacion': 'UEFA', 'ama_p90': 4.0, 'roj_p90': 0.12, 'pen_p90': 0.22, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 39},
    'Mohammed Al-Hakim':  {'pais': 'Suecia', 'confederacion': 'UEFA', 'ama_p90': 3.8, 'roj_p90': 0.11, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 36},
    'Stephanie Frappart': {'pais': 'Francia', 'confederacion': 'UEFA', 'ama_p90': 3.7, 'roj_p90': 0.09, 'pen_p90': 0.21, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 41},
    # ---------------------------- CONCACAF ---------------------------- #
    'César Arturo Ramos': {'pais': 'México', 'confederacion': 'CONCACAF', 'ama_p90': 4.1, 'roj_p90': 0.16, 'pen_p90': 0.24, 'criterio': 'Estricto', 'sesgo_local': 0.58, 'edad': 42},
    'Iván Barton':        {'pais': 'El Salvador', 'confederacion': 'CONCACAF', 'ama_p90': 3.7, 'roj_p90': 0.11, 'pen_p90': 0.21, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 36},
    'Mario Escobar':      {'pais': 'Guatemala', 'confederacion': 'CONCACAF', 'ama_p90': 4.3, 'roj_p90': 0.17, 'pen_p90': 0.25, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 39},
    'Said Martínez':      {'pais': 'Honduras', 'confederacion': 'CONCACAF', 'ama_p90': 4.0, 'roj_p90': 0.14, 'pen_p90': 0.23, 'criterio': 'Estricto', 'sesgo_local': 0.54, 'edad': 34},
    'Jair Marrufo':       {'pais': 'Estados Unidos', 'confederacion': 'CONCACAF', 'ama_p90': 3.4, 'roj_p90': 0.09, 'pen_p90': 0.18, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 45},
    'Drew Fischer':       {'pais': 'Canadá', 'confederacion': 'CONCACAF', 'ama_p90': 3.6, 'roj_p90': 0.10, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 40},
    'Katia García':       {'pais': 'México', 'confederacion': 'CONCACAF', 'ama_p90': 3.9, 'roj_p90': 0.08, 'pen_p90': 0.22, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 32},
    'Keylor Herrera':     {'pais': 'Costa Rica', 'confederacion': 'CONCACAF', 'ama_p90': 4.0, 'roj_p90': 0.13, 'pen_p90': 0.22, 'criterio': 'Estricto', 'sesgo_local': 0.55, 'edad': 35},
    'Anthony Buttimer':   {'pais': 'Estados Unidos', 'confederacion': 'CONCACAF', 'ama_p90': 3.7, 'roj_p90': 0.10, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 38},
    # ------------------------------- CAF ------------------------------- #
    'Mustapha Ghorbal':   {'pais': 'Argelia', 'confederacion': 'CAF', 'ama_p90': 4.0, 'roj_p90': 0.13, 'pen_p90': 0.22, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 38},
    'Bakary Gassama':     {'pais': 'Gambia', 'confederacion': 'CAF', 'ama_p90': 3.8, 'roj_p90': 0.12, 'pen_p90': 0.21, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 45},
    'Victor Gomes':       {'pais': 'Sudáfrica', 'confederacion': 'CAF', 'ama_p90': 4.2, 'roj_p90': 0.15, 'pen_p90': 0.24, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 41},
    'Redouane Jiyed':     {'pais': 'Marruecos', 'confederacion': 'CAF', 'ama_p90': 3.9, 'roj_p90': 0.11, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 43},
    'Jean-Jacques Ndala': {'pais': 'RD Congo', 'confederacion': 'CAF', 'ama_p90': 4.1, 'roj_p90': 0.14, 'pen_p90': 0.23, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 37},
    'Salima Mukansanga':  {'pais': 'Ruanda', 'confederacion': 'CAF', 'ama_p90': 3.6, 'roj_p90': 0.09, 'pen_p90': 0.18, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 36},
    # ------------------------------- AFC ------------------------------- #
    'Alireza Faghani':    {'pais': 'Irán', 'confederacion': 'AFC', 'ama_p90': 3.7, 'roj_p90': 0.10, 'pen_p90': 0.19, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 46},
    'Abdulla Hassan':     {'pais': 'EAU', 'confederacion': 'AFC', 'ama_p90': 3.5, 'roj_p90': 0.09, 'pen_p90': 0.18, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 42},
    'Ma Ning':            {'pais': 'China', 'confederacion': 'AFC', 'ama_p90': 4.3, 'roj_p90': 0.16, 'pen_p90': 0.25, 'criterio': 'Estricto', 'sesgo_local': 0.50, 'edad': 44},
    'Ryuji Sato':         {'pais': 'Japón', 'confederacion': 'AFC', 'ama_p90': 3.4, 'roj_p90': 0.08, 'pen_p90': 0.17, 'criterio': 'Permisivo', 'sesgo_local': 0.50, 'edad': 46},
    'Chris Beath':        {'pais': 'Australia', 'confederacion': 'AFC', 'ama_p90': 3.8, 'roj_p90': 0.11, 'pen_p90': 0.20, 'criterio': 'Moderado', 'sesgo_local': 0.50, 'edad': 39},
}


# ---------------------------------------------------------------------------
# Si referee_scraper.py generó referees.json (actualización semanal desde
# WorldReferee), sus valores PISAN a los pregrabados de este módulo.
# ---------------------------------------------------------------------------
def _cargar_actualizacion():
    import json, os
    if not os.path.exists('referees.json'):
        return
    try:
        with open('referees.json', 'r', encoding='utf-8') as f:
            datos = json.load(f)
        for nombre, perfil in datos.get('arbitros', {}).items():
            if nombre in ARBITROS:
                ARBITROS[nombre].update({k: v for k, v in perfil.items()
                                         if k in ARBITROS[nombre]})
            else:
                ARBITROS[nombre] = perfil
    except Exception:
        pass  # el respaldo pregrabado sigue vigente


_cargar_actualizacion()


def perfil_arbitro(nombre: Optional[str]) -> Tuple[str, Dict]:
    """Devuelve (nombre_mostrado, perfil). Sin nombre -> perfil promedio FIFA."""
    if nombre and nombre in ARBITROS:
        return nombre, ARBITROS[nombre]
    return 'Promedio FIFA (sin asignar)', dict(ARBITRO_PROMEDIO)


def modelo_tarjetas(perfil: Dict, base_amarillas_local: float, base_rojas_local: float,
                    base_amarillas_visit: float, base_rojas_visit: float,
                    estilo_local: str = 'bloque_bajo', estilo_visit: str = 'bloque_bajo',
                    fase: str = 'grupos') -> Dict:
    """
    Modelo v2 con interacción árbitro-equipo (ver docstring del módulo).
    El ancla es el p90 REAL del árbitro; la desviación MA5 del equipo, su
    estilo, la fase del torneo y el sesgo local modulan el reparto.
    """
    factor_fase = FACTOR_ELIMINATORIA if fase == 'eliminatoria' else FACTOR_GRUPOS
    desvio = perfil['sesgo_local'] - 0.50  # sesgo 55 % => local ×0.90, visit ×1.10

    def amarillas_equipo(base_ma5: float, estilo: str, es_local: bool) -> float:
        ama = (perfil['ama_p90'] / 2.0) * (1 + DESVIACION_EQUIPO_COEF * (base_ma5 - 2.0))
        if estilo == 'bloque_alto':
            ama *= FACTOR_BLOQUE_ALTO
        ama *= factor_fase
        ama *= (1 - 2 * desvio) if es_local else (1 + 2 * desvio)
        return max(0.2, float(ama))

    ama_h = amarillas_equipo(base_amarillas_local, estilo_local, True)
    ama_a = amarillas_equipo(base_amarillas_visit, estilo_visit, False)

    # Rojas: ancla arbitral repartida por la indisciplina relativa de los
    # equipos, con el mismo ajuste de fase y sesgo.
    factor_roj = perfil['roj_p90'] / MEDIA_ROJ_P90
    agresividad_total = max(base_rojas_local + base_rojas_visit, 1e-6)
    roj_equipos = (base_rojas_local + base_rojas_visit)
    roj_total = (0.5 * perfil['roj_p90'] + 0.5 * roj_equipos * factor_roj) * factor_fase
    roj_h = roj_total * (base_rojas_local / agresividad_total) * (1 - 2 * desvio)
    roj_a = roj_total * (base_rojas_visit / agresividad_total) * (1 + 2 * desvio)

    return {
        'amarillas_local': round(ama_h, 2),
        'amarillas_visitante': round(ama_a, 2),
        'rojas_local': round(float(roj_h), 3),
        'rojas_visitante': round(float(roj_a), 3),
        'total_tarjetas': round(ama_h + ama_a + float(roj_h) + float(roj_a), 2),
        'factor_arbitro': round(perfil['ama_p90'] / MEDIA_AMA_P90, 3),
        'fase': fase,
    }


def modelo_penaltis(perfil: Dict, lam_local: float, lam_visit: float) -> Dict:
    """
    Penaltis esperados según el árbitro (PEN_P90) repartidos por el volumen
    ofensivo de cada equipo (quien más ataca, más penaltis recibe a favor).
    """
    total = perfil['pen_p90']
    ataque_total = max(lam_local + lam_visit, 1e-6)
    pen_h = total * (lam_local / ataque_total)
    pen_a = total * (lam_visit / ataque_total)
    return {
        'pen_esperados_total': round(float(total), 3),
        'prob_penal_en_partido': round(float(1 - np.exp(-total)), 3),
        'prob_penal_favor_local': round(float(1 - np.exp(-pen_h)), 3),
        'prob_penal_favor_visitante': round(float(1 - np.exp(-pen_a)), 3),
    }


def ajuste_reaccion_eliminatoria(lam_h: float, lam_a: float,
                                 reaccion_local: str, reaccion_visit: str,
                                 fase: str) -> Tuple[float, float]:
    """
    Ajuste de "vida o muerte" en eliminación directa, integrado a nivel de
    partido a partir de la regla por tramos ("+10 % de xG durante los 15
    minutos posteriores a encajar"):

        Δλ_equipo ≈ λ_equipo × 0.10 × (15/90) × λ_rival   (reacción Fuerte)
        Δλ_rival  ≈ λ_rival  × 0.10 × (15/90) × λ_equipo  (reacción Débil)

    En fase de grupos el efecto es la mitad (+5 % por tramo).
    """
    if fase != 'eliminatoria':
        coef = 0.05  # fase de grupos: respuestas menos acentuadas
    else:
        coef = 0.10
    tramo = 15.0 / 90.0

    ajuste_h = ajuste_a = 0.0
    if str(reaccion_local).startswith('Fuerte'):
        ajuste_h += lam_h * coef * tramo * lam_a
    if str(reaccion_local).startswith('Débil'):
        ajuste_a += lam_a * coef * tramo * lam_h  # el rival castiga el desplome
    if str(reaccion_visit).startswith('Fuerte'):
        ajuste_a += lam_a * coef * tramo * lam_h
    if str(reaccion_visit).startswith('Débil'):
        ajuste_h += lam_h * coef * tramo * lam_a

    return (float(np.clip(lam_h + ajuste_h, 0.2, 3.6)),
            float(np.clip(lam_a + ajuste_a, 0.2, 3.6)))


def descripcion_arbitro(nombre: str, perfil: Dict) -> str:
    """Línea de observaciones en lenguaje natural para la plantilla."""
    sesgo = ""
    if perfil['sesgo_local'] > 0.51:
        sesgo = (f" Muestra un ligero sesgo a favor del local "
                 f"({perfil['sesgo_local']*100:.0f} % de decisiones dudosas).")
    return (f"Árbitro {nombre} ({perfil['criterio'].lower()}, {perfil['confederacion']}): "
            f"promedia {perfil['ama_p90']:.1f} amarillas, {perfil['roj_p90']:.2f} rojas y "
            f"{perfil['pen_p90']:.2f} penaltis por 90 minutos.{sesgo}")
