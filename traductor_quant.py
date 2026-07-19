#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Traductor Quant (v28 §4): jerga técnica → lenguaje llano, sin LLM.

Se engancha al modo Principiante/Pro que existe desde v14 (sidebar). Base
100 % determinista; si Ollama está activo, asistente_comentarios ya
reescribe los textos (v22) — el traductor no depende de él.
"""

from typing import Dict, Optional

# término backend -> (etiqueta principiante, tooltip)
GLOSARIO: Dict[str, tuple] = {
    'evc_platino': ('Apuesta Estrella ⭐',
                    'La recomendación más segura del día, validada por tres '
                    'filtros matemáticos independientes.'),
    'evc': ('Apuesta Doblemente Verificada ✅',
            'El modelo y el detector de movimientos del mercado están de '
            'acuerdo en que hay valor.'),
    'shadow': ('Alerta del Mercado 🚨',
               'Detectamos que las casas de apuestas están reaccionando '
               'exageradamente a noticias recientes.'),
    'vaca': ('Nivel de Estabilidad ⚖️',
             'Mide qué tan impredecibles suelen ser los partidos de estos '
             'dos equipos: más alto = oportunidad más estable.'),
    'arbitraje': ('Cuota Desajustada 🎯',
                  'La casa de apuestas ha calculado mal el premio de esta '
                  'combinación.'),
    'ev': ('Ventaja Matemática 📈',
           'Si apostaras a esto 100 veces, este es el porcentaje de ganancia '
           'que obtendrías a largo plazo.'),
    'kelly': ('Gestión de Banca Inteligente 💼',
              'Calcula cuánto apostar para maximizar ganancias y minimizar '
              'el riesgo de arruinarte.'),
    'walk_forward': ('Prueba de Fuego Histórica 🔥',
                     'Hemos probado esta estrategia en miles de partidos '
                     'pasados para verificar que funciona.'),
}

TECNICO: Dict[str, str] = {
    'evc_platino': 'EVC Platino ⭐', 'evc': '💎 EVC (doble validación)',
    'shadow': 'Shadow Booster ⚡', 'vaca': 'VACA (ν)',
    'arbitraje': 'Arbitraje de mercado cruzado', 'ev': 'EV',
    'kelly': 'Kelly simultáneo ⅛ + cap 20 %', 'walk_forward': 'walk-forward',
}


def t(clave: str, experto: bool) -> str:
    """Etiqueta según el modo."""
    if experto:
        return TECNICO.get(clave, clave)
    return GLOSARIO.get(clave, (clave,))[0]


def tooltip(clave: str) -> Optional[str]:
    par = GLOSARIO.get(clave)
    return par[1] if par else None


def frase_estrella(equipo: str, prob_modelo: float, prob_casa: float) -> str:
    """Plantilla determinista de la Apuesta Estrella (spec §4.3)."""
    ventaja = (prob_modelo - prob_casa) * 100
    return (f"El sistema ha encontrado una oportunidad excepcional: "
            f"{equipo} tiene un {prob_modelo*100:.0f} % de probabilidades "
            f"según nuestro análisis, pero las casas pagan como si solo "
            f"tuviera un {prob_casa*100:.0f} %. Eso nos da una ventaja del "
            f"{ventaja:.0f} %.")
