#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Envío automático del DÍA COMPLETO a Telegram: hoy y mañana.

Qué manda, y en qué se diferencia de `bot_telegram.py`
------------------------------------------------------
`bot_telegram.py` manda los PICKS: lo que pasa los filtros, que es lo que hay
que apostar. Esto manda el día ENTERO — todos los partidos de todos los
deportes con todos sus mercados (1X2, goles, BTTS, hándicap, ganador, primer
set, total de sets, córners, tarjetas y remates) y sus cuotas.

Va como fichero adjunto, no como mensajes, y eso está medido: un día real son
368 partidos y 5.951 mercados, unos 457 KB. A 3.900 caracteres por mensaje son
107 mensajes, y Telegram limita a ~20 por minuto en un chat.

POR QUÉ UN FICHERO PROPIO Y NO UN ARGUMENTO DE `bot_telegram.py`
----------------------------------------------------------------
El bloque `if __name__ == '__main__':` de `bot_telegram.py` está A MITAD del
fichero, con funciones definidas después. Añadirle una rama que llamara a
`texto_dia_completo` daría `NameError`, porque esa función todavía no existe
cuando ese bloque se ejecuta. Se deja el orden como está y el arranque vive
aquí.

Seguridad: el token y el chat_id salen EXCLUSIVAMENTE del entorno. Sin
credenciales imprime el resumen y termina con éxito (modo seco).

Uso:
    python bot_dia_completo.py              # hoy y mañana
    python bot_dia_completo.py --solo-hoy
    python bot_dia_completo.py --dry-run    # no envía, sólo imprime
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _imprimir(texto: str) -> None:
    """La consola de Windows usa cp1252 y los emojis del resumen la revientan
    ANTES de intentar el envío. Se imprime de forma tolerante."""
    try:
        print(texto)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(texto.encode('utf-8', 'replace') + b'\n')


def main() -> int:
    import bot_telegram as bt
    import mercados_dia as md

    seco = '--dry-run' in sys.argv
    dias = [(0, 'HOY')] if '--solo-hoy' in sys.argv else [(0, 'HOY'),
                                                          (1, 'MAÑANA')]

    try:
        import alpha_finder
        import guardia_barrido
        r = guardia_barrido.barrido(alpha_finder.apuestas_del_dia_universal)
    except Exception as e:
        logger.error('No se pudo calcular el barrido: %s: %s',
                     type(e).__name__, e)
        return 0            # nunca romper el workflow por un fallo de datos

    enviados = 0
    for desplazamiento, etiqueta in dias:
        dia = md.dia_cdmx(desplazamiento)
        try:
            partidos = md.partidos_del_dia(r, dia)
            texto = bt.texto_dia_completo(r, dia, True, partidos)
            pie = bt.resumen_dia_completo(r, dia, etiqueta, True, partidos)
        except Exception as e:
            logger.error('No se pudo construir el día %s: %s: %s', dia,
                         type(e).__name__, e)
            continue
        _imprimir(pie)
        logger.info('[dia-completo] %s (%s): %d KB, %d líneas', etiqueta, dia,
                    len(texto.encode('utf-8')) // 1024,
                    len(texto.splitlines()))
        if seco:
            continue
        if bt.enviar_documento(texto, f'apuestas_{dia}.txt', pie):
            enviados += 1
        elif bt.enviar(pie + "\n\n_No se pudo adjuntar el detalle completo._"):
            enviados += 1
    logger.info('[dia-completo] envíos completados: %d de %d', enviados,
                len(dias))
    return 0


if __name__ == '__main__':
    sys.exit(main())
