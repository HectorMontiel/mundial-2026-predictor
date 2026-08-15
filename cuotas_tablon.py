#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v114 — El tablón multi-casa, cruzado con el modelo: mercados con EV REAL.

El problema que resuelve
------------------------
La vista de liga tenía DOS caminos para enseñar cuotas y no eran comparables:

  A) `cuotas_auto` — encuentra el `event_id` de ESPN y saca 1X2, over/under,
     hándicap y props de jugador, todo cruzado con la plantilla y con su EV.
     Es la tabla rica que se ve en Liga MX.
  B) `_mostrar_cuotas_multi` — el respaldo cuando (A) no encuentra el evento.
     Enseñaba SÓLO el 1X2 de cada casa y la línea «Mejor precio disponible».

Y (A) falla justo donde más partidos hay: `buscar_event_id` mapea el nombre de
ESPN contra el nombre del modelo, y en las competiciones europeas el catálogo
del motor no contiene a los equipos de fase previa. En los registros de
producción se ve tal cual:

    [name_mapper] sin mapear: 'Kairat Almaty' (evid) — mejor candidato
                              'AC Milan' con 0.29

Sin `event_id` no hay (A), y la Champions, la Conference y la Eredivisie se
quedaban con la tabla pobre de (B) mientras Liga MX enseñaba treinta mercados.
El usuario lo dijo así: «¿y las demás cuotas? Quiero que todas las ligas
muestren bien todas las cuotas, todo al mismo nivel».

La solución
-----------
Dejar de depender del `event_id`. `cuotas_multi.cuotas_partido` YA devuelve, de
las cinco casas y sin ninguna clave, mucho más de lo que (B) pintaba:

    casas               1X2 de cada casa
    totales             Más/Menos de 2.5 y ambos marcan
    totales_por_casa    lo mismo, sin fusionar, con la casa de cada precio
    handicap_por_casa   hándicap asiático con la línea referida al local

Aquí eso se traduce al MISMO vocabulario que usa la plantilla del modelo y se
cruza con `cuotas_manual.cruzar_con_plantilla`, que es el cruce difuso que (A)
ya usaba. Resultado: la tabla rica en TODAS las competiciones que tengan
precio, venga o no de ESPN.

Y con una ventaja que (A) no tenía: (A) lee una sola casa (la que ESPN
publique), mientras que esto compara las cinco y se queda con la MEJOR de cada
mercado. Eso importa más que el modelo — la v112 midió que comprar al mejor
precio da +1,37 % de ROI sin modelo ninguno, mientras que apostar por la
probabilidad del modelo pierde entre −4,66 % y −6,52 %.
"""
import logging
import re
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Mercados que se saben leer del tablón, en el orden en que se enseñan.
FAMILIAS = ('1X2', 'Total de goles', 'Ambos marcan', 'Hándicap asiático')


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 1.0 else None


def _linea_txt(v: float) -> str:
    """0.5 → «0.5»; 1.0 → «1»  (la plantilla escribe «Monterrey -1», no «-1.0»)."""
    return f'{v:g}'


def _norm(t: str) -> str:
    """
    Minúsculas, sin acentos y con los espacios colapsados.

    Va con NFKD y no con NFD porque Altenar escribe «1ª Mitad» con el indicador
    ordinal femenino (U+00AA), que NFD deja intacto por no ser un acento. Con
    NFD, «1ª mitad» nunca empezaba por «1a mitad» y los doce mercados de
    tiempos del partido se perdían sin dar un solo error — el mismo modo de
    fallo silencioso que este proyecto ya ha pagado tres veces.
    """
    t = unicodedata.normalize('NFKD', str(t or ''))
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return ' '.join(t.lower().split())


def _apretado(t: str) -> str:
    """Sólo letras y dígitos, para comparar títulos de sección.

    «4. Ambos marcan · Primer/último gol · Par-Impar» y «5. Ambos Equipos
    Marcan (BTTS)» son la misma sección en dos motores distintos; con los
    signos fuera, las dos contienen «ambos» y «marcan».
    """
    return ''.join(c for c in _norm(t) if c.isalnum())


# Qué sección de la plantilla puede recibir cada familia de mercado.
#
# Cada familia lista ALTERNATIVAS (basta con que encaje una) y cada alternativa
# son fragmentos que TODOS tienen que aparecer en el título apretado de la
# sección. Hacen falta alternativas porque los dos motores del proyecto titulan
# distinto: el de clubes dice «3. Total de goles (línea deslizable)» y el de
# selecciones reparte lo mismo entre «4. Total de Goles» y «9b. Líneas
# Over/Under (probabilidad exacta)».
FAMILIA_SECCION = {
    '1X2':                (('1x2',),),
    'Doble oportunidad':  (('dobleoportunidad',),),
    'Total de goles':     (('totaldegoles',), ('lineasoverunder',),
                           ('overunder',)),
    'Ambos marcan':       (('ambos', 'marcan'),),
    'Hándicap asiático':  (('handicap', 'asiatic'),),
    'Marcador exacto':    (('marcadorexacto',),),
    'Margen de victoria': (('margendevictoria',),),
    'Goles por equipo':   (('golesporequipo',),),
    'Par/Impar':          (('parimpar',),),
    'Primer/último gol':  (('primerultimogol',),),
    'Mitades':            (('1a', 'mitad'), ('mitades',)),
    # v131 — familias de la NFL. Van aquí y no en `nfl_mercados` porque este
    # mapa es lo que ACOTA el cruce por similitud, y sin acotar volvería el
    # fallo que la v123 arregló: «Más de 44.5 puntos» (total del partido)
    # casando por parecido con «Más de 4.5 puntos» del total de un equipo, que
    # es otra sección y otra probabilidad. Con la familia declarada, cada fila
    # sólo puede cruzarse contra su propia sección.
    'Hándicap NFL':       (('handicap', 'nfl'),),
    'Total de puntos':    (('totaldepuntos',),),
    'Puntos por equipo':  (('puntosporequipo',),),
}


def _por_familia(filas) -> Dict[str, list]:
    """Agrupa las filas por familia de mercado, conservando el orden."""
    grupos: Dict[str, list] = {}
    for f in filas:
        grupos.setdefault(f.get('familia') or '', []).append(f)
    return grupos


def _plantilla_de_familia(plantilla: Dict, familia: str) -> Dict:
    """
    La plantilla recortada a las secciones donde esa familia puede casar.

    Devuelve la plantilla ENTERA cuando la familia no se reconoce o cuando
    ninguna sección encaja: es la degradación segura, porque perder un mercado
    por un título inesperado sería peor que el cruce amplio que había antes.
    """
    reglas = FAMILIA_SECCION.get(familia)
    if not reglas:
        return plantilla
    secciones = []
    for sec in (plantilla or {}).get('secciones', []):
        t = _apretado(sec.get('titulo', ''))
        if any(all(frag in t for frag in alt) for alt in reglas):
            secciones.append(sec)
    if not secciones:
        logger.debug(f'[tablon] ninguna sección para la familia {familia!r}; '
                     f'se cruza contra la plantilla entera')
        return plantilla
    return {'secciones': secciones}


def filas_del_tablon(res: Dict, home: str, away: str) -> List[Dict]:
    """
    Todo lo que el tablón publica, como filas `{etiqueta, cuota, casa, familia}`
    en el vocabulario de la plantilla del modelo.

    Las etiquetas están copiadas de `plantilla_club` a propósito —«Gana
    Monterrey», «Más de 2.5 goles», «Ambos equipos marcan: Sí», «Juarez
    +1.5»—, porque el cruce posterior es por similitud de cadena y acertar el
    vocabulario es lo que decide si un mercado aparece o se pierde.
    """
    filas: List[Dict] = []

    def _add(etiqueta, cuota, casa, familia):
        c = _f(cuota)
        if c is not None:
            filas.append({'etiqueta': etiqueta, 'cuota': round(c, 4),
                          'casa': casa, 'familia': familia})

    # --- 1X2, de cada casa ------------------------------------------------
    for casa, c in (res.get('casas') or {}).items():
        if casa.startswith('_'):          # '_totales' es un cajón interno
            continue
        _add(f'Gana {home}', (c or {}).get('home'), casa, '1X2')
        _add('Empate', (c or {}).get('draw'), casa, '1X2')
        _add(f'Gana {away}', (c or {}).get('away'), casa, '1X2')

    # --- totales y ambos marcan -------------------------------------------
    # Se prefiere la versión POR CASA (permite line shopping); el dict
    # fusionado es el respaldo, y entonces no se sabe de quién es el precio.
    por_casa = res.get('totales_por_casa') or {}
    if not por_casa and (res.get('totales') or {}):
        por_casa = {'—': res['totales']}
    for casa, t in por_casa.items():
        _add('Más de 2.5 goles', (t or {}).get('over25'), casa, 'Total de goles')
        _add('Menos de 2.5 goles', (t or {}).get('under25'), casa, 'Total de goles')
        _add('Ambos equipos marcan: Sí', (t or {}).get('btts_yes'), casa,
             'Ambos marcan')
        _add('Ambos equipos marcan: No', (t or {}).get('btts_no'), casa,
             'Ambos marcan')

    # --- v114: TODAS las líneas de goles del ancla sharp -------------------
    #
    # `totales_por_casa` sólo trae la línea de 2.5. Pinnacle publica el abanico
    # entero (0.5, 1.5, 2.5, 3.5, 4.5…) y hasta la v114 se descartaba. Sin
    # esto, un partido tenía cinco mercados con precio real y no había con qué
    # armar más de una combinada.
    #
    # Sólo se emiten las líneas que la plantilla del modelo TIENE: las de .5
    # hasta 5.5. Las asiáticas de cuarto (2.25, 2.75) no existen ahí, y
    # dejarlas pasar sería peor que perderlas — el cruce es por similitud de
    # texto y «Más de 2.25 goles» se parece demasiado a «Más de 2.5 goles»,
    # así que acabaría poniéndole a un mercado el precio de otro.
    for linea, precios in (res.get('lineas_totales') or {}).items():
        try:
            L = float(linea)
        except (TypeError, ValueError):
            continue
        if abs(L * 2 - round(L * 2)) > 1e-9 or L % 1 == 0 or not (0 < L <= 5.5):
            continue                      # sólo X.5, y dentro de la plantilla
        _add(f'Más de {_linea_txt(L)} goles', (precios or {}).get('over'),
             'Pinnacle', 'Total de goles')
        _add(f'Menos de {_linea_txt(L)} goles', (precios or {}).get('under'),
             'Pinnacle', 'Total de goles')

    # --- v114: TODAS las líneas de hándicap del ancla sharp ----------------
    # Misma criba: la plantilla nombra «Monterrey -1.5» y «Juarez +1.5», así
    # que sólo entran las líneas de .5. La del visitante va con el signo
    # cambiado, que es como la escribe la plantilla.
    for linea, precios in (res.get('lineas_handicap') or {}).items():
        try:
            L = float(linea)
        except (TypeError, ValueError):
            continue
        if abs(L * 2 - round(L * 2)) > 1e-9 or L % 1 == 0 or abs(L) > 4:
            continue
        v = _linea_txt(abs(L))
        signo_h = '-' if L < 0 else '+'
        signo_a = '+' if L < 0 else '-'
        _add(f'{home} {signo_h}{v}', (precios or {}).get('home'),
             'Pinnacle', 'Hándicap asiático')
        _add(f'{away} {signo_a}{v}', (precios or {}).get('away'),
             'Pinnacle', 'Hándicap asiático')

    # --- hándicap asiático -------------------------------------------------
    # `handicap_por_casa` trae la línea REFERIDA AL LOCAL (negativa = local
    # favorito), que es el convenio del proyecto. La plantilla nombra cada
    # lado con su propia línea, así que la del visitante va cambiada de signo.
    for casa, ah in (res.get('handicap_por_casa') or {}).items():
        linea = (ah or {}).get('linea')
        if linea is None:
            continue
        try:
            L = float(linea)
        except (TypeError, ValueError):
            continue
        signo_h = '-' if L < 0 else '+'
        signo_a = '+' if L < 0 else '-'
        v = _linea_txt(abs(L))
        _add(f'{home} {signo_h}{v}', ah.get('home'), casa, 'Hándicap asiático')
        _add(f'{away} {signo_a}{v}', ah.get('away'), casa, 'Hándicap asiático')

    return filas


def mercados_con_ev(res: Dict, plantilla: Dict, home: str,
                    away: str) -> List[Dict]:
    """
    Mercados del tablón cruzados con el modelo, **al mejor precio de cada uno**.

    Por qué al mejor precio y no al de una casa fija: es el único criterio con
    ROI positivo y robusto que el proyecto ha medido (+11,49 % en el tramo de
    juicio, p5 +1,73 %). Cada fila lleva la casa que da ese precio y cuántas
    casas se compararon, para que se vea de dónde sale.

    Devuelve filas ordenadas por EV descendente con:
        mercado, apuesta, prob, cuota_casa, casa, cuota_justa, ev,
        n_casas, cuota_peor, familia
    """
    return mercados_de_filas(filas_del_tablon(res, home, away), plantilla)


def mercados_de_filas(filas: List[Dict], plantilla: Dict) -> List[Dict]:
    """
    El cruce con el modelo, a partir de filas ya extraídas.

    Se separó de `mercados_con_ev` en la v122 porque hay dos orígenes de filas
    —el tablón multi-casa y el tablero completo de Playdoit— y el cruce con la
    plantilla, el line shopping y la criba por EV son idénticos para los dos.
    Con una casa sola el line shopping no encuentra nada que comparar y todas
    las filas salen con `n_casas = 1`, que es exactamente la verdad.
    """
    if not filas:
        return []

    # line shopping: una sola fila por etiqueta, con el precio más alto
    mejor_por_etq: Dict[str, Dict] = {}
    for f in filas:
        prev = mejor_por_etq.get(f['etiqueta'])
        if prev is None:
            mejor_por_etq[f['etiqueta']] = {**f, 'n_casas': 1,
                                            'cuota_peor': f['cuota'],
                                            '_suma': f['cuota']}
            continue
        prev['n_casas'] += 1
        prev['cuota_peor'] = min(prev['cuota_peor'], f['cuota'])
        # v125 — la MEDIA de las casas, no sólo el mejor y el peor.
        #
        # Hace falta porque la medición que fija el umbral de la Sección 1
        # compara contra el CONSENSO (la media del resto de casas), no contra
        # el mejor precio. Usar el mejor como referencia mide otra cosa —una
        # mucho más exigente— y aplicarle un umbral calibrado sobre la media
        # sería comparar peras con manzanas.
        prev['_suma'] += f['cuota']
        if f['cuota'] > prev['cuota']:
            prev.update({'cuota': f['cuota'], 'casa': f['casa']})
    for v in mejor_por_etq.values():
        v['cuota_media'] = round(v.pop('_suma') / max(v['n_casas'], 1), 4)

    # v123 — CADA MERCADO SE CRUZA CONTRA SU SECCIÓN, NO CONTRA TODA LA
    # PLANTILLA.
    #
    # `cruzar_con_plantilla` compara por similitud de cadena contra los ~85
    # campos del modelo a la vez, y cuando dos campos distintos se llaman
    # parecido gana el que más se parezca, no el correcto. El caso que lo
    # destapó llevaba en producción desde la v114 y es el mercado más jugado
    # que existe:
    #
    #     «Empate» @ 4,63  →  «Empate» (mv_x, margen de victoria)   similitud 1,00
    #                     y NO  →  «Empate (+269)» (draw_prob, 1X2)  similitud 0,63
    #
    # Los dos campos describen el mismo suceso, así que la probabilidad y el EV
    # salían bien y nada fallaba a la vista. Pero el precio del empate no
    # llegaba nunca a `draw_prob`, así que el constructor de combinadas
    # armaba cualquier pata con empate a CUOTA JUSTA —un precio inventado—
    # teniendo el real delante.
    #
    # Se arregla acotando los candidatos: una fila de familia «1X2» sólo puede
    # casar con campos de la sección del 1X2. Si la familia no se reconoce o
    # ninguna sección encaja, se cruza contra la plantilla entera como antes,
    # así que ninguna competición pierde mercados por esto.
    try:
        import cuotas_manual
        cruzadas = []
        for fam, grupo in _por_familia(mejor_por_etq.values()).items():
            pl_fam = _plantilla_de_familia(plantilla, fam)
            cruzadas += cuotas_manual.cruzar_con_plantilla(
                [{'etiqueta': v['etiqueta'], 'cuota': v['cuota']}
                 for v in grupo], pl_fam)
    except Exception as e:
        logger.warning(f'[tablon] no se pudo cruzar con la plantilla: {e}')
        return []

    # v122 — EL VETO POR SEÑA, PORQUE EL PARECIDO DE TEXTO NO BASTA.
    #
    # `cruzar_con_plantilla` empareja por similitud de cadena con un listón de
    # 0,80. Eso vale para «Gana Monterrey» contra «Gana Monterrey (-121)», pero
    # con el tablero completo de una casa aparecen mercados que la plantilla NO
    # tiene, y entonces el comparador entrega el más parecido en vez de nada.
    # Medido el 2026-08-10 en Monterrey vs Juárez:
    #
    #     «Monterrey 3-4 Juarez» @ 251,00  →  «Monterrey o Juarez» (p 0,785)
    #     similitud 0,89  →  EV declarado +19.603 %
    #
    # Es el mismo fallo de la v114 (una cuota puesta sobre otro mercado) por
    # otra puerta, y da una apuesta en vez de una excepción. La guardia: quien
    # emite la fila puede exigir que la etiqueta de la plantilla contenga una
    # SEÑA —el marcador «3-4», la línea «de 2.5 goles», el margen «por 3+»—.
    # Si no está, la fila se cae. Las filas sin seña se cruzan como siempre,
    # así que el tablón multi-casa se comporta exactamente igual que antes.
    def _pasa_veto(r) -> bool:
        sena = (mejor_por_etq.get(r.get('texto_pegado')) or {}).get('sena')
        if not sena:
            return True
        return _norm(sena) in _norm(r.get('apuesta'))

    descartadas = [r for r in cruzadas if not _pasa_veto(r)]
    if descartadas:
        logger.info(
            f'[tablon] {len(descartadas)} mercados descartados por no existir '
            f'en la plantilla: '
            + ', '.join(f"{r.get('texto_pegado')}→{r.get('apuesta')}"
                        for r in descartadas[:6]))
    cruzadas = [r for r in cruzadas if _pasa_veto(r)]

    # `cruzar_con_plantilla` devuelve la etiqueta de la PLANTILLA, no la que se
    # le pasó; el enlace de vuelta es `texto_pegado`, que conserva la nuestra.
    for r in cruzadas:
        origen = mejor_por_etq.get(r.get('texto_pegado')) or {}
        r['casa'] = origen.get('casa')
        r['n_casas'] = origen.get('n_casas', 1)
        r['cuota_peor'] = origen.get('cuota_peor')
        r['cuota_media'] = origen.get('cuota_media')
        r['familia'] = origen.get('familia', '')
        # cuánto se gana por comprar bien en vez de mal, en el mismo mercado
        if r.get('cuota_peor') and r['cuota_peor'] > 0:
            r['ventaja_line_shopping'] = round(
                r['cuota_casa'] / r['cuota_peor'] - 1, 4)
        else:
            r['ventaja_line_shopping'] = 0.0

    # v123 — LOS MERCADOS DE TIEMPOS LLEVAN EL EV MARCADO COMO NO FIABLE.
    #
    # Ver `_mitades_degeneradas`: el modelo reparte los goles a partes iguales
    # entre las dos mitades, así que su probabilidad para la 1ª y la 2ª es la
    # MISMA cifra. El precio de la casa no lo es —paga 1,95 el «menos de 1.5»
    # de la segunda y 1,6451 el de la primera— y de esa diferencia sale un EV
    # que no mide valor: mide que al modelo le falta el reparto por mitad.
    #
    # No se descartan los mercados: su PRECIO es real y sirve para armar un
    # boleto en una sola casa, que es para lo que el usuario los pidió. Lo que
    # se marca es que su EV no se puede creer.
    if _mitades_degeneradas(plantilla):
        for r in cruzadas:
            if r.get('familia') == 'Mitades':
                r['ev_no_fiable'] = True
                r['motivo_no_fiable'] = (
                    'el modelo da la misma probabilidad a las dos mitades, así '
                    'que su EV aquí no mide valor')

    # un mismo mercado del modelo puede recibir dos etiquetas nuestras; se
    # conserva la de mejor EV (mismo criterio que `cuotas_auto.evaluar`)
    mejor: Dict[str, Dict] = {}
    for r in cruzadas:
        prev = mejor.get(r['apuesta'])
        if prev is None or r['ev'] > prev['ev']:
            mejor[r['apuesta']] = r
    return sorted(mejor.values(), key=lambda r: -r['ev'])


def _mitades_degeneradas(plantilla: Dict) -> bool:
    """
    ¿Da el modelo la MISMA probabilidad a las dos mitades?

    Medido el 2026-08-10 sobre cuatro partidos de Liga MX: **4 de 4**. El
    reparto de goles por mitad (`G2H_MA5` en `league_engine`) no está llegando,
    así que `f1h` y `f2h` valen 0,5 y las dos mitades salen clavadas —«1ª mitad:
    más de 0.5 goles 77,1 %» y «2ª mitad: más de 0.5 goles 77,1 %»—.
    En el fútbol real se marca alrededor del 55 % de los goles en la segunda
    parte, así que esa simetría es falsa y todo EV que salga de ella también.

    Se comprueba sobre los campos, no sobre `f1h`/`f2h`: lo que importa es lo
    que la plantilla acaba diciendo, que es lo que se cruza con las cuotas.
    """
    campos = {}
    for sec in (plantilla or {}).get('secciones', []):
        for c in sec.get('campos', []):
            if c.get('id'):
                campos[c['id']] = c.get('valor')
    pares = [('1h_over05', '2h_over05'), ('1h_1x2_home', '2h_1x2_home'),
             ('1h_btts_si', '2h_btts_si')]
    vistos = [(campos.get(a), campos.get(b)) for a, b in pares
              if campos.get(a) is not None and campos.get(b) is not None]
    if not vistos:
        return False
    return all(abs(float(a) - float(b)) < 1e-9 for a, b in vistos)


# ===========================================================================
# v122 — EL TABLERO DE UNA SOLA CASA: PLAYDOIT
#
# El usuario lo planteó exactamente así: «en el mundo real no es posible hacer
# cuotas con diferentes casas. Quiero que me des cuotas también pero solo con
# la casa de Playdoit que es la mía. De esa forma sabré cuál me da una buena
# cuota a mí».
#
# Es una objeción correcta y no menor. Hasta aquí las combinadas se armaban con
# el MEJOR precio de cada mercado, viniera de donde viniera, y eso significa
# que una combinada de tres patas podía tener una en Pinnacle, otra en
# Matchbook y otra en Playdoit. Como ticket no existe: son tres apuestas
# sueltas, y la «cuota combinada» que se anunciaba no la paga nadie.
#
# La regla del proyecto (el edge está en el precio, no en el modelo) NO cambia
# por esto. Lo que cambia es a qué se compara: cuando sólo se puede jugar en
# una casa, el line shopping deja de ser una decisión y pasa a ser una
# MEDICIÓN — cuánto se deja el usuario por no poder ir a otra parte. Eso es lo
# que estas funciones calculan y lo que la pantalla enseña.
# ===========================================================================

# Mercados de PERIODO. Se descartan enteros y a propósito: la plantilla del
# modelo no tiene ni un solo campo de media parte, y sus etiquetas («Monterrey
# o empate» del 1ª Mitad) son IDÉNTICAS a las del partido completo. Dejarlas
# entrar sería ponerle a un mercado el precio de otro, que es el fallo que la
# v114 corrigió en el emparejador y no se va a reintroducir por la puerta de
# atrás.
_PERIODO = re.compile(r'mitad|descanso|cuarto|per[ií]odo|periodo|\bset\b|'
                      r'entrada|inning|primer tiempo|segundo tiempo')

# Sólo las líneas que la plantilla TIENE. Altenar publica el abanico asiático
# entero (1.75, 2, 2.25, 2.75…) y la plantilla sólo nombra las de .5; «Más de
# 2.25 goles» se parece un 0,93 a «Más de 2.5 goles» con el comparador de
# cadenas, así que colarlas es garantizar el cruce equivocado.
_LINEA = re.compile(r'^(m[áa]s|menos)\s+de\s+([0-9]+(?:[.,][0-9]+)?)$', re.I)
_LINEA_AH = re.compile(r'^(.+?)\s*\(([+-]?[0-9]+(?:[.,][0-9]+)?)\)$')
_MARCADOR = re.compile(r'^([0-9]{1,2})\s*[:\-]\s*([0-9]{1,2})$')


def _num(t: str):
    try:
        return float(str(t).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def _es_media(x) -> bool:
    """¿Es una línea de las que la plantilla nombra (X.5)?"""
    return x is not None and abs(abs(x) * 2 - round(abs(x) * 2)) < 1e-9 \
        and abs(x) % 1 != 0


# Los mercados de mitad que la plantilla del modelo nombra, y sólo ésos.
# `league_engine._mercados_mitad` publica, por cada mitad: el 1X2, los totales
# (0.5 y 1.5 en la primera; 0.5, 1.5 y 2.5 en la segunda) y ambos marcan. Los
# totales POR EQUIPO de una mitad —que Playdoit sí cotiza— no existen ahí, así
# que se quedan fuera.
_LINEAS_MITAD = {'1ª mitad': (0.5, 1.5), '2ª mitad': (0.5, 1.5, 2.5)}


def _mitad_de(nombre: str, n_ch: str, n_ca: str) -> Optional[str]:
    """
    ¿De qué mitad habla este mercado, y es uno de los que la plantilla tiene?

    Devuelve «1ª mitad», «2ª mitad» o None. Descarta explícitamente los que
    llevan el nombre de un equipo («1ª Mitad - Monterrey total»), que son
    totales por equipo sin campo en el modelo, y los combinados de mitad con
    partido completo («1X2 1ª mitad / Doble oportunidad (partido)»), que no son
    un mercado de mitad sino otra cosa.
    """
    if n_ch in nombre or n_ca in nombre:
        return None
    if '/' in nombre or 'partido' in nombre:
        return None
    if nombre.startswith('1a mitad'):
        return '1ª mitad'
    if nombre.startswith('2a mitad'):
        return '2ª mitad'
    return None


def _add_mitad(_add, mitad: str, m: Dict, sels: List[Dict], home: str,
               away: str, n_ch: str, n_ca: str) -> None:
    """Traduce un mercado de mitad al vocabulario de la plantilla."""
    nombre = _norm(m.get('nombre'))
    nombres = [_norm(s.get('nombre')) for s in sels]
    fam = 'Mitades'

    # 1X2 de la mitad → «1ª mitad: gana Monterrey»
    if len(sels) == 3 and 'empate' in nombres \
            and n_ch in nombres and n_ca in nombres:
        for s in sels:
            n = _norm(s.get('nombre'))
            if n == n_ch:
                _add(f'{mitad}: gana {home}', s['cuota'], fam,
                     f'{mitad}: gana {home}')
            elif n == n_ca:
                _add(f'{mitad}: gana {away}', s['cuota'], fam,
                     f'{mitad}: gana {away}')
            elif n == 'empate':
                _add(f'{mitad}: empate', s['cuota'], fam, f'{mitad}: empate')
        return

    # total de la mitad → «1ª mitad: más de 1.5 goles»
    if 'total' in nombre:
        for s in sels:
            mt = _LINEA.match(str(s.get('nombre') or '').strip())
            if not mt:
                continue
            L = _num(mt.group(2))
            if L is None or L not in _LINEAS_MITAD.get(mitad, ()):
                continue
            lado = 'más' if _norm(mt.group(1)).startswith('mas') else 'menos'
            etq = f'{mitad}: {lado} de {L:g} goles'
            _add(etq, s['cuota'], fam, etq)
        return

    # ambos marcan de la mitad → «1ª mitad: ambos marcan Sí»
    if 'ambos equipos marcan' in nombre:
        for s in sels:
            n = _norm(s.get('nombre'))
            if n == 'si':
                _add(f'{mitad}: ambos marcan Sí', s['cuota'], fam,
                     f'{mitad}: ambos marcan si')
            elif n == 'no':
                _add(f'{mitad}: ambos marcan No', s['cuota'], fam,
                     f'{mitad}: ambos marcan no')


def filas_playdoit(det: Dict, home: str, away: str) -> List[Dict]:
    """
    El tablero de Playdoit, en el vocabulario de la plantilla del modelo.

    Se traduce SÓLO lo que la plantilla nombra igual. Todo lo demás —marcador
    exacto XL, multigoles, goleador, mitades, hándicap 1x2 con marcador— se
    deja fuera aunque tenga precio: un mercado que no existe en el modelo no
    tiene probabilidad con la que cruzarse, y forzarlo por parecido de texto es
    la forma de inventar un EV.

    La identificación es por NOMBRE de mercado, no por `typeId`. El `typeId` de
    Altenar cambia de un deporte a otro (la v77 ya lo pagó: fijarlo a 1 dejó
    MLB, NBA y tenis sin cuotas y sin dar un solo error), mientras que el
    nombre en es-ES es el mismo texto que el usuario lee en la web de la casa.
    """
    filas: List[Dict] = []
    if not isinstance(det, dict):
        return filas
    ch = det.get('casa_home') or home
    ca = det.get('casa_away') or away
    n_ch, n_ca = _norm(ch), _norm(ca)

    def _add(etiqueta, cuota, familia, sena=None):
        """
        Una fila del tablero, con la SEÑA que la etiqueta del modelo debe
        llevar para que el cruce se dé por bueno (ver el veto de
        `mercados_de_filas`). Sin seña, un marcador exacto que la plantilla no
        tiene acaba cobrando la probabilidad del mercado más parecido — que es
        cómo salió un EV de +19.603 % en las primeras pruebas de esta versión.
        """
        c = _f(cuota)
        if c is not None:
            filas.append({'etiqueta': etiqueta, 'cuota': round(c, 4),
                          'casa': det.get('casa', 'Playdoit'),
                          'familia': familia, 'sena': sena})

    def _lado(sel) -> Optional[str]:
        """¿De qué equipo habla esta selección? Por nombre, no por id."""
        n = _norm(sel.get('nombre'))
        if n == n_ch:
            return 'home'
        if n == n_ca:
            return 'away'
        return None

    for m in (det.get('mercados') or []):
        nombre = _norm(m.get('nombre'))
        sels = m.get('selecciones') or []
        nombres = [_norm(s.get('nombre')) for s in sels]

        # --- v123: LOS TIEMPOS, que la plantilla SÍ tiene ------------------
        #
        # El usuario los pidió («combinadas de córners, tarjetas, tiempos») y
        # de los tres es el único con precio: medido sobre Monterrey vs
        # Juárez, Playdoit publica CERO mercados de córners o tarjetas de 148,
        # y en cambio doce de mitades.
        #
        # La v122 los descartaba todos por una razón buena —sus etiquetas son
        # idénticas a las del partido completo, así que «1ª Mitad · Más de 1.5»
        # habría robado el precio del «Más de 1.5 goles» del partido— pero la
        # solución no era tirarlos: es ponerles el prefijo con el que la
        # plantilla los nombra («1ª mitad: más de 1.5 goles») y dejar que la
        # seña haga el resto.
        mitad = _mitad_de(nombre, n_ch, n_ca)
        if mitad:
            _add_mitad(_add, mitad, m, sels, home, away, n_ch, n_ca)
            continue
        if _PERIODO.search(nombre):
            continue

        # --- 1X2: por ESTRUCTURA (tres selecciones, dos equipos y el empate).
        # Así vale para cualquier deporte sin depender de cómo se llame el
        # mercado, que es lo que `_ganador_altenar` ya aprendió en la v77.
        if len(sels) == 3 and 'empate' in nombres \
                and n_ch in nombres and n_ca in nombres:
            for s in sels:
                l = _lado(s)
                if l == 'home':
                    _add(f'Gana {home}', s['cuota'], '1X2', f'gana {home}')
                elif l == 'away':
                    _add(f'Gana {away}', s['cuota'], '1X2', f'gana {away}')
                elif _norm(s.get('nombre')) == 'empate':
                    _add('Empate', s['cuota'], '1X2', 'empate')
            continue

        # --- doble oportunidad: la casa ya la escribe como la plantilla
        if nombre == 'doble oportunidad':
            for s in sels:
                n = _norm(s.get('nombre'))
                if n == f'{n_ch} o empate':
                    _add(f'{home} o Empate', s['cuota'], 'Doble oportunidad',
                         f'{home} o empate')
                elif n == f'{n_ch} o {n_ca}':
                    _add(f'{home} o {away}', s['cuota'], 'Doble oportunidad',
                         f'{home} o {away}')
                elif n == f'empate o {n_ca}':
                    _add(f'Empate o {away}', s['cuota'], 'Doble oportunidad',
                         f'empate o {away}')
            continue

        # --- ambos marcan
        if nombre == 'ambos equipos marcan':
            for s in sels:
                n = _norm(s.get('nombre'))
                if n == 'si':
                    _add('Ambos equipos marcan: Sí', s['cuota'], 'Ambos marcan')
                elif n == 'no':
                    _add('Ambos equipos marcan: No', s['cuota'], 'Ambos marcan',
                         'no')
            continue

        # --- total de goles del partido, todas las líneas de .5
        if nombre == 'total':
            for s in sels:
                mt = _LINEA.match(str(s.get('nombre') or '').strip())
                if not mt:
                    continue
                L = _num(mt.group(2))
                if not _es_media(L) or not (0 < L <= 5.5):
                    continue
                lado = 'Más' if _norm(mt.group(1)).startswith('mas') else 'Menos'
                _add(f'{lado} de {L:g} goles', s['cuota'], 'Total de goles',
                     f'{lado} de {L:g} goles')
            continue

        # --- total de goles POR EQUIPO («Monterrey total de goles»)
        if 'total de goles' in nombre and (n_ch in nombre or n_ca in nombre):
            equipo = home if n_ch in nombre else away
            for s in sels:
                mt = _LINEA.match(str(s.get('nombre') or '').strip())
                if not mt or not _norm(mt.group(1)).startswith('mas'):
                    continue      # la plantilla sólo nombra el «más de»
                L = _num(mt.group(2))
                if not _es_media(L) or not (0 < L <= 2.5):
                    continue
                _add(f'{equipo} más de {L:g} goles', s['cuota'],
                     'Goles por equipo', f'{equipo} mas de {L:g}')
            continue

        # --- hándicap asiático, sólo las líneas enteras de .5
        if 'handicap' in nombre and 'asiat' in nombre:
            for s in sels:
                mt = _LINEA_AH.match(str(s.get('nombre') or '').strip())
                if not mt:
                    continue
                eq = _norm(mt.group(1))
                L = _num(mt.group(2))
                if not _es_media(L) or abs(L) > 3.5:
                    continue
                equipo = home if eq == n_ch else away if eq == n_ca else None
                if equipo is None:
                    continue
                _add(f'{equipo} {L:+g}', s['cuota'], 'Hándicap asiático',
                     f'{equipo} {L:+g}')
            continue

        # --- par / impar del partido (el de cada equipo lleva su nombre y no
        #     entra aquí: la plantilla no tiene ese campo)
        if nombre in ('par/impar', 'par impar'):
            for s in sels:
                n = _norm(s.get('nombre'))
                if n == 'par':
                    _add('Total de goles PAR', s['cuota'], 'Par/Impar',
                         'goles par')
                elif n == 'impar':
                    _add('Total de goles IMPAR', s['cuota'], 'Par/Impar',
                         'goles impar')
            continue

        # --- primer y último gol
        if nombre in ('primer gol', 'ultimo gol'):
            etq = 'Primer gol' if nombre == 'primer gol' else 'Último gol'
            for s in sels:
                l = _lado(s)
                if l == 'home':
                    _add(f'{etq} de {home}', s['cuota'], 'Primer/último gol',
                         f'{etq} de {home}')
                elif l == 'away':
                    _add(f'{etq} de {away}', s['cuota'], 'Primer/último gol',
                         f'{etq} de {away}')
                elif nombre == 'primer gol' and _norm(s.get('nombre')) == 'ninguno':
                    # «no marca ninguno el primer gol» es, exactamente, el 0-0
                    _add('Sin goles (0-0)', s['cuota'], 'Primer/último gol',
                         'sin goles')
            continue

        # --- marcador exacto («2:1» → «Monterrey 2-1 Juarez»)
        if nombre == 'marcador exacto':
            for s in sels:
                mt = _MARCADOR.match(str(s.get('nombre') or '').strip())
                if not mt:
                    continue
                _add(f'{home} {mt.group(1)}-{mt.group(2)} {away}', s['cuota'],
                     'Marcador exacto', f'{mt.group(1)}-{mt.group(2)}')
            continue

        # --- margen de victoria. El «Empate» de este mercado se descarta: la
        #     plantilla lo tiene con la misma etiqueta que el del 1X2 y el
        #     cruce por parecido no sabría a cuál de los dos va.
        if nombre == 'margen de victoria':
            for s in sels:
                n = str(s.get('nombre') or '').strip()
                if _norm(n).startswith(n_ch + ' por '):
                    _add(f'{home} por {n.split(" por ", 1)[1]}', s['cuota'],
                         'Margen de victoria',
                         f'{home} por {n.split(" por ", 1)[1]}')
                elif _norm(n).startswith(n_ca + ' por '):
                    _add(f'{away} por {n.split(" por ", 1)[1]}', s['cuota'],
                         'Margen de victoria',
                         f'{away} por {n.split(" por ", 1)[1]}')
            continue

    return filas


def mercados_playdoit_con_ev(det: Dict, plantilla: Dict, home: str,
                             away: str) -> List[Dict]:
    """Los mercados de Playdoit cruzados con el modelo, con su EV accionable."""
    return mercados_de_filas(filas_playdoit(det, home, away), plantilla)


def comparar_con_el_mercado(mk_pdt: List[Dict],
                            mk_mercado: List[Dict]) -> List[Dict]:
    """
    Cuánto se deja (o se gana) el usuario por jugar en su casa y no en la mejor.

    A cada mercado de Playdoit se le pega el mejor precio del tablón para el
    MISMO mercado del modelo (mismo `id`, no mismo texto) y se anota la
    diferencia. Es la única cifra de esta pantalla que no depende de que el
    modelo acierte: son dos precios del mismo suceso.

    Añade a cada fila:
        cuota_mercado      el mejor precio del tablón, si existe
        casa_mercado       quién lo da
        dif_vs_mercado     +0.03 = Playdoit paga un 3 % MÁS que la mejor
                           alternativa; −0.03 = un 3 % menos
    """
    mejor = {}
    for r in (mk_mercado or []):
        cid = r.get('id')
        if not cid or not r.get('cuota_casa'):
            continue
        if cid not in mejor or r['cuota_casa'] > mejor[cid]['cuota_casa']:
            mejor[cid] = r
    salida = []
    for r in (mk_pdt or []):
        r = dict(r)
        alt = mejor.get(r.get('id'))
        # Sólo cuenta como comparación si el otro precio es de OTRA casa: si el
        # mejor del tablón lo da Playdoit, comparar consigo mismo daría un 0 %
        # que se leería como «no pierdes nada» cuando lo cierto es «además,
        # aquí mandas tú».
        if alt and alt.get('cuota_casa') and alt.get('casa') != r.get('casa'):
            r['cuota_mercado'] = alt['cuota_casa']
            r['casa_mercado'] = alt.get('casa')
            r['dif_vs_mercado'] = round(
                r['cuota_casa'] / alt['cuota_casa'] - 1, 4)
            # v125 — y contra el CONSENSO, que es la referencia con la que se
            # midió el umbral de la Sección 1. `dif_vs_mercado` compara contra
            # el MEJOR precio del resto (más exigente, buena para enseñar
            # cuánto se deja el usuario); `dif_vs_consenso` compara contra la
            # media de las casas, que es lo que decide si hay ventaja.
            r['cuota_consenso'] = alt.get('cuota_media')
            r['n_casas_mercado'] = alt.get('n_casas')
            r['dif_vs_consenso'] = (
                round(r['cuota_casa'] / alt['cuota_media'] - 1, 4)
                if alt.get('cuota_media') else None)
        else:
            r['cuota_mercado'] = None
            r['casa_mercado'] = None
            r['dif_vs_mercado'] = None
            r['cuota_consenso'] = None
            r['n_casas_mercado'] = None
            r['dif_vs_consenso'] = None
        salida.append(r)
    return salida


def resumen_playdoit(comparados: List[Dict]) -> Optional[Dict]:
    """
    Titular de la sección: dónde manda tu casa y dónde te está costando dinero.

    Devuelve None si no hay ni un mercado con el que comparar, que también es
    una respuesta: hoy no se puede saber si Playdoit paga bien en este partido.
    """
    con = [r for r in (comparados or []) if r.get('dif_vs_mercado') is not None]
    if not con:
        return None
    gana = [r for r in con if r['dif_vs_mercado'] > 0]
    pierde = [r for r in con if r['dif_vs_mercado'] < 0]
    media = sum(r['dif_vs_mercado'] for r in con) / len(con)
    peor = min(con, key=lambda r: r['dif_vs_mercado'])
    return {'n': len(con), 'n_gana': len(gana), 'n_pierde': len(pierde),
            'media': round(media, 4),
            'peor_apuesta': peor.get('apuesta'),
            'peor_dif': peor.get('dif_vs_mercado'),
            'peor_casa': peor.get('casa_mercado'),
            'mejor_apuesta': (max(con, key=lambda r: r['dif_vs_mercado'])
                              .get('apuesta') if gana else None)}


def motor_solo_playdoit(motor, home: str, away: str, deporte: str = 'futbol',
                        fecha=None, liga: Optional[str] = None):
    """
    El motor con las cuotas de Playdoit y de nadie más, para armar combinadas
    que se puedan colocar de verdad en un solo ticket.

    Devuelve `(motor, n_mercados, detalle)`. Con `n_mercados = 0` la vista no
    debe enseñar la sección: significa que hoy Playdoit no cotiza este partido,
    y eso es más honesto que rellenarlo con cuota justa.
    """
    try:
        import cuotas_multi as cm
        det = cm.mercados_playdoit(deporte, home, away, fecha=fecha, liga=liga)
        if not det:
            return motor, 0, None
        pl = (motor.plantilla_club(home, away)
              if hasattr(motor, 'plantilla_club') else motor.plantilla(home, away))
        if not isinstance(pl, dict) or 'error' in pl:
            return motor, 0, None
        filas = mercados_playdoit_con_ev(det, pl, home, away)
        cuotas, casas = {}, {}
        for r in filas:
            cid = r.get('id')
            if not cid or not r.get('cuota_casa'):
                continue
            if cid not in cuotas or r['cuota_casa'] > cuotas[cid]:
                cuotas[cid] = float(r['cuota_casa'])
                casas[cid] = r.get('casa')
        if not cuotas:
            return motor, 0, det
        return MotorConTablon(motor, cuotas, casas), len(cuotas), det
    except Exception as e:
        logger.info(f'[playdoit] sin tablero para la combinada de una casa: '
                    f'{type(e).__name__}: {e}')
        return motor, 0, None


def adjuntar_a_plantilla(plantilla: Dict, res: Dict, home: str,
                         away: str) -> int:
    """
    Cuelga de la plantilla las cuotas REALES del tablón, por id de campo.

    Es el enganche que hace que el constructor de combinadas deje de razonar
    con cuotas justas. `match_parlay` armaba los parlays con `cuota = 1/prob`
    salvo para los pocos mercados que hubiera en `odds_actuales.json`, un
    fichero que escribe el pipeline una vez al día; con esto usa el precio que
    las casas publican AHORA, que es el que el usuario va a pagar.

    Importa para el resultado, no sólo para la presentación: con cuotas justas
    el EV de toda pata es 0 por construcción, así que el motor sólo podía
    ordenar por probabilidad. Con precio real puede ver qué pata paga de más —
    que es lo que el usuario pidió: «propón un parlay en base a las cuotas
    reales automáticas».

    Devuelve cuántos campos se han podido rellenar y escribe en la plantilla:
        pl['cuotas_tablon']      {id_campo: cuota}
        pl['casas_tablon']       {id_campo: casa que da ese precio}
    """
    if not isinstance(plantilla, dict):
        return 0
    try:
        filas = mercados_con_ev(res, plantilla, home, away)
    except Exception as e:
        logger.warning(f'[tablon] no se pudieron adjuntar cuotas: {e}')
        return 0
    cuotas, casas = {}, {}
    for r in filas:
        cid = r.get('id')
        if not cid or not r.get('cuota_casa'):
            continue
        # si el mismo id llega dos veces, manda el precio más alto: es el que
        # el usuario puede tomar de verdad (line shopping)
        if cid not in cuotas or r['cuota_casa'] > cuotas[cid]:
            cuotas[cid] = float(r['cuota_casa'])
            casas[cid] = r.get('casa')
    if cuotas:
        plantilla['cuotas_tablon'] = cuotas
        plantilla['casas_tablon'] = casas
    return len(cuotas)


class MotorConTablon:
    """
    El motor de la competición, pero con las cuotas del tablón enganchadas.

    `match_parlay` tiene tres constructores (`construir_parlay_partido`,
    `construir_parlay_con_resultado` y el `proponer_parlays` que los orquesta)
    y los tres piden la plantilla al motor por su cuenta. Envolver el motor
    resuelve los tres de una vez y sin añadir un parámetro que habría que ir
    pasando de función en función — y sin variables de módulo, que en una app
    con varias sesiones a la vez serían una fuente de datos cruzados.

    Todo lo que no sea pedir la plantilla se delega intacto.
    """

    def __init__(self, motor, cuotas: Dict, casas: Optional[Dict] = None):
        self._motor = motor
        self._cuotas = cuotas or {}
        self._casas = casas or {}

    def __getattr__(self, nombre):
        return getattr(self._motor, nombre)

    def _con_cuotas(self, pl):
        if isinstance(pl, dict) and self._cuotas:
            pl['cuotas_tablon'] = dict(self._cuotas)
            pl['casas_tablon'] = dict(self._casas)
        return pl

    def plantilla_club(self, *a, **kw):
        return self._con_cuotas(self._motor.plantilla_club(*a, **kw))

    def plantilla(self, *a, **kw):
        return self._con_cuotas(self._motor.plantilla(*a, **kw))


def motor_con_tablon(motor, home: str, away: str, deporte: str = 'futbol',
                     fecha=None, liga: Optional[str] = None):
    """
    Motor envuelto con el mejor precio real de cada mercado, o el motor tal
    cual si el tablón no da nada.

    Nunca lanza: sin red, sin partido en el tablón o sin cruce posible, se
    devuelve el motor original y las combinadas salen con cuota justa, que es
    exactamente lo que hacían antes.
    """
    try:
        import cuotas_multi as cm
        pl = (motor.plantilla_club(home, away)
              if hasattr(motor, 'plantilla_club') else motor.plantilla(home, away))
        if not isinstance(pl, dict) or 'error' in pl:
            return motor, 0
        res = cm.cuotas_partido(deporte, home, away, fecha=fecha, liga=liga)
        n = adjuntar_a_plantilla(pl, res, home, away)
        if not n:
            return motor, 0
        return MotorConTablon(motor, pl.get('cuotas_tablon'),
                              pl.get('casas_tablon')), n
    except Exception as e:
        logger.info(f'[tablon] sin cuotas en vivo para el parlay: '
                    f'{type(e).__name__}: {e}')
        return motor, 0


# Por encima de este EV, la explicación más probable NO es que haya valor.
#
# El proyecto lo tiene medido: el modelo no bate al mercado (4 de 37 ligas) y
# el EV que declara es ANTI-indicador del cierre (correlación −0,054 con el
# CLV). Un mercado líquido como el de Pinnacle no se equivoca un 40 %; el que
# se equivoca es el modelo. Ordenar por EV, sin más, pone arriba justo sus
# peores errores — que es lo contrario de lo que hace falta.
#
# Ejemplo real del 2026-08-09, Bodo/Glimt vs Union Saint-Gilloise:
#     «Menos de 1.5 goles» @ 5,40 · el modelo dice justa 2,47 → EV +118,7 %
# Pinnacle da un 18,5 % implícito y el modelo un 40 %. La diferencia no es una
# oportunidad de +118 %: es el modelo equivocándose en un mercado sharp.
EV_SOSPECHOSO = 0.30


def marcar_ev_sospechoso(filas: List[Dict]) -> List[Dict]:
    """Marca las filas cuyo EV es demasiado bueno para ser cierto."""
    for r in filas:
        r['ev_sospechoso'] = bool(
            (r.get('ev') or 0) > EV_SOSPECHOSO and (r.get('n_casas') or 1) <= 1)
    return filas


def recomendar_combinada(opciones: List[Dict],
                         mercados: Optional[List[Dict]] = None,
                         criterio: str = 'mercado') -> Optional[Dict]:
    """
    Cuál de las combinadas propuestas merece la pena, y POR QUÉ.

    El criterio NO es el EV. Lo que este proyecto ha medido positivo es
    comprar al mejor precio (+1,37 % de ROI sin modelo ninguno), y lo que ha
    medido negativo es apostar por la probabilidad del modelo (−4,66 % a
    −6,52 % en 37.158 apuestas). Así que se puntúa, por este orden:

      1. que las patas tengan precio comparado entre VARIAS casas — es la
         única ventaja medida, y sin dos precios no hay comparación;
      2. la probabilidad conjunta real (PFP), que es lo que decide si la
         combinada entra;
      3. la cuota, pero con peso bajo: subirla es fácil y siempre a costa de
         la probabilidad.

    Se penaliza el EV sospechoso (ver `EV_SOSPECHOSO`) en vez de premiarlo.

    v122 — `criterio='casa_unica'`
    ------------------------------
    Cuando la combinada se arma en UNA sola casa (la del usuario), el criterio
    de arriba se queda sin su primera pieza: no hay dos precios que comparar
    porque no hay dónde elegir. Medir «cuántas patas están comparadas» daría
    cero en todas y la recomendación se decidiría sola por probabilidad, que es
    justo el criterio que el proyecto tiene medido en negativo.

    Así que ahí se puntúa otra cosa, que sigue siendo precio y sigue siendo
    comprobable: **cuánto paga esa casa comparada con el mejor precio del
    mercado en el mismo mercado** (`dif_vs_mercado`, lo calcula
    `comparar_con_el_mercado`). Una pata donde Playdoit paga igual o más que
    Pinnacle es una pata bien comprada aunque sólo se pueda comprar en un
    sitio; una donde paga un 23 % menos es dinero que se deja encima de la
    mesa, y eso el usuario tiene derecho a verlo antes de poner el ticket.

    Devuelve la opción elegida con un campo `motivo_recomendacion` en texto
    llano, o None si ninguna reúne lo mínimo.
    """
    if not opciones:
        return None
    una_casa = (criterio == 'casa_unica')
    por_id = {m.get('id'): m for m in (mercados or []) if m.get('id')}
    mejor, mejor_score = None, -1e9
    for op in opciones:
        sels = op.get('selecciones') or []
        if not sels:
            continue
        pfp = float(op.get('prob_conjunta') or 0)
        cuota = float(op.get('cuota_combinada') or 1)
        n_reales = sum(1 for s in sels if s.get('cuota_fuente') == 'real')
        # cuántas patas tienen su precio comparado entre dos o más casas
        comparadas, ventaja = 0, 0.0
        sospechosas = 0
        # v122 — y, en el caso de una sola casa, cuánto se deja frente al
        # mejor precio del mercado en esas mismas patas
        n_dif, suma_dif, peor_dif, n_gana = 0, 0.0, None, 0
        for s in sels:
            m = por_id.get(s.get('id'))
            if not m:
                continue
            if (m.get('n_casas') or 1) >= 2:
                comparadas += 1
                ventaja += float(m.get('ventaja_line_shopping') or 0)
            if (m.get('ev') or 0) > EV_SOSPECHOSO and (m.get('n_casas') or 1) <= 1:
                sospechosas += 1
            # v123 — una pata de mitad con EV marcado como no fiable pesa lo
            # mismo que una sospechosa: su EV positivo viene de que al modelo
            # le falta el reparto de goles por mitad, no de que haya valor.
            elif m.get('ev_no_fiable') and (m.get('ev') or 0) > 0:
                sospechosas += 1
            d = m.get('dif_vs_mercado')
            if d is not None:
                n_dif += 1
                suma_dif += float(d)
                peor_dif = float(d) if peor_dif is None else min(peor_dif, float(d))
                if float(d) >= 0:
                    n_gana += 1
        frac_reales = n_reales / len(sels)
        frac_comp = comparadas / len(sels)
        if una_casa:
            # La media del diferencial es una fracción (−0,05 = un 5 % menos).
            # Se escala ×4 para que pese como pesaba `frac_comp`: un −5 % de
            # media resta 0,2 puntos, un −25 % resta 1,0 — que es tanto como
            # perder toda la ventaja del line shopping, y es correcto.
            media_dif = (suma_dif / n_dif) if n_dif else 0.0
            score = (4.0 * media_dif + 1.5 * frac_reales + 1.2 * pfp
                     + 0.25 * min(cuota, 6.0) / 6.0
                     - 0.8 * (sospechosas / len(sels)))
        else:
            score = (2.0 * frac_comp + 1.5 * frac_reales + 1.2 * pfp
                     + 0.25 * min(cuota, 6.0) / 6.0
                     - 0.8 * (sospechosas / len(sels)))
        if score > mejor_score:
            mejor, mejor_score = op, score
            mejor_meta = {'n_reales': n_reales, 'n_patas': len(sels),
                          'comparadas': comparadas, 'ventaja': ventaja,
                          'sospechosas': sospechosas, 'pfp': pfp,
                          'cuota': cuota, 'n_dif': n_dif, 'n_gana': n_gana,
                          'media_dif': (suma_dif / n_dif) if n_dif else None,
                          'peor_dif': peor_dif}
    if mejor is None:
        return None
    m = mejor_meta
    partes = []
    if m['n_reales'] == m['n_patas']:
        partes.append(
            (f"Las **{m['n_patas']} patas** tienen" if m['n_patas'] != 1
             else "**La única pata** tiene")
            + " precio publicado por una casa, así que la cuota combinada es "
              "la que vas a cobrar.")
    else:
        partes.append(
            f"**{m['n_reales']} de {m['n_patas']} patas** con precio "
            f"publicado; el resto va con cuota justa, que no es un precio que "
            f"puedas tomar.")
    if una_casa:
        partes.append(
            "Todas las patas son de **la misma casa**, así que esto es un "
            "ticket que puedes poner de verdad — no tres apuestas sueltas en "
            "tres sitios.")
        if m['n_dif']:
            _md = m['media_dif'] or 0.0
            _cuantas = (f"**{m['n_dif']} patas**" if m['n_dif'] != 1
                        else "**la única pata**")
            if _md >= 0:
                partes.append(
                    f"De {_cuantas} que se puede{'n' if m['n_dif'] != 1 else ''} "
                    f"comparar, tu casa paga de media un **{_md*100:+.1f} %** "
                    f"frente al mejor precio del resto del mercado: aquí no "
                    f"estás perdiendo nada por jugar donde juegas.")
            else:
                partes.append(
                    f"De {_cuantas} que se puede{'n' if m['n_dif'] != 1 else ''} "
                    f"comparar, tu casa paga de media un **{_md*100:.1f} %** "
                    f"respecto al mejor precio del mercado. Ése es el coste "
                    f"real de tener una sola cuenta, y es la cifra de esta "
                    f"pantalla que **no depende de que el modelo acierte**: "
                    f"son dos precios del mismo suceso.")
            if m['peor_dif'] is not None and m['peor_dif'] < -0.05:
                partes.append(
                    f"La pata peor comprada se deja un "
                    f"**{m['peor_dif']*100:.1f} %**. Si alguna vez abres una "
                    f"segunda cuenta, ésa es la clase de mercado por la que "
                    f"compensa.")
        else:
            partes.append(
                "Ninguna de estas patas tiene precio en otra casa con el que "
                "compararla, así que hoy no se puede decir si tu casa paga "
                "bien o mal en ellas. Es una combinada colocable, no una "
                "ventaja demostrada.")
    elif m['comparadas']:
        partes.append(
            f"**{m['comparadas']} de {m['n_patas']}** están comparadas entre "
            f"dos o más casas — la única ventaja que este proyecto tiene "
            f"medida con ROI positivo.")
    else:
        partes.append(
            "Ninguna pata tiene un segundo precio con el que compararse: las "
            "líneas alternativas hoy sólo las publica Pinnacle. Sin dos "
            "precios no hay line shopping, que es lo único que este proyecto "
            "mide en positivo — tómala como la más sólida de las disponibles, "
            "no como una ventaja demostrada.")
    partes.append(
        f"Probabilidad real de acertar todo: **{m['pfp']*100:.0f} %** a cuota "
        f"**{m['cuota']:.2f}**.")
    if m['ventaja'] > 0:
        partes.append(
            f"Comprando al mejor precio en vez de al peor se gana un "
            f"**{m['ventaja']*100:.1f} %** acumulado sobre estas patas.")
    # El aviso que más importa: si el EV conjunto sale disparado, lo que hay
    # es un modelo optimista, no una oportunidad. Se dice aquí y con el
    # número delante, no en letra pequeña.
    _ev_conj = m['pfp'] * m['cuota'] - 1
    if _ev_conj > 0.25:
        partes.append(
            f"⚠️ Ojo: {m['pfp']*100:.0f} % a cuota {m['cuota']:.2f} implica un "
            f"EV conjunto de **{_ev_conj*100:+.0f} %**. Ninguna combinada real "
            f"paga eso. Significa que el modelo da probabilidades bastante más "
            f"altas que las del mercado en estas patas, y el histórico del "
            f"proyecto dice que en esa discrepancia suele equivocarse él.")
    if m['sospechosas']:
        partes.append(
            f"⚠️ {m['sospechosas']} pata(s) con un EV superior al "
            f"{EV_SOSPECHOSO*100:.0f} % y una sola casa: eso casi siempre es "
            f"el modelo equivocándose, no valor. No es el motivo por el que "
            f"esta combinada se recomienda.")
    mejor = dict(mejor)
    mejor['motivo_recomendacion'] = partes
    return mejor


def resumen_line_shopping(res: Dict) -> Optional[str]:
    """
    Frase corta con lo que cuesta comprar en la casa equivocada.

    Sale del propio tablón, sin modelo: es la única cifra de esta pantalla que
    no depende de que el modelo acierte.
    """
    casas = {k: v for k, v in (res.get('casas') or {}).items()
             if not k.startswith('_')}
    if len(casas) < 2:
        return None
    peor_mejor = []
    for lado in ('home', 'draw', 'away'):
        precios = [c[lado] for c in casas.values()
                   if (c or {}).get(lado) and c[lado] > 1]
        if len(precios) >= 2 and min(precios) > 0:
            peor_mejor.append(max(precios) / min(precios) - 1)
    if not peor_mejor:
        return None
    return (f"Entre las {len(casas)} casas del tablón hay hasta un "
            f"**{max(peor_mejor)*100:.1f} %** de diferencia de precio en el "
            f"mismo resultado.")
