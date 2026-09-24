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
#
# v308 — Y LA ESCALERA ENTERA. El usuario la pidió con una captura de su casa:
# «1+, 2+, 3+ remates a puerta» con la cuota de cada peldaño, y que el modelo
# diga la probabilidad de cada uno. Playdoit la publica (0.5 / 1.5 / 2.5 son
# 1+ / 2+ / 3+) y aquí se tiraba. Son tres números por mercado.
_CAMPOS_GUARDADOS = ('principal', 'cuota', 'lineas')


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
                pendientes.append((clave, h, a, str(f.get('fecha') or '')[:10]))
    # v308 — Y TODO LO DEL PRONÓSTICO DEL DÍA, selecciones incluidas. Antes
    # sólo entraban las ligas con código de ESPN, así que ninguna selección
    # tenía líneas aunque Playdoit sí las cotiza (Portugal–Gales: Cristiano,
    # 1+ a puerta @1,09 · 2+ @1,65 · 3+ @3,10).
    vistos = {_llave(p[1], p[2]) for p in pendientes}
    for clave, h, a, fecha in partidos_del_pronostico():
        if _llave(h, a) not in vistos:
            vistos.add(_llave(h, a))
            pendientes.append((clave, h, a, fecha))

    def _uno(par):
        clave, h, a, fecha = par
        lin = {}
        for hh, aa in nombres_de_casa(clave, h, a):
            try:
                lin = del_tablero(cm.mercados_playdoit('futbol', hh, aa))
            except Exception as e:
                logger.debug('[lineas_jugador] %s-%s: %s', hh, aa, e)
                lin = {}
            if lin:
                break
        if not lin:
            return None
        return (_llave(h, a), {'clave_liga': clave, 'home': h, 'away': a,
                               'fecha': fecha,
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


def partidos_del_pronostico(ruta: str = 'pronostico_dia.json') -> List[tuple]:
    """[(clave_liga, home, away, fecha)] de los partidos de fútbol del
    pronóstico del día. Vacío si no está."""
    try:
        with open(ruta, encoding='utf-8') as f:
            d = (json.load(f) or {}).get('datos') or {}
    except Exception:
        return []
    fuera, vistos = [], set()
    for p in list(d.get('pronosticos') or []) + list(d.get('candidatos') or []):
        if not isinstance(p, dict):
            continue
        if str(p.get('deporte') or 'Fútbol') != 'Fútbol':
            continue
        par = str(p.get('partido') or '')
        if ' vs ' not in par:
            continue
        h, a = (x.strip() for x in par.split(' vs ', 1))
        k = _llave(h, a)
        if k in vistos:
            continue
        vistos.add(k)
        fuera.append((str(p.get('clave_liga') or ''), h, a,
                      str(p.get('fecha') or p.get('inicio') or '')[:10]))
    return fuera


def nombres_de_casa(clave: str, home: str, away: str) -> List[tuple]:
    """Los nombres con los que probar en la casa. Las selecciones van en
    español en Playdoit («Gales», no «Wales»): se prueba primero así."""
    fuera = []
    if clave == 'selecciones':
        try:
            from config import TEAM_NAMES_EN
            from prediction_api import NOMBRES_PAIS
            en_es = {TEAM_NAMES_EN[c]: es for c, es in NOMBRES_PAIS.items()
                     if c in TEAM_NAMES_EN}
            hh, aa = en_es.get(home), en_es.get(away)
            if hh and aa:
                fuera.append((hh, aa))
        except Exception as e:
            logger.debug('[lineas_jugador] nombres: %s', e)
    fuera.append((home, away))
    return fuera


# ---------------------------------------------------------------------------
# v308 — el histórico de precios, para poder medir contra la cuota
# ---------------------------------------------------------------------------
#
# Sin histórico de líneas de jugador no se puede saber si apostar donde el
# modelo ve más probabilidad que la casa GANA dinero: la calibración se mide
# con los partidos, el ROI sólo con los precios que hubo. Se guarda el último
# precio visto de cada peldaño (el más cercano al saque) y el primero, y
# cuando el partido se juega se liquida con los remates reales de
# `remates_fotmob`.
#
# Un fichero por mes: sólo cambia el del mes en curso, así que los viejos no
# vuelven a pesar en cada commit.
HIST_DIR = 'lineas_jugador_hist'
COL_HIST = ['fecha', 'clave_liga', 'home', 'away', 'jugador', 'equipo',
            'objetivo', 'linea', 'cuota_primera', 'cuota', 'capturado',
            'real', 'minutos']


def _ruta_hist(fecha: str) -> str:
    return os.path.join(HIST_DIR, '%s.csv' % (str(fecha)[:7] or 'sin-fecha'))


def _leer_hist(ruta: str) -> List[Dict]:
    import csv
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def _escribir_hist(ruta: str, filas: List[Dict]) -> None:
    import csv
    os.makedirs(HIST_DIR, exist_ok=True)
    tmp = ruta + '.nuevo'
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COL_HIST, lineterminator='\n',
                           extrasaction='ignore')
        w.writeheader()
        for r in sorted(filas, key=lambda x: (
                x['fecha'], x['home'], x['jugador'], x['objetivo'],
                float(x['linea']))):
            w.writerow({c: r.get(c, '') for c in COL_HIST})
    os.replace(tmp, ruta)


def registrar_historico(doc: Dict) -> int:
    """Añade o actualiza los precios del día. Devuelve los peldaños tocados."""
    ahora = str(doc.get('generado') or time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                     time.gmtime()))
    por_ruta: Dict[str, List[Dict]] = {}
    for v in (doc.get('partidos') or {}).values():
        fecha = str(v.get('fecha') or ahora)[:10]
        for jugador, f in v.items():
            if not isinstance(f, dict):
                continue
            for obj in ('tot', 'on'):
                for L, cu in ((f.get(obj) or {}).get('lineas') or {}).items():
                    por_ruta.setdefault(_ruta_hist(fecha), []).append({
                        'fecha': fecha, 'clave_liga': v.get('clave_liga'),
                        'home': v.get('home'), 'away': v.get('away'),
                        'jugador': jugador, 'equipo': f.get('equipo'),
                        'objetivo': obj, 'linea': str(L), 'cuota': cu,
                        'capturado': ahora})
    tocadas = 0
    for ruta, nuevas in por_ruta.items():
        filas = {(r['fecha'], r['home'], r['away'], r['jugador'],
                  r['objetivo'], r['linea']): r for r in _leer_hist(ruta)}
        for r in nuevas:
            k = (r['fecha'], r['home'], r['away'], r['jugador'],
                 r['objetivo'], r['linea'])
            viejo = filas.get(k) or {}
            r['cuota_primera'] = viejo.get('cuota_primera') or r['cuota']
            r['real'] = viejo.get('real', '')
            r['minutos'] = viejo.get('minutos', '')
            filas[k] = r
            tocadas += 1
        _escribir_hist(ruta, list(filas.values()))
    return tocadas


def liquidar(dias: int = 10) -> int:
    """Pone el número real (remates o a puerta) y los minutos a los peldaños
    de partidos ya jugados, con lo que guardó `remates_fotmob`."""
    import datetime as dt
    try:
        import remates_fotmob as rf
        dj = rf._jugadores()
    except Exception:
        return 0
    if dj is None or dj.empty or not os.path.isdir(HIST_DIR):
        return 0
    hoy = dt.date.today()
    desde = (hoy - dt.timedelta(days=dias)).isoformat()
    eqs = sorted(set(dj['equipo'].astype(str)))
    hechos = 0
    for nombre in sorted(os.listdir(HIST_DIR)):
        ruta = os.path.join(HIST_DIR, nombre)
        filas = _leer_hist(ruta)
        cambio = False
        for r in filas:
            if r.get('real') not in ('', None):
                continue
            if not (desde <= r['fecha'] < hoy.isoformat()):
                continue
            # FotMob va en UTC: el partido puede caer al día siguiente
            f0 = dt.date.fromisoformat(r['fecha'])
            fechas = {f0.isoformat(), (f0 + dt.timedelta(days=1)).isoformat()}
            cand = [e for e in (rf._resolver_equipo(r['home'], eqs),
                                rf._resolver_equipo(r['away'], eqs)) if e]
            s = dj[dj['equipo'].isin(cand)
                   & dj['fecha'].astype(str).isin(fechas)]
            if s.empty:
                continue
            j = por_apellidos(r['jugador'],
                              sorted(set(s['jugador'].astype(str))))
            if not j:
                continue
            fila = s[s['jugador'] == j].iloc[0]
            r['real'] = int(fila['a_puerta'] if r['objetivo'] == 'on'
                            else fila['tiros'])
            r['minutos'] = int(fila['minutos'])
            cambio = True
            hechos += 1
        if cambio:
            _escribir_hist(ruta, filas)
    return hechos


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
    try:
        print('histórico de precios: %d peldaños · liquidados %d'
              % (registrar_historico(doc), liquidar()))
    except Exception as e:
        logger.warning('[lineas_jugador] histórico: %s', e)
    n_jug = sum(len([k for k in v if k not in
                     ('clave_liga', 'home', 'away', 'equipo')])
                for v in (doc.get('partidos') or {}).values())
    print('%d partidos con líneas de jugador · %d fichas'
          % (len(doc.get('partidos') or {}), n_jug))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
