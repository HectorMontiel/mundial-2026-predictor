#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v106 — LA HORA DEL PARTIDO, EN HORA DE CIUDAD DE MÉXICO.

El problema
-----------
Las fuentes publican la hora de inicio y el proyecto ya la capturaba
(`fixtures_espn` y `mlb_statsapi` guardan `inicio` en UTC; `tenis_fuentes`
guarda `hora`, también UTC), pero **no llegaba a la pantalla**: la interfaz
enseñaba sólo la fecha. Para decidir qué apostar «casi en vivo, antes de que
empiece» hace falta la hora, y hace falta en la hora del usuario, no en UTC.

Por qué un módulo aparte, y qué NO hace
---------------------------------------
El proyecto tiene un invariante que un test vigila (`test_un_solo_reloj`):
TODO el barrido razona en UTC, porque las fechas de las fuentes son UTC y
mezclar relojes ya costó un día entero de partidos descartados (v91).

Este módulo NO toca ese reloj. Es exclusivamente de PRESENTACIÓN: recibe una
marca de tiempo UTC y devuelve texto para enseñar. La lógica de «qué partidos
son de hoy» sigue igual, en UTC, donde estaba validada.

Ojo con la fecha, que no es un detalle
--------------------------------------
CDMX va 6 horas por detrás de UTC, así que un partido de las 01:00 UTC del
sábado se juega el VIERNES a las 19:00 en México. Por eso `partes()` devuelve
también la fecha local: enseñar la hora de CDMX junto a la fecha UTC sería
peor que no enseñar nada.

México eliminó el horario de verano en 2022, pero no se codifica «UTC−6» a
mano: se usa la base de datos de zonas horarias (`America/Mexico_City`), que
es la que sabe qué pasó antes de 2022 y la que se actualizará sola si la regla
vuelve a cambiar. Si esa base no estuviera disponible en el entorno, se cae a
un desfase fijo de −6 h y se deja constancia en el log — degradación limpia:
una hora aproximada es mejor que ninguna, y peor que la correcta.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

ZONA = 'America/Mexico_City'
ETIQUETA = 'CDMX'
_RESPALDO = _dt.timezone(_dt.timedelta(hours=-6), 'CDMX(aprox)')
_TZ = None
_AVISADO = False


def _zona():
    """Zona de CDMX, con respaldo a UTC−6 fijo si falta la base de zonas."""
    global _TZ, _AVISADO
    if _TZ is not None:
        return _TZ
    try:
        from zoneinfo import ZoneInfo
        _TZ = ZoneInfo(ZONA)
    except Exception as e:
        if not _AVISADO:
            logger.warning(
                f"[horario] sin base de zonas horarias ({type(e).__name__}: "
                f"{e}); se usa UTC−6 fijo. Instala `tzdata` para la hora "
                f"exacta.")
            _AVISADO = True
        _TZ = _RESPALDO
    return _TZ


def _a_utc(valor) -> Optional[_dt.datetime]:
    """
    Normaliza a `datetime` con zona UTC lo que llega del pipeline:

      · 'YYYY-MM-DD HH:MM:SS'  (el `inicio` de fixtures_espn / mlb_statsapi)
      · 'YYYY-MM-DDTHH:MM:SSZ' y demás variantes ISO
      · datetime / pd.Timestamp, con zona o sin ella

    Sin zona = UTC, que es lo que el proyecto guarda. Devuelve None si no se
    puede leer: enseñar una hora inventada sería peor que no enseñarla.
    """
    if valor is None or valor == '':
        return None
    d = None
    if isinstance(valor, _dt.datetime):
        d = valor
    elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
        # epoch de Bovada. Hoy llega ya normalizado por
        # `cuotas_multi.fecha_normalizada`, pero si algún día una fuente entra
        # por otra puerta, más vale leerlo que devolver 1970: `pd.Timestamp`
        # interpreta un entero como NANOsegundos y ese error ya costó dos
        # versiones (v94 en tenis, v95 en MLB).
        try:
            if valor != valor or abs(valor) < 1e8:      # NaN o valor absurdo
                return None
            unidad = 1000.0 if abs(valor) > 1e11 else 1.0
            d = _dt.datetime.fromtimestamp(valor / unidad, _dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        txt = str(valor).strip()
        if not txt:
            return None
        if txt.endswith('Z'):
            txt = txt[:-1] + '+00:00'
        try:
            d = _dt.datetime.fromisoformat(txt)
        except ValueError:
            try:                       # último recurso: el lector de pandas
                import pandas as pd
                ts = pd.Timestamp(valor)
                if ts is None or str(ts) == 'NaT':
                    return None
                d = ts.to_pydatetime()
            except Exception:
                return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    if not (2000 <= d.year <= 2100):
        return None                    # la misma guardia que usa la interfaz
    return d.astimezone(_dt.timezone.utc)


def a_cdmx(valor) -> Optional[_dt.datetime]:
    """La misma marca de tiempo, expresada en hora de Ciudad de México."""
    d = _a_utc(valor)
    return None if d is None else d.astimezone(_zona())


def partes(valor) -> Optional[Tuple[str, str]]:
    """
    (fecha_local, hora_local) como ('2026-08-08', '19:00').

    La FECHA es la de CDMX, que puede no ser la fecha UTC guardada: un partido
    de las 01:00 UTC del sábado es del viernes por la noche en México.
    """
    d = a_cdmx(valor)
    return None if d is None else (d.strftime('%Y-%m-%d'), d.strftime('%H:%M'))


def hora(valor) -> str:
    """'19:00' — sólo la hora, sin adorno. Cadena vacía si no se puede leer."""
    p = partes(valor)
    return p[1] if p else ''


def fecha(valor) -> str:
    """'2026-08-08' — la fecha en CDMX. Cadena vacía si no se puede leer."""
    p = partes(valor)
    return p[0] if p else ''


def etiqueta(valor, con_fecha: bool = False) -> str:
    """
    Texto listo para la interfaz: '🕒 19:00 CDMX' (o con la fecha delante).
    Cadena vacía si la fuente no trajo hora, para que quien lo use pueda
    concatenar sin comprobar nada.
    """
    p = partes(valor)
    if not p:
        return ''
    f, h = p
    return f'🕒 {f} {h} {ETIQUETA}' if con_fecha else f'🕒 {h} {ETIQUETA}'


def falta_para(valor, ahora_utc=None) -> Optional[str]:
    """
    'empieza en 2 h 15 min' / 'empieza en 40 min' / 'ya empezó'.

    Es la mitad que le da sentido a la hora cuando se apuesta poco antes del
    inicio: la hora dice cuándo, esto dice cuánto queda. `ahora_utc` existe
    para poder probarlo sin depender del reloj de la máquina.
    """
    d = _a_utc(valor)
    if d is None:
        return None
    ahora = _a_utc(ahora_utc) if ahora_utc is not None else \
        _dt.datetime.now(_dt.timezone.utc)
    if ahora is None:
        return None
    seg = (d - ahora).total_seconds()
    if seg < -3 * 3600:
        return None                    # hace horas: ya no es información útil
    if seg <= 0:
        return 'ya empezó'
    horas, minutos = int(seg // 3600), int((seg % 3600) // 60)
    if horas >= 24:
        dias = horas // 24
        return f'empieza en {dias} d {horas % 24} h'
    if horas:
        return f'empieza en {horas} h {minutos:02d} min'
    return f'empieza en {minutos} min'


def anotar(fixture: dict, campo: str = 'inicio') -> dict:
    """
    Añade `hora_cdmx`, `fecha_cdmx` y `hora_txt` a un fixture o pick, in place.

    Se aplica en el borde de presentación (interfaz, Telegram, exportaciones):
    los campos internos `fecha`/`inicio` siguen intactos y en UTC, que es lo
    que el resto del sistema compara.
    """
    if not isinstance(fixture, dict):
        return fixture
    p = partes(fixture.get(campo))
    if p:
        fixture['fecha_cdmx'], fixture['hora_cdmx'] = p
        fixture['hora_txt'] = etiqueta(fixture.get(campo))
    return fixture
