#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cuotas manuales (v63) — el usuario PEGA las cuotas de su casa y la app las
parsea, las cruza con la plantilla del modelo y calcula el EV de cada mercado.

## Por qué esta vía y no un scraper

Se auditó el scraping directo de la casa (Playdoit) y NO es viable ni adecuado:
  · el HTML de la ficha trae solo los NOMBRES de mercado; los acordeones están
    colapsados y las cuotas se cargan al expandir cada uno;
  · el sitio está tras Cloudflare (devuelve cuerpo vacío a clientes no-navegador);
  · las clases son hashes de styled-components (`sc-43347967-4`) que cambian en
    cada despliegue de su frontend;
  · automatizarlo exigiría evadir protección anti-bot, lo que va contra sus
    términos y contra la regla del proyecto ("sin scraping agresivo").

La vía manual conserva TODO el valor (cuotas reales de cualquier mercado y de
cualquier casa) sin ninguno de esos problemas: el usuario ya consulta la página;
aquí solo se estructura lo que copia.

## Qué acepta

Es deliberadamente tolerante, porque cada casa copia de forma distinta:
  · texto plano por líneas:   «Más de 2.5   1.85»
  · con separadores:          «Ambos marcan: Sí | 1.72»
  · HTML pegado del inspector (se extrae el texto y se aplica lo anterior)
  · cuota americana (+150 / -110) o decimal (1.85) — se normaliza a decimal.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ARCHIVO = 'cuotas_manuales.json'

# Una cuota decimal razonable de casa: 1.01 a 1000. Se usa para no confundir
# la cuota con la línea del mercado ("Más de 2.5" -> 2.5 NO es la cuota).
CUOTA_MIN, CUOTA_MAX = 1.01, 1000.0
_RE_AMERICANA = re.compile(r'^[+-]\d{3,5}$')
_RE_DECIMAL = re.compile(r'^\d{1,4}[.,]\d{1,3}$|^\d{1,4}$')
# Palabras tras las que un número es la LÍNEA del mercado, no la cuota:
# «Menos de 2.5», «Over 8.5», «Hándicap -1.5»...
_ANTES_DE_LINEA = {'de', 'over', 'under', 'mas', 'menos', 'handicap',
                   'total', 'linea', '+', '-'}


def _a_decimal(token: str) -> Optional[float]:
    """Convierte un token a cuota decimal. Acepta americana y decimal."""
    t = token.strip().replace(',', '.')
    if _RE_AMERICANA.match(t):
        ml = float(t)
        return round(1 + ml / 100, 3) if ml > 0 else round(1 + 100 / abs(ml), 3)
    if _RE_DECIMAL.match(t):
        try:
            v = float(t)
        except ValueError:
            return None
        if CUOTA_MIN <= v <= CUOTA_MAX:
            return round(v, 3)
    return None


def _texto_de_html(bruto: str) -> str:
    """Si lo pegado es HTML, devuelve solo el texto visible (un item por línea)."""
    if '<' not in bruto or '>' not in bruto:
        return bruto
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(bruto, 'lxml')
        for tag in soup(['script', 'style', 'svg']):
            tag.decompose()
        # cada nodo con texto propio en su línea → conserva la relación
        # etiqueta-cuota que la casa muestra visualmente
        partes = [t.strip() for t in soup.stripped_strings]
        return '\n'.join(partes)
    except Exception as e:
        logger.warning(f"[cuotas_manual] HTML no parseable ({e}); se usa en crudo.")
        return re.sub(r'<[^>]+>', '\n', bruto)


def parsear(bruto: str) -> List[Dict]:
    """Extrae [{'etiqueta','cuota'}] de lo pegado. Empareja cada cuota con el
    texto NO numérico que la precede (así funciona tanto si vienen en la misma
    línea como en líneas consecutivas, que es como copia la mayoría de casas)."""
    texto = _texto_de_html(bruto)
    salida: List[Dict] = []
    etiqueta_pendiente = ''
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        # ¿la línea termina en una cuota? («Más de 2.5   1.85»)
        tokens = linea.split()
        cuota = _a_decimal(tokens[-1]) if tokens else None
        # OJO: en «Menos de 2.5» el 2.5 es la LÍNEA del mercado, no la cuota.
        # Se detecta por la palabra que la precede (de/over/under/±).
        if cuota is not None and len(tokens) > 1 and \
                _normalizar(tokens[-2]) in _ANTES_DE_LINEA:
            etiqueta_pendiente = linea.strip(' :|-\t')
            continue
        if cuota is not None and len(tokens) > 1:
            etiqueta = ' '.join(tokens[:-1]).strip(' :|-\t')
            if etiqueta:
                salida.append({'etiqueta': etiqueta, 'cuota': cuota})
                etiqueta_pendiente = ''
                continue
        # ¿la línea es SOLO una cuota? -> se asocia a la etiqueta anterior
        if cuota is not None and len(tokens) == 1:
            if etiqueta_pendiente:
                salida.append({'etiqueta': etiqueta_pendiente, 'cuota': cuota})
                etiqueta_pendiente = ''
            continue
        # línea de texto: candidata a etiqueta del siguiente número
        etiqueta_pendiente = linea.strip(' :|-\t')
    return salida


def _normalizar(s: str) -> str:
    import re
    import unicodedata
    n = unicodedata.normalize('NFKD', str(s))
    n = ''.join(c for c in n if not unicodedata.combining(c)).lower()
    # v123 — FUERA LA CUOTA AMERICANA QUE LA PLANTILLA PEGA A LA ETIQUETA.
    #
    # El modelo escribe «Empate (+269)», «Gana Monterrey (-121)» o «Monterrey
    # 1-1 Juarez (+707)»: el paréntesis es una cortesía para el lector, no
    # parte del nombre del mercado. Para el comparador de cadenas sí lo era, y
    # eso costaba el mercado más jugado que hay:
    #
    #     «Empate» contra «Empate (+269)»  →  «empate» vs «empate 269»
    #     similitud 0,75, por debajo del listón de 0,80  →  SIN CRUCE
    #
    # Resultado en producción desde la v114: el empate no recibía nunca su
    # precio real y toda combinada que lo incluyera iba con cuota justa, que es
    # un precio inventado. Se quitan SÓLO los paréntesis cuyo contenido es un
    # número con signo, así que «(no pierde)», «(BTTS)» o «(top 8)» siguen
    # contando para el cotejo.
    n = re.sub(r'\(\s*[+-]?\d+(?:[.,]\d+)?\s*\)', ' ', n)
    for ch in '.:|-–—()':
        n = n.replace(ch, ' ')
    return ' '.join(n.split())


def cruzar_con_plantilla(pegado: List[Dict], pl: Dict,
                         umbral: float = 0.80) -> List[Dict]:
    """Empareja cada cuota pegada con el mercado equivalente de la plantilla del
    modelo y calcula el EV. Devuelve las coincidencias ordenadas por EV.

    El EV aquí es ACCIONABLE: usa la cuota REAL de la casa contra la
    probabilidad del modelo (EV = cuota × prob − 1)."""
    from difflib import SequenceMatcher
    campos = []
    for sec in pl.get('secciones', []):
        for c in sec.get('campos', []):
            if c.get('tipo', 'pct') != 'pct':
                continue
            try:
                prob = float(c['valor']) / 100.0
            except (TypeError, ValueError):
                continue
            if 0.0 < prob < 1.0:
                campos.append({'id': c['id'], 'etiqueta': c['etiqueta'],
                               'prob': prob, 'seccion': sec.get('titulo', ''),
                               'norm': _normalizar(c['etiqueta'])})
    resultados = []
    for p in pegado:
        objetivo = _normalizar(p['etiqueta'])
        mejor, ratio = None, 0.0
        for c in campos:
            r = SequenceMatcher(None, objetivo, c['norm']).ratio()
            if r > ratio:
                mejor, ratio = c, r
        if not mejor or ratio < umbral:
            continue
        ev = p['cuota'] * mejor['prob'] - 1.0
        resultados.append({
            'mercado': mejor['seccion'], 'apuesta': mejor['etiqueta'],
            'id': mejor['id'], 'prob': round(mejor['prob'], 3),
            'cuota_casa': p['cuota'],
            'cuota_justa': round(1 / max(mejor['prob'], 1e-6), 2),
            'ev': round(ev, 4), 'similitud': round(ratio, 2),
            'texto_pegado': p['etiqueta'],
        })
    resultados.sort(key=lambda r: -r['ev'])
    return resultados


def guardar(partido: str, casa: str, filas: List[Dict]) -> None:
    """Persiste las cuotas cruzadas (histórico para CLV y auditoría)."""
    import json
    import os
    import datetime
    datos = {}
    if os.path.exists(ARCHIVO):
        try:
            with open(ARCHIVO, encoding='utf-8') as f:
                datos = json.load(f)
        except Exception:
            datos = {}
    datos.setdefault(partido, []).append({
        'casa': casa, 'capturado': datetime.datetime.now().isoformat(timespec='seconds'),
        'mercados': filas,
    })
    try:
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.warning(f"[cuotas_manual] no se pudo guardar: {e}")


if __name__ == '__main__':
    demo = """Resultado Final
Atlante FC  2.55
Empate      3.10
América     2.60
Total
Más de 2.5  1.85
Menos de 2.5
1.95
Ambos equipos marcan: Sí | 1.72
"""
    for f in parsear(demo):
        print(f"  {f['etiqueta']:32} -> {f['cuota']}")
