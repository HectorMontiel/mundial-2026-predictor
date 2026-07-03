#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de altitud y aclimatación — Mundial 2026 (v10).

Los 16 estadios oficiales con su altitud real y la altitud HABITUAL de cada
selección (la de su estadio local), para modelar la aclimatación:

    aclimatado          = ALT_HABITUAL >= 1500 m
    penalización de xG  = jugar en altura sin estar aclimatado
    bonificación local  = estar aclimatado por encima de la sede cuando el
                          visitante no lo está

Reglas (especificación del analista):
  altitud > 1500 m: local no habituado (<1000 m) -> xG ×0.90
                    visitante no habituado        -> xG ×0.88
  altitud > 2500 m: penalizaciones suben a ×0.85 y ×0.82
  ambos aclimatados (>=1500 m): sin penalización
  bonus: si ALT_HABITUAL_local >= altitud_sede y visitante no aclimatado -> local ×1.05
  2ª mitad: el equipo no aclimatado en altura baja un escalón su rendimiento
  córners: +0.2 por partido en altura (balón más rápido en aire menos denso)
"""

from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Los 16 estadios oficiales del Mundial 2026 (FIFA; altitud real en msnm)
# Clave = nombre interno (coincide con config.STADIUMS y el calendario)
# ---------------------------------------------------------------------------
ESTADIOS_MUNDIAL = {
    'Azteca':            {'nombre': 'Estadio Azteca', 'ciudad': 'Ciudad de México (México)', 'altitud': 2240},
    'Estadio_BBVA':      {'nombre': 'Estadio BBVA', 'ciudad': 'Monterrey (México)', 'altitud': 537},
    'Akron':             {'nombre': 'Estadio Akron', 'ciudad': 'Guadalajara (México)', 'altitud': 1564},
    'MetLife':           {'nombre': 'MetLife Stadium', 'ciudad': 'East Rutherford (EE.UU.)', 'altitud': 2},
    'AT&T':              {'nombre': 'AT&T Stadium', 'ciudad': 'Arlington (EE.UU.)', 'altitud': 168},
    'SoFi':              {'nombre': 'SoFi Stadium', 'ciudad': 'Inglewood (EE.UU.)', 'altitud': 71},
    'HardRock':          {'nombre': 'Hard Rock Stadium', 'ciudad': 'Miami Gardens (EE.UU.)', 'altitud': 2},
    'Mercedes-Benz':     {'nombre': 'Mercedes-Benz Stadium', 'ciudad': 'Atlanta (EE.UU.)', 'altitud': 315},
    "Levi's":            {'nombre': "Levi's Stadium", 'ciudad': 'Santa Clara (EE.UU.)', 'altitud': 2},
    'NRG':               {'nombre': 'NRG Stadium', 'ciudad': 'Houston (EE.UU.)', 'altitud': 43},
    'Lincoln_Financial': {'nombre': 'Lincoln Financial Field', 'ciudad': 'Filadelfia (EE.UU.)', 'altitud': 12},
    'Arrowhead':         {'nombre': 'Arrowhead Stadium', 'ciudad': 'Kansas City (EE.UU.)', 'altitud': 271},
    'Gillette':          {'nombre': 'Gillette Stadium', 'ciudad': 'Foxborough (EE.UU.)', 'altitud': 75},
    'Lumen_Field':       {'nombre': 'Lumen Field', 'ciudad': 'Seattle (EE.UU.)', 'altitud': 5},
    'BC_Place':          {'nombre': 'BC Place', 'ciudad': 'Vancouver (Canadá)', 'altitud': 2},
    'BMO_Field':         {'nombre': 'BMO Field', 'ciudad': 'Toronto (Canadá)', 'altitud': 86},
}
ESTADIO_POR_DEFECTO = 'MetLife'   # si el usuario no especifica sede

# ---------------------------------------------------------------------------
# Altitud habitual de cada selección (estadio local / capital futbolística)
# ---------------------------------------------------------------------------
ALT_HABITUAL = {
    'MEX': 2240, 'ECU': 2780, 'COL': 2600,   # aclimatados a la altura
    'ARG': 25, 'BRA': 760, 'URU': 40, 'PER': 150, 'CHI': 570, 'PAR': 120,
    'USA': 100, 'CAN': 76, 'CRC': 1170, 'PAN': 20, 'HON': 990, 'JAM': 50,
    'FRA': 35, 'ENG': 15, 'ESP': 667, 'GER': 50, 'ITA': 20, 'POR': 100,
    'NED': 0, 'BEL': 20, 'CRO': 120, 'SRB': 117, 'SUI': 540, 'AUT': 170,
    'NOR': 10, 'DEN': 10, 'SCO': 40,
    'MAR': 60, 'SEN': 20, 'CMR': 720, 'GHA': 60, 'NGA': 450, 'TUN': 10,
    'ALG': 190, 'EGY': 20, 'CIV': 20,
    'JPN': 20, 'KOR': 40, 'IRN': 1190, 'AUS': 20, 'KSA': 610, 'QAT': 10,
    'UZB': 450, 'JOR': 780, 'NZL': 20, 'CPV': 50,
}

UMBRAL_ACLIMATADO = 1500.0   # habituado a jugar en altura
UMBRAL_NO_HABITUADO = 1000.0


def altitud_estadio(estadio: Optional[str]) -> float:
    """Altitud del estadio; sin sede especificada se asume MetLife (2 m)."""
    if estadio and estadio in ESTADIOS_MUNDIAL:
        return float(ESTADIOS_MUNDIAL[estadio]['altitud'])
    from config import STADIUMS
    if estadio and estadio in STADIUMS:
        return float(STADIUMS[estadio])
    return float(ESTADIOS_MUNDIAL[ESTADIO_POR_DEFECTO]['altitud'])


def esta_aclimatado(equipo: str) -> bool:
    return ALT_HABITUAL.get(equipo, 100.0) >= UMBRAL_ACLIMATADO


def nivel_aclimatacion(equipo: str) -> str:
    alt = ALT_HABITUAL.get(equipo, 100.0)
    if alt >= UMBRAL_ACLIMATADO:
        return f"aclimatado a la altura ({alt:.0f} m habituales)"
    if alt >= UMBRAL_NO_HABITUADO:
        return f"parcialmente habituado ({alt:.0f} m habituales)"
    return f"no habituado a la altura ({alt:.0f} m habituales)"


def ajustar_xg_por_altitud(lam_h: float, lam_a: float, home: str, away: str,
                           altitud: float) -> Tuple[float, float, Dict]:
    """
    Aplica las penalizaciones/bonificaciones de aclimatación al xG esperado.
    Devuelve (λ_local, λ_visitante, detalle) con los factores aplicados.
    """
    alt_h = ALT_HABITUAL.get(home, 100.0)
    alt_a = ALT_HABITUAL.get(away, 100.0)
    factor_h = factor_a = 1.0

    if altitud > 1500 and not (alt_h >= UMBRAL_ACLIMATADO and alt_a >= UMBRAL_ACLIMATADO):
        if altitud > 2500:
            pen_local, pen_visit = 0.15, 0.18
        else:
            pen_local, pen_visit = 0.10, 0.12
        if alt_h < UMBRAL_NO_HABITUADO:
            factor_h *= (1 - pen_local)
        if alt_a < UMBRAL_NO_HABITUADO:
            factor_a *= (1 - pen_visit)
        # Bonificación: local aclimatado por encima de la sede vs visitante no
        if alt_h >= altitud and alt_a < UMBRAL_ACLIMATADO:
            factor_h *= 1.05

    detalle = {
        'altitud_sede': round(altitud, 0),
        'factor_xg_local': round(factor_h, 3),
        'factor_xg_visitante': round(factor_a, 3),
        'local_aclimatado': alt_h >= UMBRAL_ACLIMATADO,
        'visitante_aclimatado': alt_a >= UMBRAL_ACLIMATADO,
        'alt_habitual_local': alt_h,
        'alt_habitual_visitante': alt_a,
    }
    return lam_h * factor_h, lam_a * factor_a, detalle


def ajuste_2da_mitad(pct_2h: float, equipo: str, altitud: float) -> float:
    """
    En altura, el equipo NO aclimatado baja un escalón su rendimiento de
    segunda mitad (≈ -7 puntos porcentuales de su fracción de goles en 2ª parte).
    """
    if altitud > 1500 and not esta_aclimatado(equipo):
        return max(0.25, pct_2h - 0.07)
    return pct_2h


def ajuste_corners(corners_totales: float, altitud: float) -> float:
    """+0.2 córners por partido en altura (balón más vivo en aire menos denso)."""
    return corners_totales + (0.2 if altitud > 1500 else 0.0)


def descripcion_efecto(home: str, away: str, estadio: Optional[str],
                       detalle: Dict) -> str:
    """Frase de observaciones sobre el efecto de la altitud."""
    alt = detalle['altitud_sede']
    if alt <= 1000:
        return f"Altitud de la sede ({alt:.0f} m): sin efecto relevante."
    partes = [f"Altitud de la sede ({alt:.0f} m):"]
    if detalle['factor_xg_local'] < 1.0:
        partes.append(f"el local pierde un {100*(1-detalle['factor_xg_local']):.0f} % de generación ofensiva;")
    if detalle['factor_xg_visitante'] < 1.0:
        partes.append(f"el visitante pierde un {100*(1-detalle['factor_xg_visitante']):.0f} %;")
    if detalle['factor_xg_local'] > 1.0:
        partes.append("el local, aclimatado por encima de la sede, recibe un bono del 5 %;")
    if detalle['local_aclimatado'] and detalle['visitante_aclimatado']:
        partes.append("ambos equipos están aclimatados: sin penalizaciones.")
    return ' '.join(partes).rstrip(';') + '.'
