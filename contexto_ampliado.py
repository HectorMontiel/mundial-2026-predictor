#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Todo el contexto de un partido en un sitio, diciendo qué está medido y qué no.

QUÉ RESUELVE
------------
El usuario cuenta que copia sus apuestas y se las pasa a una IA para que le
cruce lesiones, geografía y noticias. Esto es eso mismo hecho dentro del
sistema, con una diferencia que importa: **cada dato viene con una etiqueta de
si su efecto está medido o sólo se supone.**

LA SEPARACIÓN QUE MANDA
-----------------------
    MEDIDO Y APLICADO     la ACLIMATACIÓN sobre el 1X2. No es que la sede
                          esté alta: es que el VISITANTE SUBE. Medido fuera de
                          muestra en `validar_contexto.py`, sobre los 376
                          partidos del tramo de prueba en que el visitante
                          asciende 1.000 m o más a una sede por encima de
                          2.200:

                              log-loss  0,65712 → 0,64703   (−1,54 %)
                              ECE       0,08142 → 0,05355   (−34 %)

                          Es lo único que toca una probabilidad.

    MEDIDO Y DESCARTADO   la ALTURA BRUTA de la sede sobre el 1X2 (+0,10 %,
                          ruido) y sobre los goles (+0,49 %); la aclimatación
                          sobre «ambos marcan» (+0,57 %) y sobre la escalera
                          de goles (+0,90 %), las dos por debajo del listón;
                          y el descanso, que EMPEORA el log-loss un 0,15 %.
                          Se publican como dato y no corrigen nada.

                          LA ALTURA BRUTA MERECE UNA NOTA APARTE, porque con
                          sólo Bolivia, Ecuador, Colombia y Perú sí parecía
                          funcionar (−1,80 % en «ambos marcan»). Al meter la
                          Liga MX —donde casi toda la liga juega en alto y los
                          dos equipos llegan aclimatados— se cayó. La variable
                          buena nunca fue la altura: era el desnivel.

    NO MEDIBLE            bajas, alineaciones y noticias. Se pueden leer hoy,
                          pero nadie guardó la lista de bajas de un partido de
                          2024, así que no hay contra qué contrastarlas.
                          Salen con `medido: False` y no tocan ninguna
                          probabilidad — mismo trato que `contexto_mercado`.

Por qué tanto cuidado: una variable de contexto sin medir es exactamente el
tipo de cosa que parece que mejora el modelo y lo empeora. El descanso es el
ejemplo de esta misma tanda: la intuición dice que un equipo con tres días
menos rinde peor, la medición dice que corregirlo **sube** el log-loss.
"""

import functools
import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MEDICION = 'modelos/contexto_medido.json'

# La prueba cuyo ajuste se aplica de verdad. Si el JSON dice que no mejora, no
# se aplica: el módulo lee el veredicto, no lo presupone.
VARIABLE_APLICADA = 'sube_visitante'
# Desnivel mínimo, en metros, para considerar que el visitante «sube». Sale de
# la medición, no de la intuición.
DESNIVEL_MINIMO = 1000
PRUEBA_APLICADA = '1x2_aclimatacion'


@functools.lru_cache(maxsize=1)
def medicion(ruta: str = MEDICION) -> Dict:
    """El resultado de `validar_contexto`. Vacío si no está generado."""
    try:
        with open(ruta, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception as e:
        logger.debug('[contexto+] sin medición: %s', e)
        return {}


def _olvidar() -> None:
    medicion.cache_clear()
    ciudad_local.cache_clear()


@functools.lru_cache(maxsize=4096)
def ciudad_local(clave_liga: str, equipo: str) -> Optional[str]:
    """La ciudad donde ese equipo juega en casa, del histórico de su liga.

    Se saca del propio `historico_*.csv` —la sede de sus últimos partidos como
    local— en vez de pedir una tabla de estadios: el dato ya está en disco y
    así no hay una segunda lista que mantener y que se desincronice.
    """
    if not (clave_liga and equipo):
        return None
    import pandas as pd
    d = None
    ruta = f'historico_{clave_liga}.csv'
    if os.path.exists(ruta):
        try:
            d = pd.read_csv(ruta, usecols=['home_team', 'sede_ciudad'])
        except Exception:
            d = None      # la liga no guarda la sede: se prueba el respaldo
    # RESPALDO: `sedes_futbol.csv`, que el proyecto ya tiene.
    #
    # Medido: `historico_laliga.csv` y `historico_liga_mx.csv` NO llevan
    # columna `sede_ciudad`, así que por esa vía la Liga MX entera se quedaba
    # sin altitud — y ahí están Toluca (2.660 m), la Ciudad de México (2.240)
    # y Pachuca (2.400), que es justo donde el efecto existe.
    if d is None or not len(d):
        try:
            d = pd.read_csv('sedes_futbol.csv',
                            usecols=['home_team', 'sede_ciudad'])
        except Exception:
            return None
    d = d.dropna(subset=['sede_ciudad'])
    if not len(d):
        return None
    # EL NOMBRE SE MAPEA, NO SE COMPARA. El barrido llama a los equipos como
    # los llama su fuente y el histórico como los llama ESPN: comparando
    # cadenas, «Bolívar» no encuentra a «Bolivar» y el partido se queda sin
    # sede — o sea sin altitud, que es justo el dato medido. Se usa el mismo
    # `name_mapper` que el resto del proyecto.
    catalogo = sorted(d['home_team'].astype(str).unique())
    nombre = str(equipo)
    if nombre not in catalogo:
        try:
            import name_mapper
            nombre = name_mapper.mapear(
                nombre, catalogo, contexto=f'contexto+→{clave_liga}') or nombre
        except Exception:
            pass
    d = d[d['home_team'].astype(str) == nombre]
    if not len(d):
        return None
    # la más frecuente, no la última: un partido jugado en campo neutral no
    # debe cambiar la sede habitual del equipo
    return str(d['sede_ciudad'].mode().iloc[0])


def altitud_de(ciudad: Optional[str]) -> int:
    try:
        import validar_contexto as vc
        return vc.altitud_de(ciudad)
    except Exception:
        return 0


def ajuste_medido() -> Optional[float]:
    """El desplazamiento del logit que la medición autoriza, o None."""
    p = (medicion().get('pruebas') or {}).get(PRUEBA_APLICADA) or {}
    if not p.get('medido') or not p.get('mejora'):
        return None
    col = (p.get('ajustes') or {}).get(VARIABLE_APLICADA) or {}
    # la clave puede venir como '1.0' o 1.0 según haya pasado por JSON
    for k, v in col.items():
        try:
            if float(k) == 1.0 and float(v) != 0.0:
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def ajustar_1x2(p_home, p_draw, p_away, sube_visitante: bool):
    """El 1X2 corregido cuando el visitante sube a la altura.

    Devuelve `(p_home, p_draw, p_away, aplicado)`. Sin ascenso, o si la
    medición no autoriza el ajuste, salen las tres intactas.

    EL EMPATE Y LA VICTORIA VISITANTE SE REESCALAN, NO SE DEJAN QUIETAS. Si se
    sube la del local y no se toca el resto, las tres dejan de sumar 1 y todo
    lo que cuelga de ahí —la doble oportunidad, que es literalmente su suma—
    empieza a dar probabilidades imposibles.
    """
    import math
    try:
        ph, px, pa = float(p_home), float(p_draw), float(p_away)
    except (TypeError, ValueError):
        return p_home, p_draw, p_away, False
    total = ph + px + pa
    if not sube_visitante or not (0.0 < ph < 1.0) or total <= 0:
        return p_home, p_draw, p_away, False
    d = ajuste_medido()
    if d is None:
        return p_home, p_draw, p_away, False
    ph, px, pa = ph / total, px / total, pa / total
    nuevo_h = 1.0 / (1.0 + math.exp(-(math.log(ph / (1.0 - ph)) + d)))
    resto = px + pa
    if resto <= 0:
        return p_home, p_draw, p_away, False
    k = (1.0 - nuevo_h) / resto
    return nuevo_h, px * k, pa * k, True


def de_partido(clave_liga: str, home: str, away: str,
               dia: Optional[str] = None) -> Dict:
    """El contexto entero del partido, con su etiqueta de medición.

    Nunca lanza: cada bloque que falla sale vacío y marcado. Esto lo consume
    la pantalla dentro del barrido, y una excepción aquí se llevaría la rama
    entera — ha pasado dos veces en este proyecto.
    """
    fuera: Dict = {}

    # --- ALTITUD Y ACLIMATACIÓN: lo único medido que corrige ------------
    ciudad = alt_visitante = None
    try:
        ciudad = ciudad_local(clave_liga, home)
        ciudad_v = ciudad_local(clave_liga, away)
        alt_visitante = altitud_de(ciudad_v)
    except Exception as e:
        logger.debug('[contexto+] sede de %s: %s', home, e)
        ciudad_v, alt_visitante = None, 0
    metros = altitud_de(ciudad)
    corte = int(medicion().get('altitud_corte_m') or 2200)
    en_altura = bool(metros >= corte)
    desnivel = int(metros - (alt_visitante or 0))
    sube = bool(en_altura and desnivel >= DESNIVEL_MINIMO)
    fuera['altitud'] = {
        'ciudad': ciudad, 'metros': metros,
        'ciudad_visitante': ciudad_v, 'metros_visitante': alt_visitante or 0,
        'desnivel': desnivel, 'en_altura': en_altura,
        'sube_visitante': sube,
        'medido': ajuste_medido() is not None,
        'aplica_a': '1X2 y doble oportunidad' if sube else '',
        'nota': (f'El visitante sube {desnivel} m. Medido fuera de muestra, '
                 f'corregir el 1X2 por eso baja el log-loss un 1,54 % y el '
                 f'error de calibración un 34 % en estos partidos.'
                 if sube else
                 ('Sede en altura, pero el visitante también juega alto: '
                  'medido, ahí no hay efecto que corregir.'
                  if en_altura else '')),
    }

    # --- DESCANSO: medido y DESCARTADO ----------------------------------
    #
    # Se publica porque es información real del partido, y se dice que no
    # corrige: medido, ajustar por diferencia de descanso SUBE el log-loss
    # un 0,15 %. La intuición dice lo contrario y la intuición se equivoca.
    fuera['descanso'] = {
        'medido': False,
        'motivo': 'medido y descartado: corregir por descanso empeora el '
                  'log-loss un 0,15 % fuera de muestra',
    }

    # --- BAJAS Y ALINEACIÓN: no medible ---------------------------------
    fuera['bajas'] = {
        'medido': False,
        'motivo': 'nadie guardó la lista de bajas de los partidos pasados, '
                  'así que su efecto no se puede contrastar contra el '
                  'histórico',
        'fuente': 'FotMob (once, suplentes, formación y bajas)',
    }

    # --- ENTRENADOR: hay fuente con fecha, el EFECTO sigue sin medirse ---
    try:
        import filtro_contexto as fc
        info = fc.rebote_entrenador(home, away, dia or '',
                                    cuota_favorito=None, lado_favorito='')
        fuera['entrenador'] = {
            'medido': False,
            'hay_fuente': fc.hay_fuente(),
            'activo': bool(info.get('activo')),
            'motivo': 'Wikidata da la fecha de nombramiento, pero el TAMAÑO '
                      'del efecto rebote no se ha medido nunca en este '
                      'proyecto',
        }
    except Exception as e:
        logger.debug('[contexto+] entrenador: %s', e)
        fuera['entrenador'] = {'medido': False, 'hay_fuente': False}

    return fuera


def resumen(ficha: Dict) -> str:
    """Una línea para la pantalla. Vacía si no hay nada que decir."""
    trozos = []
    alt = (ficha or {}).get('altitud') or {}
    if alt.get('sube_visitante'):
        trozos.append(f"⛰️ el visitante sube {alt.get('desnivel')} m a "
                      f"{alt.get('ciudad')}"
                      + (' · corregido' if alt.get('medido') else ''))
    elif alt.get('en_altura'):
        trozos.append(f"⛰️ {alt.get('ciudad')} a {alt.get('metros')} m "
                      f"(los dos equipos aclimatados)")
    ent = (ficha or {}).get('entrenador') or {}
    if ent.get('activo'):
        trozos.append('🔄 entrenador nuevo en el rival')
    return ' · '.join(trozos)
