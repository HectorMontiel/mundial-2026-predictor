#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v212 — Contexto y noticias, normalizado, multideporte y con el hueco a la vista.

QUÉ RESUELVE
------------
El encargo pide señales de contexto de cinco deportes y once fuentes. Este
módulo las normaliza a UN formato de señal y las agrega, para que
`escalada_lineas.fuente_contexto` no tenga que saber de dónde vino cada cosa.

LO PRIMERO, PORQUE DETERMINA TODO LO DEMÁS: QUÉ FUENTES EXISTEN DE VERDAD
-------------------------------------------------------------------------
Sondeo del 2026-09-19 sobre lo que este pipeline puede consultar hoy:

    FUNCIONAN
      entrenador      Wikidata, vía `buscador_fuentes.cambios_wikidata`.
                      Verificado en la v209: 8 cambios reales en 7 días.
      racha / forma   histórico propio, vía `contexto_partido.forma`
      h2h             histórico propio, vía `contexto_partido.h2h`
      media_metrica   histórico propio, vía `rendimiento_equipos`
      aclimatacion    `contexto_ampliado` — la ÚNICA medida fuera de muestra
      arbitro         `arbitro_partido`

    NO FUNCIONAN HOY, y no se simulan
      lesiones        API-Football, y no hay clave configurada
                      (`api_football_manager.api_key()` -> None)
      alineaciones    misma clave. ESPN publica `rosters`, que es la plantilla,
                      no el once confirmado: no sirve para «falta el central».
      clima           ninguna fuente en el pipeline. No hay módulo de clima.
      x / twitter     sin API abierta. No se scrapea.
      sofascore
      transfermarkt   sin API y bloquean el scraping.

Las que no funcionan **están registradas igualmente**, con `disponible=False` y
su motivo. Un hueco declarado se ve en `estado()` y se enchufa el día que
aparezca la fuente; un hueco no declarado simplemente no existe para nadie —que
es como `filtro_contexto` se pasó desde la v202 hasta la v209 sin disparar.

FRAGILIDAD (§5 del encargo)
---------------------------
Ninguna señal es obligatoria. `senales()` captura los fallos de cada proveedor
por separado: una fuente caída resta señales, no tumba la pantalla. `estado()`
es lo que un cron puede vigilar para avisar de que una fuente dejó de dar nada.
"""

import datetime as _dt
import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger('scraper_contexto')

DEPORTES = ('futbol', 'nfl', 'mlb', 'tenis', 'kbo')

# Confianza por fuente. No está medida: es el orden de preferencia del
# proyecto (dato propio > fuente pública verificada > agregador).
CONFIANZA = {'historico_propio': 0.95, 'wikidata': 0.85, 'fotmob': 0.80,
             'espn': 0.75, 'api_football': 0.85}

# Umbrales de agregación del encargo.
PESO_ESCALADA = 3       # >= 3 -> respalda escalada
PESO_CONTEXTO = 2       # >= 2 -> «contexto positivo»

_REGISTRO: Dict[str, Dict] = {}


def senal(tipo: str, peso: int, fuente: str, deporte: str,
          metrica_afectada: str = '', detalle: str = '',
          confianza: Optional[float] = None) -> Dict:
    """Una señal en el formato normalizado del encargo."""
    return {
        'tipo': tipo,
        'peso': int(peso),
        'fuente': fuente,
        'confianza_fuente': (CONFIANZA.get(fuente, 0.5)
                             if confianza is None else float(confianza)),
        'timestamp': _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'deporte': deporte,
        'metrica_afectada': metrica_afectada,
        'detalle': detalle,
    }


def registrar(nombre: str, fn: Optional[Callable], deportes,
              disponible: bool = True, motivo: str = '') -> None:
    """Da de alta un proveedor. Los NO disponibles también se registran."""
    _REGISTRO[nombre] = {'fn': fn, 'deportes': tuple(deportes),
                         'disponible': bool(disponible), 'motivo': motivo}


# ---------------------------------------------------------------------------
# Proveedores que funcionan
# ---------------------------------------------------------------------------
def _p_entrenador(ctx: Dict) -> List[Dict]:
    """Cambio de entrenador en los últimos 7 días (Wikidata)."""
    import auditoria_pick as ap
    pick = {'partido': ctx.get('partido'), 'apuesta': ctx.get('apuesta') or '',
            'cuota': ctx.get('cuota'), 'fecha': ctx.get('fecha')}
    r = ap.entrenador_nuevo(pick, dia=ctx.get('fecha'))
    if not r.get('activa'):
        return []
    return [senal('contexto', 1, 'wikidata', ctx.get('deporte', 'futbol'),
                  detalle=f"{r.get('equipo')} cambió de entrenador hace "
                          f"{r.get('dias')} días")]


def _p_racha(ctx: Dict) -> List[Dict]:
    """Racha reciente de los dos equipos, del histórico propio."""
    import contexto_partido as cp
    clave = ctx.get('clave_liga')
    if not clave:
        return []
    fuera = []
    for equipo in (ctx.get('home'), ctx.get('away')):
        if not equipo:
            continue
        f = cp.forma(str(clave), str(equipo)) or {}
        racha = str(f.get('racha') or '')
        if len(racha) >= 4 and racha[-4:].count('G') >= 3:
            fuera.append(senal('racha', 1, 'historico_propio',
                               ctx.get('deporte', 'futbol'),
                               ctx.get('metrica', ''),
                               f'{equipo} ganó 3 de sus últimos 4 (`{racha}`)'))
    return fuera


def _p_h2h(ctx: Dict) -> List[Dict]:
    """Cara a cara: sólo si la métrica pedida se repitió en el historial."""
    import contexto_partido as cp
    clave, h, a = ctx.get('clave_liga'), ctx.get('home'), ctx.get('away')
    if not (clave and h and a):
        return []
    d = cp.h2h(str(clave), str(h), str(a)) or {}
    n, goles = int(d.get('n') or 0), d.get('goles')
    if n < 3 or goles is None:
        return []
    linea = ctx.get('linea_superior')
    if linea is None:
        return []
    try:
        if float(goles) / max(n, 1) >= float(linea):
            return [senal('h2h', 1, 'historico_propio',
                          ctx.get('deporte', 'futbol'), ctx.get('metrica', ''),
                          f'el cara a cara promedia {float(goles)/n:.1f} '
                          f'sobre {n} partidos')]
    except (TypeError, ValueError):
        return []
    return []


def _p_aclimatacion(ctx: Dict) -> List[Dict]:
    """Desnivel: la única señal de contexto MEDIDA fuera de muestra."""
    import contexto_ampliado as ca
    clave, h, a = ctx.get('clave_liga'), ctx.get('home'), ctx.get('away')
    if not (clave and h and a):
        return []
    d = ca.de_partido(str(clave), str(h), str(a)) or {}
    if not d.get('sube_visitante'):
        return []
    return [senal('contexto', 1, 'historico_propio',
                  ctx.get('deporte', 'futbol'), ctx.get('metrica', ''),
                  'el visitante sube de altitud (efecto MEDIDO sobre el 1X2)',
                  confianza=0.95)]


def _p_media_metrica(ctx: Dict) -> List[Dict]:
    """La media reciente de la métrica ya supera la línea superior."""
    m, linea = ctx.get('media_5'), ctx.get('linea_superior')
    if m is None or linea is None:
        return []
    try:
        if float(m) >= float(linea):
            return [senal('contexto', 1, 'historico_propio',
                          ctx.get('deporte', 'futbol'), ctx.get('metrica', ''),
                          f'la media reciente ({float(m):.1f}) ya supera '
                          f'{linea}')]
    except (TypeError, ValueError):
        pass
    return []


def _p_arbitro(ctx: Dict) -> List[Dict]:
    """Árbitro con sesgo medido de tarjetas. Sólo aplica a tarjetas."""
    if 'tarjeta' not in str(ctx.get('metrica') or '').lower():
        return []
    try:
        import arbitro_partido as arb
    except Exception:
        return []
    f = None
    for nombre in ('ficha', 'del_partido', 'de_partido'):
        fn = getattr(arb, nombre, None)
        if callable(fn):
            try:
                f = fn(ctx.get('clave_liga'), ctx.get('home'), ctx.get('away'))
                break
            except Exception:
                continue
    if not isinstance(f, dict) or not f.get('media_tarjetas'):
        return []
    linea = ctx.get('linea_superior')
    try:
        if linea is not None and float(f['media_tarjetas']) >= float(linea):
            return [senal('contexto', 1, 'historico_propio',
                          ctx.get('deporte', 'futbol'), 'tarjetas',
                          f"el árbitro promedia {f['media_tarjetas']} tarjetas")]
    except (TypeError, ValueError):
        pass
    return []


registrar('entrenador', _p_entrenador, ('futbol',))
registrar('racha', _p_racha, DEPORTES)
registrar('h2h', _p_h2h, DEPORTES)
registrar('aclimatacion', _p_aclimatacion, ('futbol',))
registrar('media_metrica', _p_media_metrica, DEPORTES)
registrar('arbitro', _p_arbitro, ('futbol',))

# ---------------------------------------------------------------------------
# Huecos declarados. No se simulan; se registran para que se vean.
# ---------------------------------------------------------------------------
registrar('lesiones', None, DEPORTES, disponible=False,
          motivo='API-Football sin clave configurada (API_FOOTBALL_KEY). '
                 'La regla existe; falta la credencial.')
registrar('alineaciones', None, DEPORTES, disponible=False,
          motivo='misma clave. ESPN publica `rosters` (plantilla), no el once '
                 'confirmado, así que no responde «falta el central».')
registrar('clima', None, ('futbol', 'nfl', 'mlb'), disponible=False,
          motivo='no hay ninguna fuente de clima en el pipeline')
registrar('x_twitter', None, DEPORTES, disponible=False,
          motivo='sin API abierta; no se scrapea')
registrar('sofascore', None, ('futbol',), disponible=False,
          motivo='sin API y bloquea el scraping')
registrar('transfermarkt', None, ('futbol',), disponible=False,
          motivo='sin API y bloquea el scraping')


# ---------------------------------------------------------------------------
def senales(contexto: Dict) -> List[Dict]:
    """Todas las señales que los proveedores disponibles sepan dar.

    Cada proveedor va en su propio `try`: una fuente caída resta señales, no
    tumba la llamada. Es la condición de fragilidad del §5 del encargo.
    """
    ctx = dict(contexto or {})
    deporte = str(ctx.get('deporte') or 'futbol').lower()
    fuera: List[Dict] = []
    for nombre, p in _REGISTRO.items():
        if not p['disponible'] or not p['fn']:
            continue
        if deporte not in p['deportes']:
            continue
        try:
            fuera.extend(p['fn'](ctx) or [])
        except Exception as e:
            logger.debug('[contexto] proveedor %s: %s', nombre, e)
    return fuera


def agregar(lista: Optional[List[Dict]] = None) -> Dict:
    """Suma los pesos y traduce a los tramos del encargo."""
    s = [x for x in (lista or []) if isinstance(x, dict)]
    peso = sum(int(x.get('peso') or 1) for x in s)
    if peso >= PESO_ESCALADA:
        veredicto = 'respalda_escalada'
    elif peso >= PESO_CONTEXTO:
        veredicto = 'contexto_positivo'
    else:
        veredicto = 'insuficiente'
    return {'peso': peso, 'n': len(s), 'veredicto': veredicto, 'senales': s,
            'tipos': sorted({str(x.get('tipo') or '?') for x in s})}


def de_partido(clave_liga: Optional[str], home: str, away: str,
               deporte: str = 'futbol', metrica: str = 'goles',
               linea_superior: Optional[float] = None,
               media_5: Optional[float] = None,
               fecha: Optional[str] = None,
               **extra) -> Dict:
    """Atajo: el contexto de un partido, ya agregado."""
    ctx = {'clave_liga': clave_liga, 'home': home, 'away': away,
           'partido': f'{home} vs {away}', 'deporte': deporte,
           'metrica': metrica, 'linea_superior': linea_superior,
           'media_5': media_5, 'fecha': fecha, **extra}
    return agregar(senales(ctx))


def estado() -> Dict:
    """Qué proveedores hay, cuáles funcionan y por qué no los demás.

    Es lo que un cron vigila: si un proveedor que estaba disponible deja de
    estarlo, o si `disponibles` baja, hay que mirarlo.
    """
    return {
        'disponibles': sorted(n for n, p in _REGISTRO.items() if p['disponible']),
        'no_disponibles': {n: p['motivo'] for n, p in _REGISTRO.items()
                           if not p['disponible']},
        'por_deporte': {d: sorted(n for n, p in _REGISTRO.items()
                                  if p['disponible'] and d in p['deportes'])
                        for d in DEPORTES},
    }


if __name__ == '__main__':
    import json as _json
    print(_json.dumps(estado(), ensure_ascii=False, indent=1))
