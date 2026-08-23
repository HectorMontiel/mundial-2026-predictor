#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v164 — LA LÍNEA DE LA CASA PARA LOS REMATES DE CADA JUGADOR.

Lo que se buscaba, y dónde estaba
---------------------------------
Hacía falta el «Más de 1,5 remates (Fulano)» de la casa para poder decir qué
probabilidad le da el modelo a ESA línea, no a una inventada. El encargo daba
libertad para irse a buscar APIs de pago; no hizo falta: **Playdoit ya lo
publica**, y el proyecto lo estaba tirando.

Medido sobre 8 partidos de cinco competiciones
(`_v164_sondeo_mercados_jugador.py`): de 13.769 familias distintas,

    Remates - <Jugador> (<COD>) ............  317
    Remates a Puerta - <Jugador> (<COD>) ...  317

o sea unas 80 familias por partido, con tres líneas cada una:

    Remates - Yasin Abbas Ayari (BHA)   sv=2.5|ws:player:6312
        Más de 0.5 @ 1,0715 · Más de 1.5 @ 1,5455 · Más de 2.5 @ 2,7143

Se sabía que Playdoit servía mercados de jugador —`snapshots_tarjetas` los
descarta a propósito con su filtro `_DE_JUGADOR`— pero nadie había mirado si
entre ellos estaban los de remates. Estaban.

EL COSTE, QUE ES LO QUE DECIDE DÓNDE VA CADA COSA
--------------------------------------------------
`cuotas_multi.mercados_playdoit` cachea el tablero normalizado en disco con TTL
de 30 minutos, así que una segunda lectura cuesta 0,04 s. La PRIMERA es una
petición HTTP de 250-320 KB. Y medido tras un render completo, sólo 19 de los
~156 partidos del día tenían su tablero en disco: el barrido no los pide todos.

Así que aquí se aplica la misma disciplina que ya costó dos regresiones en la
v163 (el roster que salía a ESPN desde la tarjeta, 383 s; la alineación que
pedía a FotMob por partido):

    · la TARJETA lee del precálculo del día y NADA MÁS. Cero peticiones.
    · la FICHA puede pedir en vivo: se abre de una en una.
    · el BOT precalcula `lineas_jugador_dia.json`, como ya hace con
      `arbitros_dia.json` y `alineaciones_dia.json`.

LO QUE NO SE HACE: RELLENAR UNA LÍNEA QUE NO EXISTE
----------------------------------------------------
Si la casa no cotiza a un jugador, no se enseña un porcentaje. No es lo mismo
que un 0 %, y tampoco vale coger la línea de otro jugador «parecido». Se dice
«línea no disponible», que es la verdad y es lo que se pidió.
"""
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional

logger = logging.getLogger('lineas_jugador')

FICHERO = 'lineas_jugador_dia.json'

# «Remates - Ollie Watkins (AVL)» / «Remates a Puerta - Pascal Gross (BHA)».
# El código de equipo entre paréntesis es el que dice de qué lado juega, y por
# eso se captura: sin él, dos jugadores homónimos de los dos equipos serían
# indistinguibles.
_FAMILIA = re.compile(
    r'^Remates(?P<puerta>\s+a\s+Puerta)?\s*-\s*(?P<jugador>.+?)\s*'
    r'\((?P<equipo>[A-ZÁÉÍÓÚÑ]{2,4})\)\s*$', re.I)
# «Más de 1.5» / «Menos de 2.5»
_SELECCION = re.compile(r'^(?P<lado>M[áa]s|Menos)\s+de\s+(?P<linea>\d+(?:\.\d+)?)',
                        re.I)

_MEM: Dict[str, Optional[Dict]] = {}
_DISCO: Optional[Dict] = None


def _linea(texto: str) -> Optional[float]:
    m = _SELECCION.match(str(texto or '').strip())
    if not m:
        return None
    try:
        return float(m.group('linea'))
    except (TypeError, ValueError):
        return None


CUOTA_EQUILIBRADA = 2.0


def _linea_principal(sv, lineas: Optional[Dict[float, float]] = None):
    """
    La línea que se enseña: la más EQUILIBRADA de las que cotiza la casa.

    NO ES `sv`, Y ESO SE MIDIÓ. `sv` llega como `'2.5|ws:player:6312'` y parecía
    la línea principal del mercado. No lo es: sobre 432 mercados de jugador de
    seis partidos, `sv` cae en cualquier punto de la escalera —145 veces en la
    primera de dos, 133 en la segunda, y repartido por igual en las de tres— y
    la cuota de esa línea tiene **mediana 2,60**, con casos de hasta 20,00.

    Una línea principal de verdad ronda la cuota 1,90: es donde la casa parte
    su opinión por la mitad. Con `sv` se enseñaban cosas como «José Manuel
    López 5 % de +4.5», que es cierto y no dice nada — la línea que a nadie le
    interesa.

    Así que se elige la de cuota más cercana a 2,00. Es la que expresa lo que
    la casa de verdad espera del jugador, y se elige SIN mirar nuestro modelo:
    coger la línea que más se pareciera a nuestra lambda sería enseñar el
    número que mejor nos deja.

    `sv` se conserva como desempate, que para eso viene.
    """
    esperada = None
    if sv is not None:
        try:
            esperada = float(str(sv).split('|', 1)[0])
        except (TypeError, ValueError):
            esperada = None
    if not lineas:
        return esperada
    return min(lineas,
               key=lambda L: (abs(float(lineas[L]) - CUOTA_EQUILIBRADA),
                              0 if L == esperada else 1, L))


def del_tablero(tablero: Optional[Dict]) -> Dict[str, Dict]:
    """
    Las líneas de remates por jugador de un tablero ya descargado.

    Devuelve `{nombre: {'equipo', 'tot': {...}, 'on': {...}}}`, y cada mercado
    es `{'principal': 1.5, 'lineas': {0.5: cuota, 1.5: cuota, 2.5: cuota}}`.
    """
    salida: Dict[str, Dict] = {}
    for fam in ((tablero or {}).get('mercados') or []):
        if not isinstance(fam, dict):
            continue
        m = _FAMILIA.match(str(fam.get('nombre') or ''))
        if not m:
            continue
        objetivo = 'on' if m.group('puerta') else 'tot'
        jugador = m.group('jugador').strip()
        lineas: Dict[float, float] = {}
        for sel in (fam.get('selecciones') or []):
            if not isinstance(sel, dict):
                continue
            # sólo el lado «Más de»: es el que se enseña y el que el modelo
            # calcula. El «Menos de» es su complemento y guardarlo duplicaría
            # el fichero sin añadir nada.
            texto = str(sel.get('nombre') or '')
            if not texto.lower().startswith('m'):
                continue
            if not re.match(r'^m[áa]s\s+de', texto, re.I):
                continue
            L = _linea(texto)
            try:
                cuota = float(sel.get('cuota'))
            except (TypeError, ValueError):
                continue
            if L is None or cuota <= 1.0:
                continue
            lineas[L] = round(cuota, 4)
        if not lineas:
            continue
        principal = _linea_principal(fam.get('sv'), lineas)
        if principal not in lineas:
            ordenadas = sorted(lineas)
            principal = ordenadas[len(ordenadas) // 2]
        ficha = salida.setdefault(jugador, {'equipo': m.group('equipo')})
        ficha[objetivo] = {'principal': principal,
                           'cuota': lineas.get(principal),
                           'lineas': {str(k): v for k, v in
                                      sorted(lineas.items())}}
    return salida


# Qué se GUARDA en el fichero del día, que no es todo lo que se extrae.
_CAMPOS_GUARDADOS = ('principal', 'cuota')


def _compacta(ficha: Dict) -> Dict:
    """
    La ficha de un jugador recortada a lo que la tarjeta necesita.

    Se tira la escalera entera de líneas y se queda la PRINCIPAL con su cuota.
    Medido: el fichero del día pasa de 968 KB a una fracción, y se commitea
    todos los días — el proyecto ya arrastra un `.git` de 15 GB por no haber
    hecho esta cuenta antes.

    No se pierde nada recuperable: la ficha del partido baja el tablero en vivo
    y tiene la escalera completa, y el histórico de precios es justo lo que
    `snapshots_remates.csv` existe para acumular.
    """
    salida = {k: v for k, v in ficha.items() if k not in ('tot', 'on')}
    for obj in ('tot', 'on'):
        b = ficha.get(obj)
        if isinstance(b, dict) and b.get('principal') is not None:
            salida[obj] = {k: b.get(k) for k in _CAMPOS_GUARDADOS}
    return salida


# ---------------------------------------------------------------------------
# de dónde salen: el precálculo del día, o la red si se autoriza
# ---------------------------------------------------------------------------
def cargar(ruta: str = FICHERO, recargar: bool = False) -> Dict:
    """Lo que dejó el bot. `{}` si no está, sin protestar."""
    global _DISCO
    if _DISCO is not None and not recargar:
        return _DISCO
    datos: Dict = {}
    try:
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                datos = json.load(f) or {}
    except Exception as e:
        logger.debug('[lineas_jugador] no se pudo leer %s: %s', ruta, e)
    _DISCO = datos
    return datos


def _llave(home: str, away: str) -> str:
    import unicodedata
    def _n(x):
        x = unicodedata.normalize('NFKD', str(x or ''))
        return ''.join(c for c in x if not unicodedata.combining(c)).lower().strip()
    return '%s|%s' % (_n(home), _n(away))


def del_partido(home: str, away: str,
                permitir_red: bool = False) -> Dict[str, Dict]:
    """
    Las líneas de este partido: del precálculo, o de la casa si se autoriza.

    `permitir_red=False` (la tarjeta) NO hace ni una petición. Es el mismo
    contrato que `remates_jugador.alineacion`, y por el mismo motivo medido:
    sesenta partidos por una descarga de 300 KB cada uno no caben en una
    pantalla que ya tarda 160 s.
    """
    ck = '%s|%s' % (_llave(home, away), permitir_red)
    if ck in _MEM:
        return _MEM[ck] or {}
    guardado = (cargar().get('partidos') or {}).get(_llave(home, away))
    salida = dict(guardado) if guardado else {}
    if not salida and permitir_red:
        try:
            import cuotas_multi as cm
            salida = del_tablero(cm.mercados_playdoit('futbol', home, away))
        except Exception as e:
            logger.debug('[lineas_jugador] %s-%s: %s', home, away, e)
            salida = {}
    _MEM[ck] = salida
    return salida


def _normaliza_persona(s) -> str:
    """Minúsculas, sin tildes y sin la puntuación de los nombres compuestos."""
    import unicodedata
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    for ch in ".,'-":
        s = s.replace(ch, ' ')
    return ' '.join(s.split())


def por_apellidos(jugador: str, catalogo: List[str]) -> Optional[str]:
    """
    Empareja nombres de PERSONA, que no se comportan como los de club.

    `name_mapper` está afinado para equipos y sobre personas se queda corto:

        ESPN      «Diego Gómez»
        Playdoit  «Diego Alexander Gomez Amarilla»

    Ahí la contención no ayuda —«diego gomez» no es subcadena de la otra— y la
    similitud de cadenas da 0,5, por debajo del umbral de 0,78. El jugador
    salía sin línea aunque la casa sí lo cotizaba.

    La regla: **todas las palabras del nombre corto tienen que estar en el
    largo, y la última —el apellido con el que se le llama— también**. Se exige
    el apellido además de la inclusión porque un nombre de pila suelto lo
    comparten varios jugadores del mismo partido. Y si casan DOS candidatos, no
    se elige ninguno: ese es justo el caso en el que adivinar sale caro.

    Como compara CONJUNTOS de palabras, aguanta el orden invertido —«Lee
    Kang-In» contra «Kang-in Lee»—, que es lo que hacen las fuentes con los
    nombres coreanos.

    MEDIDO (`_v164_emparejar_lineas.py`) sobre 422 jugadores de 8 partidos: el
    emparejado pasa de 224 a 243 (del 53 % al 58 %) y los 19 que gana son
    todos correctos. El 42 % que sigue sin línea NO es un fallo: la casa cotiza
    unos 40 jugadores por partido y ESPN devuelve ~55, así que la mayoría
    simplemente no está cotizada.

    Vive aquí y no en `name_mapper` a propósito: aplicarla a clubes movería
    emparejados que están medidos y cerrados.
    """
    obj = _normaliza_persona(jugador)
    if not obj:
        return None
    t_obj = obj.split()
    candidatos = []
    for c in catalogo:
        t_c = _normaliza_persona(c).split()
        if not t_c:
            continue
        corto, largo = (t_obj, t_c) if len(t_obj) <= len(t_c) else (t_c, t_obj)
        if not all(p in largo for p in corto):
            continue
        if corto[-1] not in largo:
            continue
        candidatos.append(c)
    return candidatos[0] if len(candidatos) == 1 else None


def buscar(lineas: Dict[str, Dict], jugador: str) -> Optional[Dict]:
    """
    La ficha de un jugador dentro de las líneas de su partido.

    Tres intentos, del más seguro al más flexible: nombre exacto, el
    `name_mapper` del proyecto, y la regla de apellidos de arriba.

    **Un nombre que no casa no se fuerza**: devuelve `None` y la interfaz dice
    «línea no disponible», que es la verdad. Colgarle a un jugador la línea de
    otro sería peor que no enseñar ninguna.
    """
    if not lineas or not jugador:
        return None
    if jugador in lineas:
        return lineas[jugador]
    catalogo = [k for k in lineas if k not in ('clave_liga', 'home', 'away')]
    try:
        import name_mapper
        m = name_mapper.mapear(jugador, catalogo, contexto='lineas_jugador')
    except Exception:
        m = None
    if not m:
        m = por_apellidos(jugador, catalogo)
    return lineas.get(m) if m else None


# ---------------------------------------------------------------------------
# el precálculo diario
# ---------------------------------------------------------------------------
def precalcular(dias: int = 2, max_hilos: int = 4) -> Dict:
    """
    Las líneas de jugador de los fixtures próximos, listas para guardar.

    Una petición de tablero por partido NUESTRO. Se guarda sólo lo de remates
    —unas 80 familias de las 1.700-2.200 que trae cada tablero— así que el
    fichero es pequeño aunque la descarga no lo sea.
    """
    from concurrent.futures import ThreadPoolExecutor
    import cuotas_multi as cm
    import fixtures_espn as fx
    from config import LEAGUES

    claves = [c for c, cfg in LEAGUES.items()
              if cfg.get('disponible') and c in fx.ESPN_CODIGOS]
    por_liga = fx.fixtures_multi(claves, dias=dias)
    pendientes = []
    for clave, lista in (por_liga or {}).items():
        for f in (lista or []):
            h, a = f.get('home'), f.get('away')
            if h and a:
                pendientes.append((clave, h, a))

    def _uno(par):
        clave, h, a = par
        try:
            lin = del_tablero(cm.mercados_playdoit('futbol', h, a))
        except Exception as e:
            logger.debug('[lineas_jugador] %s-%s: %s', h, a, e)
            return None
        if not lin:
            return None
        return (_llave(h, a), {'clave_liga': clave, 'home': h, 'away': a,
                               **{k: _compacta(v) for k, v in lin.items()}})

    salida: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=max_hilos) as ex:
        for r in ex.map(_uno, pendientes):
            if r:
                salida[r[0]] = r[1]
    logger.info('[lineas_jugador] %d fixtures · %d con líneas de jugador',
                len(pendientes), len(salida))
    return {'generado': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'partidos': salida}


def guardar(doc: Dict, ruta: str = FICHERO) -> None:
    """
    Sin sangrado, y no es descuido: esto no lo lee nadie a mano.

    Son 3.400 fichas de jugador y el fichero se commitea todos los días. Con
    `indent=1` pesaba 640 KB y sin él baja a la mitad larga. El proyecto ya
    arrastra un `.git` de 15 GB por no haber hecho esta cuenta a tiempo.
    """
    try:
        import io_atomico
        io_atomico.escribir_json(ruta, doc)
    except Exception:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description='Líneas de remates por jugador')
    p.add_argument('--dias', type=int, default=2)
    p.add_argument('--salida', default=FICHERO)
    p.add_argument('--probar', nargs=2, metavar=('HOME', 'AWAY'), default=None)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s:%(name)s:%(message)s')

    if args.probar:
        lin = del_partido(args.probar[0], args.probar[1], permitir_red=True)
        print('%d jugadores con línea' % len(lin))
        for nombre, f in list(lin.items())[:12]:
            print('   %-30s (%s)  tot=%-28s on=%s'
                  % (nombre[:30], f.get('equipo'),
                     (f.get('tot') or {}).get('lineas'),
                     (f.get('on') or {}).get('lineas')))
        return 0

    doc = precalcular(dias=args.dias)
    guardar(doc, args.salida)
    n_jug = sum(len([k for k in v if k not in
                     ('clave_liga', 'home', 'away', 'equipo')])
                for v in (doc.get('partidos') or {}).values())
    print('%d partidos con líneas de jugador · %d fichas'
          % (len(doc.get('partidos') or {}), n_jug))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
