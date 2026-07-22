#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Índice de Desincronización Circadiana — CDI (v30 §2).

Hipótesis: el visitante que cruza husos horarios (sobre todo hacia el ESTE)
llega desincronizado respecto a su reloj biológico y rinde peor. El mercado
no lo tasa bien.

Implementación validable: CDI = husos cruzados por el visitante entre la
sede de su PARTIDO ANTERIOR y la sede actual, CON SIGNO (+ = viajó al este,
el desfase más duro). Se calcula en el pase cronológico (sin fuga). Si no hay
partido anterior reciente (>7 días), CDI = 0.

Husos horarios (offset UTC estándar, sin horario de verano — la señal es la
DIFERENCIA, robusta al DST) por sede. Cada deporte aporta su mapa.
"""

from typing import Dict, Optional

# MLB (código Retrosheet → offset UTC de la ciudad del equipo)
TZ_MLB: Dict[str, int] = {
    'ANA': -8, 'ARI': -7, 'ATL': -5, 'BAL': -5, 'BOS': -5, 'CHA': -6,
    'CHN': -6, 'CIN': -5, 'CLE': -5, 'COL': -7, 'DET': -5, 'HOU': -6,
    'KCA': -6, 'LAN': -8, 'MIA': -5, 'MIL': -6, 'MIN': -6, 'NYA': -5,
    'NYN': -5, 'OAK': -8, 'ATH': -8, 'PHI': -5, 'PIT': -5, 'SDN': -8,
    'SEA': -8, 'SFN': -8, 'SLN': -6, 'TBA': -5, 'TEX': -6, 'TOR': -5,
    'WAS': -5,
}

# NBA (abreviatura → offset UTC)
TZ_NBA: Dict[str, int] = {
    'ATL': -5, 'BOS': -5, 'BKN': -5, 'CHA': -5, 'CHI': -6, 'CLE': -5,
    'DAL': -6, 'DEN': -7, 'DET': -5, 'GSW': -8, 'HOU': -6, 'IND': -5,
    'LAC': -8, 'LAL': -8, 'MEM': -6, 'MIA': -5, 'MIL': -6, 'MIN': -6,
    'NOP': -6, 'NYK': -5, 'OKC': -6, 'ORL': -5, 'PHI': -5, 'PHX': -7,
    'POR': -8, 'SAC': -8, 'SAS': -6, 'TOR': -5, 'UTA': -7, 'WAS': -5,
}


def cdi_desde_offsets(tz_origen: Optional[int], tz_sede: int) -> float:
    """Husos cruzados con signo (+ = viajó al este). Normalizado a [-1,1]
    (máximo realista ~3 husos en Norteamérica)."""
    if tz_origen is None:
        return 0.0
    return float(max(min(tz_sede - tz_origen, 3), -3)) / 3.0
