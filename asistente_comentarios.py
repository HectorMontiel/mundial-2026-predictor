#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Asistente de comentarios del analista (v22, spec §3.4 — versión honesta).

El master prompt pedía un SLM local (Phi-3 / Llama 3.2). NO es viable en
Streamlit Cloud free (≈1 GB de RAM; el modelo más pequeño cuantizado supera
el límite de 100 MB de GitHub y la RAM disponible), así que:

  1. Base SIEMPRE disponible: comentarios en lenguaje natural compuestos por
     plantillas a partir de los datos REALES del modelo (probabilidades, xG,
     EV con cuotas reales, riesgo de mercado, localía). Deterministas por
     partido (semilla = nombres), sin coste y sin alucinaciones.
  2. Mejora opcional LOCAL: si hay un servidor Ollama corriendo
     (http://localhost:11434, modelo en OLLAMA_MODEL, por defecto phi3),
     se le pide reescribir el comentario con más soltura. Si no está, no
     pasa nada — la base ya es útil. El texto del SLM se marca como tal.
"""

import hashlib
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'phi3')


def _semilla(*textos: str) -> int:
    return int(hashlib.md5('|'.join(textos).encode()).hexdigest()[:8], 16)


def _elige(opciones: List[str], semilla: int, sal: int = 0) -> str:
    return opciones[(semilla + sal) % len(opciones)]


def _residuo_shadow(nombre_home: str, nombre_away: str) -> Optional[float]:
    """Residuo del Shadow Booster para este partido (solo ligas adoptadas)."""
    import json
    import os
    if not os.path.exists('shadow_senales.json'):
        return None
    try:
        with open('shadow_senales.json', encoding='utf-8') as f:
            det = json.load(f).get('detalle', {})
        h = nombre_home.replace(' ', '-')
        a = nombre_away.replace(' ', '-')
        for mid, d in det.items():
            if mid.endswith(f'_{h}_{a}'):
                return float(d.get('residuo'))
    except Exception:
        pass
    return None


def comentario_partido(pred: Dict, nombre_home: str, nombre_away: str,
                       cuotas_ev: Optional[List[Dict]] = None,
                       riesgo: str = 'bajo') -> str:
    """Comentario de 2-4 frases desde el dict de predicción del motor."""
    p = pred.get('prediction', pred)
    probs = p.get('probabilities', {})
    ph, pd_, pa = probs.get('home', 0), probs.get('draw', 0), probs.get('away', 0)
    goles = float(p.get('total_goals_expected', 2.5))
    marcador = p.get('most_likely_score', '')
    s = _semilla(nombre_home, nombre_away)
    frases = []

    # 1. lectura del 1X2
    if max(ph, pa) < 0.40 or abs(ph - pa) < 0.06:
        frases.append(_elige([
            f"Partido muy parejo entre {nombre_home} y {nombre_away}: el modelo "
            f"lo ve {ph*100:.0f}-{pd_*100:.0f}-{pa*100:.0f} y el empate "
            f"({pd_*100:.0f} %) no es ninguna locura.",
            f"{nombre_home} y {nombre_away} llegan igualados según el modelo "
            f"({ph*100:.0f} % vs {pa*100:.0f} %): cuidado con jugarse el 1X2 seco.",
        ], s))
    else:
        fav, pfav = (nombre_home, ph) if ph > pa else (nombre_away, pa)
        matiz = ("favorito claro" if pfav >= 0.55 else
                 "favorito, pero sin margen para confiarse")
        frases.append(_elige([
            f"El modelo hace a {fav} {matiz} con un {pfav*100:.0f} % "
            f"(marcador más probable: {marcador}).",
            f"{fav} parte {matiz}: {pfav*100:.0f} % de probabilidad y "
            f"{marcador} como marcador más repetido en la simulación.",
        ], s))

    # 2. ángulo de goles
    if goles >= 2.8:
        frases.append(_elige([
            f"Se esperan {goles:.1f} goles: los mercados de over y BTTS son "
            f"el ángulo natural de este cruce.",
            f"Con {goles:.1f} goles esperados, el partido pinta abierto — "
            f"el over asoma antes que el under.",
        ], s, 1))
    elif goles <= 2.1:
        frases.append(_elige([
            f"El modelo proyecta solo {goles:.1f} goles: partido de candado, "
            f"los unders y el marcador corto ganan enteros.",
            f"Con {goles:.1f} goles esperados, esto huele a partido cerrado — "
            f"piensa en under y en pocos córners de segunda mitad.",
        ], s, 1))

    # 3. valor real (solo con cuotas de mercado)
    if cuotas_ev:
        con_valor = [c for c in cuotas_ev if c.get('ev', 0) > 0.05]
        if con_valor:
            mejor = max(con_valor, key=lambda c: c['ev'])
            frases.append(
                f"Ojo al valor: «{mejor.get('etiqueta', mejor.get('mercado', ''))}» "
                f"paga {mejor.get('cuota', 0):.2f} y el modelo le da EV "
                f"+{mejor['ev']*100:.0f} % — la casa lo está pagando de más.")

    # 4b. abogado del diablo (v27 §6): divergencia modelo base vs Shadow.
    # Determinista — funciona igual sin Ollama; si Ollama está activo, el
    # bloque viaja dentro del comentario y el SLM lo reescribe con él.
    resid = _residuo_shadow(nombre_home, nombre_away)
    if resid is not None:
        conf = max(ph, pa)
        favorece_home = ph > pa
        r_dir = resid if favorece_home else -resid
        if conf > 0.70 and r_dir < -0.05:
            frases.append(
                f"🕵️ Abogado del diablo: el modelo confía un {conf*100:.0f} % "
                f"en su favorito, pero el Shadow Booster detecta al mercado "
                f"moviéndose EN CONTRA (residuo {r_dir:+.2f}). Cuando ambos "
                f"chocan así, la historia dice prudencia: reduce el stake o "
                f"déjala pasar.")
        elif r_dir > 0.05:
            frases.append(
                f"⚡ El Shadow Booster respalda la jugada: el mercado parece "
                f"estar subestimando al favorito del modelo "
                f"(residuo {r_dir:+.2f}).")

    # 4. cautela
    if riesgo == 'alto':
        frases.append("⚠️ Los mercados de predicción divergen fuerte del modelo "
                      "en este partido: si apuestas, hazlo corto.")
    elif pd_ >= 0.30:
        frases.append(_elige([
            f"El empate ({pd_*100:.0f} %) está más vivo de lo que parece: "
            f"la doble oportunidad protege la jugada.",
            f"Con un {pd_*100:.0f} % de empate, cubrirse con doble oportunidad "
            f"no es de cobardes.",
        ], s, 2))

    return ' '.join(frases[:4])


# ---------------------------------------------------------------------------
# Mejora opcional con SLM local (Ollama) — nunca requerida
# ---------------------------------------------------------------------------
def _ollama_disponible() -> bool:
    try:
        import requests
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def mejorar_con_slm(comentario: str) -> Optional[str]:
    """Reescritura opcional con el SLM local. None si no hay Ollama."""
    if not _ollama_disponible():
        return None
    try:
        import requests
        r = requests.post(f'{OLLAMA_URL}/api/generate', json={
            'model': OLLAMA_MODEL, 'stream': False,
            'prompt': ("Reescribe este análisis de apuestas en español, tono "
                       "cercano de analista, máximo 3 frases, SIN inventar "
                       "datos nuevos ni cambiar los números:\n\n" + comentario),
            'options': {'num_predict': 160, 'temperature': 0.6},
        }, timeout=30)
        texto = (r.json().get('response') or '').strip()
        return texto or None
    except Exception as e:
        logger.info(f"Ollama no disponible/falló: {e}")
        return None
