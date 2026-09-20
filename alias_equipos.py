#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v236 — los alias de nombre se DESCUBREN solos, no se escriben a mano.

EL PROBLEMA QUE AUTOMATIZA
--------------------------
La v235 arregló 19 partidos que salían sin tablero porque cada fuente escribe
el nombre en su idioma: ESPN dice «Napoli» y una casa en español «Nápoles»,
«Genoa» contra «Génova», «F.C. København» contra «FC Copenhagen». La tabla que
lo arregló la escribí a mano leyendo los fallos de ESE día, y esa es su ruina:
mañana juega otra liga, salen otros seis nombres y la tabla se queda corta sin
que nadie se entere. El usuario lo dijo: «todo automatizado, nada a mano».

CÓMO SE DESCUBRE SIN INVENTAR
-----------------------------
La tentación es bajar el umbral de parecido y dejar que el emparejador ligue lo
que pueda. Eso es exactamente como se sirve la cuota de OTRO partido, que es el
fallo que costó caro en la v114 —un partido femenino emparejado con uno
masculino, cinco días después y con los bandos al revés—.

Así que un alias sólo se acepta cuando las tres condiciones se cumplen a la vez:

  1. UN LADO CASA EXACTO. Si «Fiorentina» es idéntico en las dos fuentes, el
     partido ya está casi identificado y sólo queda un nombre por resolver. Es
     lo que convierte una adivinanza en una deducción.
  2. EL OTRO LADO SE PARECE MUCHO (>= `MIN_PARECIDO`, 0,82 sobre la cadena
     entera). «napoli» contra «napoles» pasa; «psg» contra «paris saint
     germain» no, y por eso ése sigue escrito a mano.
  3. MISMA FECHA Y MISMA CATEGORÍA. La comprobación la hace el propio
     `_buscar` del emparejador, que es quien sabe de husos y de filiales.

Y ADEMÁS, LO QUE NUNCA SE ACEPTA
--------------------------------
Un candidato cuyo nombre lleve marca de filial o de juvenil —«sub 19», «u19»,
«II», «B»— se descarta aunque cumpla las tres. Son partidos DISTINTOS que se
juegan el mismo día en la misma sede y con nombres casi iguales: el terreno más
fértil que hay para un emparejamiento falso.

QUÉ ESCRIBE, Y QUIÉN LO USA
---------------------------
`alias_equipos.json`, que `cuotas_multi.normalizar` carga y fusiona con su
tabla fija. Cada entrada guarda de dónde salió y con qué parecido, así que el
fichero es auditable: se puede mirar por qué está cada línea.
"""
import datetime as _dt
import difflib
import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger('alias_equipos')

ARTEFACTO = 'alias_equipos.json'
# 0,82 sobre la cadena entera. Por debajo empiezan a entrar nombres de equipos
# distintos de la misma ciudad, que es justo lo que no puede pasar.
MIN_PARECIDO = 0.82
# Un alias con menos de esto de largo es demasiado corto para fiarse: «psv» y
# «psg» se parecen un 0,67 y son dos clubes de dos países.
MIN_LARGO = 5

# Marcas de filial y de juvenil. Un candidato con cualquiera de éstas se
# descarta: son partidos distintos con nombres casi iguales.
_VETO = re.compile(
    r'(^|\s)(sub\s?\d{1,2}|u\s?\d{1,2}|ii|b|reserva|reserves|juvenil|'
    r'youth|academy|fem|femenino|women|w)(\s|$)', re.I)


def _cargar(ruta: Optional[str] = None) -> Dict:
    try:
        r = ruta or ARTEFACTO
        if os.path.exists(r):
            with open(r, encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception as e:
        logger.warning('[alias] no se pudo leer %s: %s', ruta or ARTEFACTO, e)
    return {}


def tabla(ruta: Optional[str] = None) -> Dict[str, str]:
    """`{nombre_de_la_casa: nombre_de_la_fuente}`, listo para el normalizador."""
    doc = _cargar(ruta)
    return {k: v['canonico'] for k, v in (doc.get('alias') or {}).items()
            if isinstance(v, dict) and v.get('canonico')}


def _vetado(nombre: str) -> bool:
    return bool(_VETO.search(str(nombre or '')))


def _parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, str(a), str(b)).ratio()


def detectar(dias: int = 2, deporte: str = 'futbol') -> Dict:
    """Recorre los fixtures y propone alias para los que no casan.

    Devuelve el documento entero, sin escribirlo. Nunca lanza: si una fuente
    falla, se devuelve lo que se haya podido deducir, que es mejor que nada.
    """
    propuestas: Dict[str, Dict] = {}
    revisados = casados = 0
    try:
        import cuotas_multi as cm
        import fixtures_espn as fx
        from config import LEAGUES

        claves = [c for c, cfg in LEAGUES.items()
                  if cfg.get('disponible') and c in fx.ESPN_CODIGOS]
        por_liga = fx.fixtures_multi(claves, dias=dias) or {}
        indice = cm._indice_pdt(deporte) or {}
        # `{nombre_normalizado_de_la_casa}` de los dos bandos de cada entrada,
        # para poder preguntar «¿este lado ya lo conozco?».
        for clave, lista in por_liga.items():
            for f in (lista or []):
                h, a = f.get('home'), f.get('away')
                if not (h and a):
                    continue
                revisados += 1
                if cm._buscar(indice, h, a, deporte, f.get('fecha')) is not None:
                    casados += 1
                    continue
                nh, na = cm.normalizar(h), cm.normalizar(a)
                for llave, ent in indice.items():
                    if '|' not in llave:
                        continue
                    ch, ca = llave.split('|', 1)
                    if _vetado(ent.get('home')) or _vetado(ent.get('away')):
                        continue
                    # (1) un lado EXACTO y (2) el otro muy parecido
                    for propio, casa, otro_propio, otro_casa in (
                            (na, ca, nh, ch), (nh, ch, na, ca)):
                        if otro_propio != otro_casa:
                            continue
                        if propio == casa:
                            continue
                        if len(casa) < MIN_LARGO or len(propio) < MIN_LARGO:
                            continue
                        p = _parecido(propio, casa)
                        if p < MIN_PARECIDO:
                            continue
                        # (3) la fecha y la categoría las valida `_buscar`
                        anterior = propuestas.get(casa)
                        if anterior and anterior['parecido'] >= p:
                            continue
                        propuestas[casa] = {
                            'canonico': propio, 'parecido': round(p, 4),
                            'visto_en': '%s vs %s' % (h, a),
                            'liga': clave,
                            'lado_ancla': otro_propio}
    except Exception as e:
        logger.warning('[alias] detección incompleta: %s: %s',
                       type(e).__name__, e)

    return {'generado': _dt.datetime.now(_dt.timezone.utc)
                           .strftime('%Y-%m-%dT%H:%M:%SZ'),
            'fixtures_revisados': revisados, 'ya_casaban': casados,
            'min_parecido': MIN_PARECIDO, 'alias': propuestas}


def fusionar(nuevo: Dict, ruta: Optional[str] = None) -> Dict:
    """Une lo descubierto con lo que ya había. No borra nunca.

    Un alias deja de verse en cuanto la liga descansa, y borrarlo por eso lo
    haría reaparecer y desaparecer cada semana. Se conserva y se anota cuándo
    se vio por última vez, que es lo que permitiría retirarlo algún día con
    criterio en vez de por ausencia de un día.
    """
    doc = _cargar(ruta)
    viejos = doc.get('alias') or {}
    for k, v in (nuevo.get('alias') or {}).items():
        v = dict(v)
        v['ultima_vez'] = nuevo.get('generado')
        if k in viejos:
            v['primera_vez'] = viejos[k].get('primera_vez') or v['ultima_vez']
        else:
            v['primera_vez'] = v['ultima_vez']
        viejos[k] = v
    nuevo = dict(nuevo)
    nuevo['alias'] = viejos
    return nuevo


def guardar(doc: Dict, ruta: Optional[str] = None) -> bool:
    try:
        with open(ruta or ARTEFACTO, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return True
    except Exception as e:
        logger.warning('[alias] no se pudo escribir: %s', e)
        return False


def actualizar(dias: int = 2, ruta: Optional[str] = None) -> int:
    """Lo que llama el cron. Devuelve cuántos alias hay en total."""
    doc = fusionar(detectar(dias=dias), ruta)
    guardar(doc, ruta)
    n = len(doc.get('alias') or {})
    logger.info('[alias] %d alias conocidos (%d fixtures revisados, %d ya '
                'casaban)', n, doc.get('fixtures_revisados', 0),
                doc.get('ya_casaban', 0))
    return n


def main() -> int:
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    doc = fusionar(detectar())
    guardar(doc)
    al = doc.get('alias') or {}
    print('fixtures revisados: %d · ya casaban: %d · alias conocidos: %d'
          % (doc.get('fixtures_revisados', 0), doc.get('ya_casaban', 0),
             len(al)))
    for k, v in sorted(al.items(), key=lambda kv: -kv[1].get('parecido', 0)):
        print('  %-28s -> %-28s  %.3f   %s'
              % (k, v.get('canonico'), v.get('parecido', 0),
                 v.get('visto_en', '')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
