#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v129 — Cuántos bateadores enfrenta un abridor, contado de sus APERTURAS.

Qué arregla
-----------
`beisbol_pitchers._bf_por_apertura` estima los bateadores por salida como
`BF_temporada / aperturas`. Ese cociente mezcla dos papeles en cuanto el
lanzador abre unos días y releva otros, y entonces da un disparate:

    Drew Anderson (DET), 11/08/2026:  289 BF / 3 aperturas = 96,3

La guarda de la v115 lo detecta (tope de 28,5) y cae a la MEDIA DE LA LIGA,
23,5 bateadores. Sus aperturas reales promediaban **14,33**. Con un k/BF de
0,27 esos nueve bateadores de más son 2,4 ponches de más, y así una línea de
«más de 5.5» salía al 60 % cuando el lanzador acabó con 4.

El arreglo no es una guarda mejor: es no necesitar guarda. El `gameLog` de
MLB StatsAPI marca `gamesStarted` partido a partido, así que las aperturas se
pueden separar EN EL ORIGEN en vez de adivinarlas desde un agregado.

Lo que está medido, y lo que se descartó
----------------------------------------
Backtest fuera de muestra, en orden cronológico —cada apertura estimada sólo
con lo anterior a ella— sobre dos temporadas completas:

    temporada   aperturas   mejora de MAE      p5 bootstrap
    2025          4.045        +0,0146           +0,0085
    2026          2.972        +0,0367           +0,0260

Y en el subgrupo donde está el problema, los que alternan abrir y relevar:

    temporada   n     sesgo hoy   sesgo aquí   mejora      p5
    2025       115      +0,866      +0,471     +0,148    +0,0855
    2026       160      +1,376      +0,762     +0,345    +0,2527

En abridores puros el cambio es de +0,0088 y +0,0064: esto es cirugía sobre
un 3-5 % de las aperturas, no una reforma del modelo.

SE PROBÓ Y SE DESCARTÓ un segundo ajuste: encoger hacia un ancla propia del
papel (17,0 bateadores para quien alterna) en vez de hacia la media de la
liga. En 2026 parecía mucho mejor —dejaba el sesgo del subgrupo en −0,02—
pero su aportación propia sobre este módulo, medida en 2025, tiene **p5
−0,0523**: funcionaba en la temporada con la que se eligió y no en la otra.
Es el patrón que este proyecto ya pagó caro, así que se queda fuera hasta que
haya una tercera temporada que lo respalde.

Lo que esto NO arregla
----------------------
Con este módulo, la apertura de Drew Anderson del 11/08 baja al 46,7 % y se
descarta; la del 05/08 se queda en el 59,5 % y se emitiría igual, y acabó en
CERO ponches. El estimador que atrapaba las dos es el que no valida. Menos
bonito y es lo que sostiene la medición.
"""
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

API = 'https://statsapi.mlb.com/api/v1'
TTL = 6 * 3600
TIMEOUT = 20

# Mínimo de aperturas propias para que la media diga algo. Con una sola no hay
# media que valga: el encogimiento la absorbería casi entera y, sobre todo, una
# apertura puede ser un día raro. El backtest exigió dos.
MIN_APERTURAS = 2

_MEM: Dict[tuple, tuple] = {}


def _get(url: str, params: Dict) -> Dict:
    try:
        import requests
    except Exception:
        return {}
    for _ in range(2):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return {}


def aperturas(pid, temporada: int, hasta: Optional[str] = None) -> List[Dict]:
    """
    Las APERTURAS de ese lanzador en esa temporada, en orden.

    `hasta` (ISO `YYYY-MM-DD`) recorta a lo anterior a esa fecha, que es lo que
    permite reproducir el backtest sin mirar el resultado que se juzga. En
    producción se deja vacío.

    Devuelve [] si la API no responde o el lanzador no tiene registros: quien
    llame decide, y `beisbol_pitchers` se queda con su estimación de siempre.
    """
    clave = (str(pid), int(temporada))
    hit = _MEM.get(clave)
    if hit and (time.time() - hit[0]) < TTL:
        filas = hit[1]
    else:
        j = _get(f'{API}/people/{pid}/stats',
                 {'stats': 'gameLog', 'group': 'pitching',
                  'season': int(temporada)})
        filas = []
        for bloque in (j.get('stats') or []):
            for s in (bloque.get('splits') or []):
                st = s.get('stat') or {}
                try:
                    if int(st.get('gamesStarted') or 0) != 1:
                        continue
                    filas.append({'fecha': s.get('date'),
                                  'bf': int(st.get('battersFaced') or 0),
                                  'k': int(st.get('strikeOuts') or 0),
                                  'ip': float(st.get('inningsPitched') or 0)})
                except (TypeError, ValueError):
                    continue
        filas.sort(key=lambda x: str(x.get('fecha') or ''))
        if filas or j:
            _MEM[clave] = (time.time(), filas)
    if hasta:
        filas = [f for f in filas if str(f.get('fecha') or '') < str(hasta)]
    return [f for f in filas if f.get('bf', 0) > 0]


def bf_por_apertura(pid, temporada: int, liga_media: float = 23.5,
                    previas: float = 6.0,
                    hasta: Optional[str] = None) -> Optional[Dict]:
    """
    Bateadores que este abridor enfrenta por salida, contados de sus aperturas.

    El encogimiento hacia `liga_media` con `previas` aperturas ficticias es el
    MISMO esquema que ya usaba `beisbol_pitchers._bf_por_apertura`: lo único
    que cambia es de dónde sale el dato propio. Se conserva porque tres
    aperturas siguen sin definir a nadie, y porque el barrido del ancla mostró
    que la mejora aguanta en toda la vecindad (7 de 7 valores probados), o sea
    que no depende de haber acertado con el número.

    Devuelve `None` cuando no hay material — sin datos, quien llama se queda
    con lo de siempre. Nunca un valor inventado que parezca medido.
    """
    try:
        ap = aperturas(pid, temporada, hasta)
    except Exception as e:
        logger.debug(f'[ponches] gameLog de {pid} no disponible: '
                     f'{type(e).__name__}: {e}')
        return None
    if len(ap) < MIN_APERTURAS:
        return None
    n = len(ap)
    propio = sum(a['bf'] for a in ap) / n
    ajustado = ((propio * n) + (float(liga_media) * float(previas))) \
        / (n + float(previas))
    return {'bf': round(float(ajustado), 2),
            'bf_propio': round(float(propio), 2),
            'n_aperturas': n,
            'ip_media': round(sum(a['ip'] for a in ap) / n, 2),
            'fuente': 'aperturas reales (gameLog)'}


def anotar_perfil(perfil: Dict, temporada: Optional[int] = None,
                  liga_media: float = 23.5, previas: float = 6.0,
                  hasta: Optional[str] = None) -> Dict:
    """
    Sustituye `bf_apertura` en un perfil de `beisbol_pitchers.perfil_pitcher`.

    Deja constancia de lo que había (`bf_apertura_agregado`) y de cuánto se ha
    movido, para que la diferencia se pueda auditar desde fuera en vez de
    aparecer un número distinto sin explicación.
    """
    if not perfil or not perfil.get('pitcher'):
        return perfil
    anio = temporada
    if anio is None:
        temporadas = perfil.get('temporadas') or []
        anio = max(temporadas) if temporadas else None
    if anio is None:
        return perfil
    ctx = bf_por_apertura(perfil['pitcher'], anio, liga_media, previas, hasta)
    if not ctx:
        return perfil
    salida = dict(perfil)
    salida['bf_apertura_agregado'] = perfil.get('bf_apertura')
    salida['bf_apertura'] = ctx['bf']
    salida['contexto_bf'] = ctx
    try:
        salida['bf_apertura_delta'] = round(
            float(ctx['bf']) - float(perfil.get('bf_apertura') or 0), 2)
    except (TypeError, ValueError):
        pass
    return salida


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import json
    import sys
    pid = sys.argv[1] if len(sys.argv) > 1 else '623454'
    temp = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    hasta = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps(bf_por_apertura(pid, temp, hasta=hasta),
                     ensure_ascii=False, indent=1))
