#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de Telegram — resumen diario de las Apuestas del Día (v33 §4).

Se ejecuta en GitHub Actions (no en Streamlit Cloud), así que no reinicia el
contenedor de la app ni depende de ella.

SEGURIDAD (§4.2): el token y el chat_id se leen EXCLUSIVAMENTE del entorno
(GitHub Secrets). Nunca se escriben en el código ni se registran en logs.
Sin credenciales, el script imprime el mensaje y termina con éxito (modo
seco), para poder probar el formato sin exponer nada.

Uso:
    python bot_telegram.py            # envía si hay credenciales; si no, imprime
    python bot_telegram.py --dry-run  # solo imprime
"""

import logging
import os
import sys
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MAX_LEN = 3900          # límite práctico de Telegram (4096)


def _fmt_pick(p: dict) -> str:
    import traductor_quant as tq
    cuota = p.get('cuota')
    if cuota:
        precio = (f"@ {cuota} (justa {p.get('cuota_justa','?')}) · "
                  f"EV {(p.get('ev') or 0)*100:+.1f}%")
    else:
        precio = f"sin cuota en vivo · mínima sugerida {p.get('cuota_justa','?')}"
    marca = '🔥' if p.get('sharp_confirmado') else \
            ('⭐' if p.get('platino') else ('💎' if p.get('evc') else '•'))
    extras = []
    # v47: sharp en lenguaje llano (el usuario pidió que "+6% sobre Pinnacle"
    # deje de ser jerga técnica)
    if p.get('sharp_confirmado'):
        extras.append(tq.sello_sharp(p.get('sharp_gap')))
    if p.get('casa'):
        extras.append(f"🏠 mejor cuota en {p['casa']}")   # v43 line shopping
    cola = ('\n   ' + ' · '.join(extras)) if extras else ''
    # v47: tenis — desglose de mercados derivados para parlays
    mts = p.get('mercados_tenis') or []
    if mts:
        top = sorted(mts, key=lambda c: -c['valor'])[:5]
        cola += "\n   🎾 " + " · ".join(f"{c['etiqueta']} {c['valor']:.0f}%" for c in top)
    if p.get('nota_seleccion'):
        cola += f"\n   ℹ️ {p['nota_seleccion']}"
    # v106 — LA HORA, EN HORA DE CDMX. El mensaje decía qué apostar pero no
    # cuándo se juega, que es lo primero que hace falta al leerlo en el móvil.
    # `hora_cdmx` lo anota `alpha_finder` al cerrar el barrido; si la fuente no
    # publicó hora, no se escribe nada (nunca una hora inventada).
    _cuando = (f" · 🕒 {p.get('hora_cdmx')} CDMX" if p.get('hora_cdmx') else '')
    return (f"{marca} [{p.get('deporte','Fútbol')}] {p.get('partido','?')}"
            f"{_cuando}\n"
            f"   {p.get('apuesta','?')} {precio} · prob "
            f"{(p.get('prob') or 0)*100:.0f}% {p.get('fiabilidad','')}{cola}")


def _guia_simple(r: dict) -> str:
    """v43: una recomendación en lenguaje llano de por dónde empezar — el pick
    más seguro y confirmado del día, para el usuario que no quiere analizar."""
    capa1 = r.get('capa1') or []
    # preferimos el confirmado por sharp; si no, el de mayor prob de la capa 1
    conf = [p for p in capa1 if p.get('sharp_confirmado')]
    cand = (sorted(conf, key=lambda p: -(p.get('prob') or 0))
            or sorted(capa1, key=lambda p: -(p.get('prob') or 0)))
    if not cand:
        btts = r.get('btts_destacado') or []
        cand = sorted(btts, key=lambda p: -(p.get('prob') or 0))
    if not cand:
        return ""
    p = cand[0]
    porque = ("la línea sharp de Pinnacle lo confirma" if p.get('sharp_confirmado')
              else f"el modelo le da {(p.get('prob') or 0)*100:.0f}% de acierto")
    casa = f" en {p['casa']}" if p.get('casa') else ""
    return (f"👉 *{p.get('apuesta','?')}* ({p.get('partido','?')}) "
            f"@ {p.get('cuota','?')}{casa} — {porque}.")


def construir_mensaje(resultado: Optional[dict] = None) -> str:
    """
    Resumen del día para Telegram.

    v88 — `resultado` permite pasar un barrido YA calculado, y por defecto se
    pide por el guardia de proceso en vez de llamar a `alpha_finder` a pelo.

    Por qué: este módulo nació para el runner de GitHub Actions, donde es lo
    único que corre. Pero el botón «Enviar a Telegram» del dashboard también lo
    llama, y ahí el barrido YA está en memoria. Llamar otra vez a
    `apuestas_del_dia_universal()` lanzaba un SEGUNDO barrido completo dentro
    del proceso de Streamlit:

        1 barrido  -> pico de 1.297,7 MB
        2 barridos -> pico de 2.172,2 MB      (medido en _v86_barrido_concurrente)

    y el contenedor moría. Ése era el «se cae al enviar a Telegram»: no fallaba
    el envío, fallaba la memoria de rehacer el trabajo.
    """
    import reto_escalera
    if resultado is not None:
        r = resultado
    else:
        import alpha_finder
        import guardia_barrido
        r = guardia_barrido.barrido(alpha_finder.apuestas_del_dia_universal)
    lineas = [f"🎯 *APUESTAS DEL DÍA* — {r.get('actualizado', 'hoy')}",
              f"Deportes: {', '.join(r.get('deportes_cubiertos') or ['—'])}", ""]

    # v41: ALARMA de datos AL PRINCIPIO — distingue "no llegaron datos"
    # (problema) de "llegaron pero hoy no hay picks" (normal). El fallo del
    # runner sin ODDS_API_KEY salía como un mensaje vacío indistinguible.
    # v61: la alarma solo se muestra si el barrido NO produjo picks. Con las
    # cuotas de ESPN (v52) puede no haber captura propia y aun así haber Capa 1
    # perfectamente válida: avisar entonces sería una FALSA alarma.
    try:
        import data_health
        hay_picks = bool((r.get('capa1') or []) or (r.get('capa2') or []))
        alarma = data_health.linea_alarma_telegram()
        # v91: `sin_captura_odds` murió con el camino de The Odds API — la
        # única distinción que queda es la real: hay picks o no los hay.
        if alarma and not hay_picks:
            lineas.insert(0, alarma.strip())
    except Exception as e:
        logger.warning(f"data_health no disponible: {e}")

    pdd = r.get('pick_del_dia')
    if pdd:
        lineas += ["🥇 *PICK DEL DÍA*", _fmt_pick(pdd), ""]
    else:
        lineas += ["🥇 Hoy no hay Pick del Día que cumpla el listón "
                   "(confianza >80% y EV en rango). Mejor no forzarlo.", ""]

    # v89 — el barrido ahora cubre la SEMANA completa: para que el mensaje del
    # día no se llene de picks del sábado, los de HOY van primero y el resto
    # por fecha (sin perder ninguno del recuento).
    def _hoy_primero(picks):
        return sorted(picks, key=lambda p: (not p.get('es_hoy'),
                                            str(p.get('fecha', ''))))

    capa1 = _hoy_primero(r.get('capa1') or [])
    if capa1:
        lineas.append(f"💎 *CAPA 1 — con cuota real* ({len(capa1)})")
        lineas += [_fmt_pick(p) for p in capa1[:8]]
        lineas.append("")
    # v47: si la Capa 1 quedó vacía, mostramos la Selección del día para que
    # el usuario nunca vea un panel sin recomendaciones accionables.
    seleccion = _hoy_primero(r.get('seleccion_dia') or [])
    if not capa1 and seleccion:
        lineas.append(f"⭐ *SELECCIÓN DEL DÍA — mejor valor* ({len(seleccion)})")
        lineas += [_fmt_pick(p) for p in seleccion[:6]]
        lineas.append("")

    capa2 = _hoy_primero(r.get('capa2') or [])
    if capa2:
        lineas.append(f"🎯 *CAPA 2 — alta confianza, sin cuota* ({len(capa2)})")
        lineas += [_fmt_pick(p) for p in capa2[:5]]
        lineas.append("")

    # v47: PARLAY DEL DÍA DE TENIS — combinación contundente de mercados seguros
    tp = r.get('tenis_parlay') or {}
    if tp.get('patas'):
        lineas.append(f"🎾 *PARLAY DEL DÍA (TENIS)* — cuota {tp['cuota_combinada']} · "
                      f"prob {tp['prob_conjunta']*100:.0f}%")
        for p in tp['patas']:
            lineas.append(f"   • [{p['circuito']}] {p['partido']}: {p['mercado']} "
                          f"({p['prob']*100:.0f}%)")
        lineas.append("")

    # v43: sección ⚽ AMBOS MARCAN destacada (el usuario la prioriza — buen
    # momio y alta certeza para los parlays)
    btts = r.get('btts_destacado') or []
    if btts:
        lineas.append(f"⚽ *AMBOS MARCAN (BTTS)* ({len(btts)}) — buen momio, base de parlay")
        lineas += [_fmt_pick(p) for p in btts[:6]]
        lineas.append("")

    # v43: guía SIMPLE de "por cuál apostar" — la mejor pata segura del día
    guia = _guia_simple(r)
    if guia:
        lineas += ["🧭 *¿POR CUÁL EMPEZAR?*", guia, ""]

    esc = reto_escalera.construir(capa1 + capa2, capital=100)
    if esc.get('picks'):
        sim = esc['simulacion']
        lineas += [f"🪜 *RETO ESCALERA* — {esc['n_picks']} picks · "
                   f"prob conjunta {esc['prob_conjunta']*100:.0f}% · "
                   f"cuota {esc['cuota_combinada']:.2f}",
                   f"   Ruina a 10 días: {sim['prob_ruina_10d']*100:.0f}%", ""]
    else:
        lineas += ["🪜 Escalera: hoy no hay picks ≥85% — no se fuerza.", ""]

    if r.get('ev_extremo'):
        lineas.append(f"⚠️ {len(r['ev_extremo'])} picks de EV extremo "
                      "excluidos (histórico: aciertan 15 pp por debajo).")
    lineas.append("\n_Juego responsable. Cuota justa = 1/probabilidad._")
    texto = '\n'.join(lineas)
    return texto[:MAX_LEN]


def enviar(texto: str) -> bool:
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        logger.warning("Sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID en el entorno: "
                       "modo seco (no se envía nada).")
        return False
    import requests
    r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                      json={'chat_id': chat_id, 'text': texto,
                            'parse_mode': 'Markdown',
                            'disable_web_page_preview': True}, timeout=30)
    if r.ok:
        logger.info("Mensaje enviado a Telegram.")
        return True
    # nunca registrar el token: solo el código y el motivo
    logger.error(f"Telegram respondió {r.status_code}: "
                 f"{r.json().get('description', '?') if r.headers.get('content-type','').startswith('application/json') else 'error'}")
    return False


if __name__ == '__main__':
    try:
        mensaje = construir_mensaje()
    except Exception as e:
        logger.error(f"No se pudo construir el resumen: {type(e).__name__}: {e}")
        sys.exit(0)          # nunca romper el workflow por un fallo de datos
    # v35 (§4): la consola de Windows usa cp1252 y los emojis del resumen
    # reventaban el print ANTES de intentar el envío (el mensaje sí es UTF-8
    # válido y Telegram lo acepta). Se imprime de forma tolerante.
    try:
        print(mensaje)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(mensaje.encode('utf-8', 'replace') + b'\n')
    if '--dry-run' not in sys.argv:
        enviar(mensaje)


# ---------------------------------------------------------------------------
# v62 — envío de las COMBINADAS PROPUESTAS de un partido concreto. Lo usa el
# botón «Enviar estos parlays a Telegram» de la ficha del partido, que existe
# en todas las ligas y deportes (fútbol, MLB, tenis, internacional...).
# ---------------------------------------------------------------------------
def formatear_parlays(partido: str, opciones: list, competicion: str = '') -> str:
    """Mensaje Markdown con las combinadas propuestas de UN partido."""
    cab = f"🎲 *PARLAYS PROPUESTOS* — {partido}"
    if competicion:
        cab += f"\n_{competicion}_"
    lineas = [cab, ""]
    for op in opciones:
        prob = (op.get('prob_conjunta') or 0) * 100
        cuota = op.get('cuota_combinada') or 1
        lineas.append(f"{op.get('etiqueta_opcion', '•')} · "
                      f"{op.get('n_selecciones', len(op.get('selecciones', [])))} patas "
                      f"· prob *{prob:.0f}%* · cuota *{cuota:.2f}*")
        for s in op.get('selecciones', []):
            real = ' (cuota real)' if s.get('cuota_fuente') == 'real' else ''
            lineas.append(f"   • {s.get('apuesta', '?')} @ {s.get('cuota', '?')} "
                          f"· {(s.get('prob') or 0)*100:.0f}%{real}")
        if op.get('ev_parlay'):
            lineas.append(f"   EV: {op['ev_parlay']:+.3f}")
        lineas.append("")
    lineas.append("_Cuotas justas = 1/probabilidad si no se indica lo "
                  "contrario. Compara con tu casa. Juego responsable._")
    return '\n'.join(lineas)[:MAX_LEN]


def enviar_parlays(partido: str, opciones: list, competicion: str = '') -> bool:
    """Formatea y envía las combinadas del partido. Devuelve False (sin
    excepción) si faltan credenciales, para que la UI muestre la vista previa."""
    return enviar(formatear_parlays(partido, opciones, competicion))


# ---------------------------------------------------------------------------
# v124 — MEJORA 7: los picks de EV+ automático, a Telegram.
#
# El botón de envío existía sólo para las combinadas de un partido. Pero la
# pantalla que el usuario mira antes de un partido de MLB o de tenis es la de
# EV+ automático, y de ahí no había forma de sacar nada al teléfono: había que
# copiarlo a mano.
#
# El mensaje lleva la MISMA advertencia que la pantalla, y no por prudencia
# formal: un pick con EV positivo del modelo y una sola casa es, con lo que
# este proyecto tiene medido, el modelo equivocándose (ver
# BITACORA_ARQUITECTURA.md §0). Un mensaje de Telegram se lee fuera de
# contexto, así que el aviso tiene que viajar con él.
# ---------------------------------------------------------------------------
def formatear_picks(titulo: str, picks: list, nota: str = '') -> str:
    """
    Mensaje Markdown con una lista de picks (capa 1 o capa 2 de cualquier
    deporte).

    Cada línea lleva el precio y la casa, que es lo accionable, y la
    probabilidad al lado. El EV va detrás a propósito: es el dato menos fiable
    de los tres.
    """
    lineas = [f"💰 *{titulo}*", ""]
    if not picks:
        lineas.append("_Hoy no hay ningún pick que pase los filtros. "
                      "Cero picks no es un fallo: es que las casas y el modelo "
                      "coinciden._")
        return '\n'.join(lineas)[:MAX_LEN]
    for p in picks:
        cuota = p.get('cuota')
        precio = (f"@ *{cuota}*" if cuota
                  else f"sin cuota abierta (mínima {p.get('cuota_justa', '?')})")
        linea = (f"• {p.get('partido', '?')}\n"
                 f"   {p.get('apuesta', '?')} {precio}")
        if p.get('casa'):
            linea += f" · {p['casa']}"
        _pr = p.get('prob_calibrada')
        _pr = _pr if _pr is not None else p.get('prob')
        if _pr is not None:
            linea += f"\n   acierta {float(_pr)*100:.0f}%"
        if p.get('ev') is not None:
            linea += f" · EV {float(p['ev'])*100:+.1f}%"
        if p.get('hora_txt'):
            linea += f" · {p['hora_txt']}"
        lineas.append(linea)
    if nota:
        lineas += ["", f"_{nota}_"]
    lineas += ["", "_El EV sale de la probabilidad del modelo, y este proyecto "
                   "tiene medido que apostar por ella pierde entre 4,7 % y "
                   "6,5 %. Lo que sí mide positivo es comprar al mejor precio. "
                   "Juego responsable._"]
    return '\n'.join(lineas)[:MAX_LEN]


def enviar_picks(titulo: str, picks: list, nota: str = '') -> bool:
    """Formatea y envía una lista de picks. False si faltan credenciales."""
    return enviar(formatear_picks(titulo, picks, nota))


# ---------------------------------------------------------------------------
# v124 — MEJORA 8: la sección de ponches, entera.
#
# «Entera» es la palabra que importa: el usuario pidió poder mandarla completa,
# no un resumen. Así que van todos los lanzadores con su línea, su precio y su
# probabilidad, y se corta sólo si Telegram no admite más (4.096 caracteres),
# diciéndolo.
# ---------------------------------------------------------------------------
def formatear_ponches(filas: list, titulo: str = 'PONCHES DEL DÍA',
                      nota: str = '') -> str:
    """Mensaje Markdown con la tabla de ponches de MLB al completo."""
    lineas = [f"⚾ *{titulo}*", ""]
    if not filas:
        lineas.append("_Hoy no hay props de ponches abiertos. Las casas los "
                      "publican el mismo día del partido y en tandas._")
        return '\n'.join(lineas)[:MAX_LEN]
    for f in filas:
        cab = f"• *{f.get('lanzador', '?')}*"
        if f.get('equipo'):
            cab += f" ({f['equipo']})"
        if f.get('partido'):
            cab += f"\n   {f['partido']}"
        det = []
        if f.get('linea') is not None:
            det.append(f"línea {f['linea']}")
        if f.get('cuota'):
            det.append(f"@ {f['cuota']}")
        if f.get('casa'):
            det.append(str(f['casa']))
        if det:
            cab += "\n   " + ' · '.join(det)
        sub = []
        if f.get('prob') is not None:
            sub.append(f"P(más) {float(f['prob'])*100:.0f}%")
        if f.get('ev') is not None:
            sub.append(f"EV {float(f['ev'])*100:+.1f}%")
        if f.get('recomendacion'):
            sub.append(str(f['recomendacion']))
        if sub:
            cab += "\n   " + ' · '.join(sub)
        lineas.append(cab)
    if nota:
        lineas += ["", f"_{nota}_"]
    lineas += ["", "_La probabilidad de ponches está calibrada sobre el "
                   "histórico de cada abridor; el EV depende además de que la "
                   "línea de la casa sea la que se ve. Juego responsable._"]
    txt = '\n'.join(lineas)
    if len(txt) > MAX_LEN:
        txt = txt[:MAX_LEN - 80].rsplit('\n', 1)[0]
        txt += f"\n\n_… recortado: no cabían los {len(filas)} lanzadores en un "
        txt += "solo mensaje de Telegram._"
    return txt


def enviar_ponches(filas: list, titulo: str = 'PONCHES DEL DÍA',
                   nota: str = '') -> bool:
    """Formatea y envía la sección de ponches entera."""
    return enviar(formatear_ponches(filas, titulo, nota))


# ---------------------------------------------------------------------------
# EL DÍA ENTERO, NO SÓLO LOS PICKS.
#
# El envío de arriba manda lo que pasa los filtros: el Pick del Día, la Capa 1,
# la Capa 2. Es lo que hay que apostar. El usuario pidió además poder mandar
# el día COMPLETO —todos los deportes, todos los partidos y todas las métricas,
# no sólo el ganador— y el de mañana igual.
#
# POR QUÉ VA COMO DOCUMENTO Y NO COMO MENSAJES
# --------------------------------------------
# Medido sobre un día real (2026-09-15): 368 partidos y 5.951 mercados, unos
# 407 KB de texto. A 3.900 caracteres por mensaje son **107 mensajes**, y
# Telegram limita a ~20 por minuto en un chat: el envío tardaría seis minutos,
# llenaría la conversación y se cortaría a la mitad por límite de frecuencia.
#
# Un documento adjunto entra de una vez, se lee entero en el móvil y se puede
# buscar dentro. Así que va un mensaje corto con el resumen y el día completo
# adjunto. Si el adjunto falla, se manda al menos el resumen y se dice que la
# lista no cabía — nunca un silencio.
# ---------------------------------------------------------------------------
MAX_CAPTION = 1000          # límite de Telegram para el pie de un adjunto


def _linea_mercado(m: dict) -> str:
    """Una fila de mercado en texto plano, con lo accionable delante."""
    prob = m.get('prob')
    izq = f"      {m.get('etiqueta', '?')}"
    trozos = []
    if prob is not None:
        trozos.append(f"{float(prob)*100:.1f}%")
    if m.get('cuota'):
        precio = f"@ {m['cuota']}"
        if m.get('casa'):
            precio += f" ({m['casa']})"
        trozos.append(precio)
    if m.get('ev') is not None:
        trozos.append(f"EV {float(m['ev'])*100:+.1f}%")
    if m.get('cuota_justa'):
        trozos.append(f"justa {m['cuota_justa']}")
    cola = ' · '.join(trozos)
    nota = m.get('nota') or ''
    if not cola and nota:
        # una media («9,9 córners») no tiene probabilidad ni precio: la nota ES
        # el dato, así que va en la misma línea y no colgando debajo
        return f"{izq}: {nota}"
    linea = f"{izq}{'  ' + cola if cola else ''}"
    if nota:
        linea += f"\n         {nota}"
    return linea


def texto_dia_completo(r: dict, dia: Optional[str] = None,
                       con_extras: bool = True,
                       partidos: Optional[list] = None) -> str:
    """El día entero en texto plano: cada partido con todos sus mercados.

    `r` es un barrido YA calculado. No se lanza uno nuevo aquí por la misma
    razón que en `construir_mensaje`: un segundo barrido dentro del proceso de
    Streamlit sube el pico de memoria de 1.297 MB a 2.172 MB y mata el
    contenedor.
    """
    import mercados_dia as md
    dia = dia or md.dia_cdmx()
    # `partidos` permite construir el documento y su resumen de UNA sola
    # pasada: rehacerlo cuesta 3,1 s por los cornrs, las tarjetas y los
    # remates de los 42 partidos de futbol, y no cambia nada entre las dos.
    if partidos is None:
        partidos = md.partidos_del_dia(r, dia, con_extras=con_extras)

    lineas = [f"APUESTAS COMPLETAS DEL {dia} (hora de Ciudad de México)",
              "=" * 62, ""]
    if not partidos:
        lineas.append("No hay ningún partido con pronóstico para ese día.")
        return '\n'.join(lineas)

    por_deporte: dict = {}
    for p in partidos:
        por_deporte.setdefault(p['deporte'], []).append(p)

    for deporte in sorted(por_deporte):
        grupo = por_deporte[deporte]
        n_mer = sum(len(x['mercados']) for x in grupo)
        lineas += ["", "#" * 62,
                   f"# {deporte.upper()} — {len(grupo)} partidos, "
                   f"{n_mer} mercados", "#" * 62]
        for p in grupo:
            cab = f"\n{p['hora'] or '--:--'}  {p['partido']}"
            if p.get('liga'):
                cab += f"   [{p['liga']}]"
            if p.get('superficie'):
                cab += f"   {p['superficie']}"
            lineas.append(cab)
            if p.get('fiabilidad'):
                lineas.append(f"      {p['fiabilidad']}")
            categorias: dict = {}
            for m in p['mercados']:
                categorias.setdefault(m['categoria'], []).append(m)
            for cat in categorias:
                ms = categorias[cat]
                marca = ' (informativo, sin EV)' if all(
                    x.get('informativo') for x in ms) else ''
                lineas.append(f"   · {cat}{marca}")
                lineas += [_linea_mercado(m) for m in ms]
            for nota in (p.get('notas') or []):
                lineas.append(f"   ! {nota}")

    # Las combinadas también son apuestas del día, y el barrido ya las trae
    # montadas. Sólo salen en el documento de HOY: las del barrido se arman
    # con los picks del día y meterlas en el de mañana sería enseñar patas
    # que ya se habrán jugado.
    if dia == md.dia_cdmx():
        combis = [c for c in (r.get('combinadas') or []) if c.get('patas')]
        if combis:
            lineas += ["", "#" * 62,
                       f"# COMBINADAS PROPUESTAS ({len(combis)})", "#" * 62]
            for c in combis:
                lineas.append(
                    f"\n{c.get('perfil', 'combinada')} · "
                    f"{c.get('n_patas', len(c['patas']))} patas · "
                    f"prob {(c.get('prob_conjunta') or 0)*100:.0f}% · "
                    f"cuota {c.get('cuota_total', '?')}"
                    + (f" · EV {(c.get('ev') or 0)*100:+.1f}%"
                       if c.get('ev') is not None else ''))
                if c.get('descripcion'):
                    lineas.append(f"      {c['descripcion']}")
                for pata in c['patas']:
                    lineas.append(
                        f"      • [{pata.get('deporte', '?')}] "
                        f"{pata.get('partido', '?')}: {pata.get('apuesta', '?')}"
                        f"  {(pata.get('prob') or 0)*100:.0f}%"
                        + (f" @ {pata['cuota']}" if pata.get('cuota') else '')
                        + (f" ({pata['casa']})" if pata.get('casa') else ''))
                if c.get('supuesto'):
                    lineas.append(f"      ! {c['supuesto']}")

        tp = r.get('tenis_parlay') or {}
        if tp.get('patas'):
            lineas += ["", "#" * 62, "# PARLAY DE TENIS", "#" * 62,
                       f"\n{tp.get('n_patas', len(tp['patas']))} patas · "
                       f"prob {(tp.get('prob_conjunta') or 0)*100:.0f}% · "
                       f"cuota {tp.get('cuota_combinada', '?')}"]
            for pata in tp['patas']:
                lineas.append(f"      • [{pata.get('circuito', '?')}] "
                              f"{pata.get('partido', '?')}: "
                              f"{pata.get('mercado', '?')}  "
                              f"{(pata.get('prob') or 0)*100:.0f}%"
                              + (f" · justa {pata['cuota_justa']}"
                                 if pata.get('cuota_justa') else ''))
            if tp.get('nota'):
                lineas.append(f"      ! {tp['nota']}")

    lineas += ["", "=" * 62,
               "CÓMO LEER ESTO",
               "- La cuota y la casa sólo aparecen donde puedes apostar de "
               "verdad: Playdoit o Novibet. Las demás casas se leen para "
               "calcular el precio justo, no para ofrecerte nada.",
               "- 'justa' es 1/probabilidad: por debajo de esa cuota, la "
               "apuesta pierde valor aunque el pronóstico acierte.",
               "- Córners, tarjetas y remates van SIN EV a propósito: el "
               "modelo ordena bien los partidos pero su nivel va alto, y "
               "cruzarlo contra la cuota fabricaría un valor que no existe.",
               "- El total de sets del tenis se publica sin precio porque "
               "ninguna de las casas que se leen cotiza esa línea.",
               "- Juego responsable."]
    return '\n'.join(lineas)


def resumen_dia_completo(r: dict, dia: Optional[str] = None,
                         etiqueta: str = '', con_extras: bool = True,
                         partidos: Optional[list] = None) -> str:
    """El mensaje corto que acompaña al adjunto: qué lleva y qué destaca."""
    import mercados_dia as md
    dia = dia or md.dia_cdmx()
    if partidos is None:
        partidos = md.partidos_del_dia(r, dia, con_extras=con_extras)
    n_mer = sum(len(p['mercados']) for p in partidos)
    por_deporte: dict = {}
    for p in partidos:
        por_deporte.setdefault(p['deporte'], []).append(p)

    titulo = f"📋 *TODAS LAS APUESTAS — {etiqueta or dia}*" if etiqueta else \
             f"📋 *TODAS LAS APUESTAS — {dia}*"
    lineas = [titulo]
    if not partidos:
        lineas.append("_No hay ningún partido con pronóstico para ese día._")
        return '\n'.join(lineas)[:MAX_CAPTION]
    lineas.append(f"{len(partidos)} partidos · {n_mer} mercados")
    lineas.append(' · '.join(f"{d} {len(v)}"
                             for d, v in sorted(por_deporte.items())))

    # lo accionable: los mercados con precio en tus casas y EV positivo
    con_valor = [(p, m) for p in partidos for m in p['mercados']
                 if m.get('cuota') and (m.get('ev') or 0) > 0]
    con_valor.sort(key=lambda pm: -(pm[1].get('ev') or 0))
    if con_valor:
        lineas += ["", f"Con precio en tus casas y EV positivo: "
                       f"{len(con_valor)}"]
        for p, m in con_valor[:4]:
            lineas.append(f"• {p['partido']} — {m['etiqueta']} @ {m['cuota']}"
                          + (f" ({m['casa']})" if m.get('casa') else '')
                          + f" · EV {float(m['ev'])*100:+.1f}%")
    else:
        lineas += ["", "_Ningún mercado con precio en Playdoit o Novibet y EV "
                       "positivo. Cero no es un fallo: es que las casas y el "
                       "modelo coinciden._"]
    lineas.append("")
    lineas.append("_El detalle completo va en el fichero adjunto._")
    return '\n'.join(lineas)[:MAX_CAPTION]


def enviar_documento(texto: str, nombre: str, pie: str = '') -> bool:
    """Manda `texto` como fichero adjunto. False si faltan credenciales."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        logger.warning("Sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID en el "
                       "entorno: modo seco (no se envía nada).")
        return False
    import requests
    datos = {'chat_id': chat_id}
    if pie:
        datos['caption'] = pie[:MAX_CAPTION]
        datos['parse_mode'] = 'Markdown'
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendDocument',
        data=datos,
        files={'document': (nombre, texto.encode('utf-8'), 'text/plain')},
        timeout=90)
    if r.ok:
        logger.info("Documento enviado a Telegram (%d KB).",
                    len(texto.encode('utf-8')) // 1024)
        return True
    # nunca registrar el token: sólo el código y el motivo
    logger.error("Telegram respondió %s al adjunto: %s", r.status_code,
                 (r.json().get('description', '?')
                  if r.headers.get('content-type', '').startswith(
                      'application/json') else 'error'))
    return False


def enviar_dia_completo(r: dict, dia: Optional[str] = None,
                        etiqueta: str = '', con_extras: bool = True) -> bool:
    """Resumen al chat y el día entero como adjunto.

    Devuelve True sólo si algo llegó. Si el adjunto falla pero el resumen sale,
    también es True y el resumen dice que la lista no cabía: un envío a medias
    se ve, un silencio no.
    """
    import mercados_dia as md
    dia = dia or md.dia_cdmx()
    partidos = md.partidos_del_dia(r, dia, con_extras=con_extras)
    texto = texto_dia_completo(r, dia, con_extras, partidos)
    pie = resumen_dia_completo(r, dia, etiqueta, con_extras, partidos)
    nombre = f"apuestas_{dia}.txt"
    if enviar_documento(texto, nombre, pie):
        return True
    aviso = (pie + "\n\n_No se pudo adjuntar el detalle completo; abre la app "
                   "para verlo._")
    return enviar(aviso)
