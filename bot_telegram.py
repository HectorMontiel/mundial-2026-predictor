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
    cuota = p.get('cuota')
    if cuota:
        precio = (f"@ {cuota} (justa {p.get('cuota_justa','?')}) · "
                  f"EV {(p.get('ev') or 0)*100:+.1f}%")
    else:
        precio = f"sin cuota en vivo · mínima sugerida {p.get('cuota_justa','?')}"
    marca = '💠' if p.get('sharp_confirmado') else \
            ('⭐' if p.get('platino') else ('💎' if p.get('evc') else '•'))
    sharp = ' · 💠 confirmado sharp' if p.get('sharp_confirmado') else ''
    return (f"{marca} [{p.get('deporte','Fútbol')}] {p.get('partido','?')}\n"
            f"   {p.get('apuesta','?')} {precio} · prob "
            f"{(p.get('prob') or 0)*100:.0f}% {p.get('fiabilidad','')}{sharp}")


def construir_mensaje() -> str:
    import alpha_finder
    import reto_escalera
    r = alpha_finder.apuestas_del_dia_universal()
    lineas = [f"🎯 *APUESTAS DEL DÍA* — {r.get('actualizado', 'hoy')}",
              f"Deportes: {', '.join(r.get('deportes_cubiertos') or ['—'])}", ""]

    # v41: ALARMA de datos AL PRINCIPIO — distingue "no llegaron datos"
    # (problema) de "llegaron pero hoy no hay picks" (normal). El fallo del
    # runner sin ODDS_API_KEY salía como un mensaje vacío indistinguible.
    try:
        import data_health
        alarma = data_health.linea_alarma_telegram()
        if alarma:
            lineas.insert(0, alarma.strip())
    except Exception as e:
        logger.warning(f"data_health no disponible: {e}")

    pdd = r.get('pick_del_dia')
    if pdd:
        lineas += ["🥇 *PICK DEL DÍA*", _fmt_pick(pdd), ""]
    else:
        lineas += ["🥇 Hoy no hay Pick del Día que cumpla el listón "
                   "(confianza >80% y EV en rango). Mejor no forzarlo.", ""]

    capa1 = r.get('capa1') or []
    if capa1:
        lineas.append(f"💎 *CAPA 1 — con cuota real* ({len(capa1)})")
        lineas += [_fmt_pick(p) for p in capa1[:8]]
        lineas.append("")
    capa2 = r.get('capa2') or []
    if capa2:
        lineas.append(f"🎯 *CAPA 2 — alta confianza, sin cuota* ({len(capa2)})")
        lineas += [_fmt_pick(p) for p in capa2[:5]]
        lineas.append("")

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
