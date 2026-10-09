# -*- coding: utf-8 -*-
"""
v302 — LA FILA COMPACTA: partido, apuesta, cuota, probabilidad, semáforo y
hora. Nada más.

LO QUE PIDIÓ EL USUARIO
    «En cuanto al reto escalera las tarjetas están bien grandes y tengo que
     scrollear mucho. Simplemente quiero un diseño sencillo en el que me diga
     lo relevante: el partido, la cuota, la probabilidad, el semáforo y la
     hora del partido.»

    «Capa 1 quiero que se pueda minimizar... igual quiero el diseño sencillo.
     Usa el mismo que te dije para el reto escalera.»

Medido en la versión anterior: cada opción de la Escalera era un contenedor
con borde, un título, un pie, TRES `st.metric` y otra línea de casa. Unos 190
píxeles por apuesta; ocho opciones eran 1.500 píxeles de scroll para leer
ocho números. Una fila de estas mide ~46.

POR QUÉ UN MÓDULO Y NO HTML DENTRO DE LA PANTALLA
`dashboard_ui` no se puede importar en un test (al importarlo se ejecuta el
router y revienta con `KeyError: 'alpha'`). Lo que decide qué se ve —qué día
se dice, qué hora, qué color— tiene que poder probarse, así que vive aquí y la
pantalla sólo hace `st.markdown(html)`.

EL DÍA SE DICE EN CADA FILA
El fallo que el usuario llamó «me estás adelantando un día» no era de cálculo:
`dia_picks` ya asignaba bien el día en hora de CDMX. Era de PRESENTACIÓN —el
mando arrancaba en «todo», desaparecía si hoy estaba vacío, y la tarjeta sólo
enseñaba la hora—, así que un partido de mañana a las 10:00 se leía como de
hoy a las 10:00. Ahora cada fila dice «Hoy 19:00» o «Mañana 10:00».
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ICONO = {'verde': '🟢', 'ambar': '🟡', 'rojo': '🔴', 'probable': '🎯',
         # v317 — el segundo nivel de la Capa 1 (`lo_mejor.py`): otra
         # probabilidad, y se ve distinto
         'riesgo': '🔷'}

# Colores con transparencia: se leen igual sobre el tema claro y el oscuro de
# Streamlit, que es lo que el resto de la aplicación ya hace con `mm-*`.
CSS = """<style>
.vc-lista{display:flex;flex-direction:column;gap:4px;margin:2px 0 8px 0}
.vc-fila{display:grid;grid-template-columns:62px minmax(0,1fr) 52px 48px;
 align-items:center;gap:8px;padding:5px 8px;border-radius:8px;
 border:1px solid rgba(128,128,128,.28);background:rgba(128,128,128,.06)}
.vc-cuando{font-size:.78rem;line-height:1.15;opacity:.85;white-space:nowrap}
.vc-cuando b{font-size:.86rem;opacity:1}
.vc-que{min-width:0;line-height:1.2}
.vc-ap{font-weight:600;font-size:.9rem;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.vc-par{font-size:.76rem;opacity:.75;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.vc-num{text-align:right;line-height:1.1}
.vc-num b{font-size:.95rem}
.vc-num span{display:block;font-size:.66rem;opacity:.65}
.vc-cab{display:grid;grid-template-columns:62px minmax(0,1fr) 52px 48px;
 gap:8px;padding:0 8px;font-size:.66rem;opacity:.6;text-transform:uppercase}
.vc-cab span:nth-child(3),.vc-cab span:nth-child(4){text-align:right}
.vc-fila.fin-ok{border-color:rgba(16,185,129,.8);background:rgba(16,185,129,.16);
 box-shadow:0 0 0 1px rgba(16,185,129,.35),0 0 18px rgba(16,185,129,.30)}
.vc-fila.fin-no{border-color:rgba(248,113,113,.8);background:rgba(248,113,113,.15);
 box-shadow:0 0 0 1px rgba(248,113,113,.35),0 0 18px rgba(248,113,113,.28)}
.vc-fila.vivo{border-style:dashed;opacity:.9}
.vc-res{display:inline-block;margin-top:2px;font-weight:800;font-size:.72rem;
 letter-spacing:.02em}
.vc-fila.fin-ok .vc-res{color:#10b981}
.vc-fila.fin-no .vc-res{color:#f87171}
.vc-hap{display:inline-block;margin-top:2px;font-size:.68rem;font-weight:700;
 color:#f59e0b}
</style>"""

# v342 — la Capa 1 de un partido ya empezado no desaparece: se queda con su
# resultado (`lo_mejor.finalizados`), en verde si se dio y en rojo si no
_CLASE_RES = {'verde': ' fin-ok', 'rojo': ' fin-no', 'vivo': ' vivo', 'nula': ' vivo'}
_TEXTO_RES = {'verde': '✅ SÍ', 'rojo': '❌ NO', 'vivo': '⏳ VIVO',
              'nula': '↩️ NULA'}       # v351: línea entera con empate exacto


def _esc(t) -> str:
    return _html.escape(str(t if t is not None else ''), quote=True)


def dia_relativo(pick: Dict, hoy: Optional[_dt.date] = None) -> str:
    """'Hoy', 'Mañana', 'Pasado' o '25 sep'. Cadena vacía si no hay fecha.

    Sale de `dia_picks.dia_de`, que es EL reloj de la presentación (CDMX):
    la Escalera, la Capa 1 y Apuestas del Día no pueden usar tres relojes.
    """
    try:
        import dia_picks as _dp
        f = _dp.dia_de(pick)
        if not f:
            return ''
        d = _dt.date.fromisoformat(f)
        base = hoy or _dp.hoy_local()
        dif = (d - base).days
        if dif == 0:
            return 'Hoy'
        if dif == 1:
            return 'Mañana'
        if dif == 2:
            return 'Pasado'
        if dif == -1:
            return 'Ayer'
        meses = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago',
                 'sep', 'oct', 'nov', 'dic')
        return '%d %s' % (d.day, meses[d.month - 1])
    except Exception as e:
        logger.debug('[vista_compacta] dia: %s', e)
        return ''


def hora(pick: Dict) -> str:
    """'19:00' en CDMX, o cadena vacía."""
    try:
        import horario as _h
        return _h.hora(pick.get('inicio')) or str(pick.get('hora_cdmx') or '')
    except Exception:
        return str(pick.get('hora_cdmx') or '')


def _hora_apuesta(pick: Dict) -> str:
    """v351 — '⏰14:15' (desde cuándo apostarlo), '⏰ya' o ''. Nunca lanza."""
    if pick.get('resultado_c1') or pick.get('jugado'):
        return ''
    try:
        import hora_apuesta as _ha
        return _ha.corto(pick)
    except Exception:
        return ''


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def fila(pick: Dict, hoy: Optional[_dt.date] = None) -> Optional[Dict]:
    """Los seis datos de una fila, ya listos. None si no hay cuota."""
    if not isinstance(pick, dict):
        return None
    cuota = _num(pick.get('cuota'))
    if not cuota or cuota <= 1:
        return None
    prob = _num(pick.get('prob_escalera'))
    if prob is None:
        prob = _num(pick.get('prob'))
    sf = pick.get('semaforo') or {}
    nivel = sf.get('nivel') if isinstance(sf, dict) else None
    if pick.get('probable') and not nivel:
        nivel = 'probable'
    # La forma del equipo y la media de goles del cruce, que el usuario pidió
    # ver en la Escalera (v296) y que `forma_equipos` calcula. SE ENSEÑAN, NO
    # FILTRAN —medido: como filtro no sobrevive al tramo de juicio—, y van en
    # el aviso al pasar el cursor para no volver a hacer la fila alta.
    extra = []
    try:
        import forma_equipos as _fe
        fz = _fe.resumen_pick(pick)
        if fz:
            extra.append('%s %s' % (_fe.del_pick(pick), fz))
        gm = _fe.goles_del_partido(pick)
        if gm:
            extra.append('media de goles del cruce %.1f' % gm)
    except Exception as e:
        logger.debug('[vista_compacta] forma: %s', e)
    apuesta = str(pick.get('apuesta') or '?')
    patas = [p for p in (pick.get('patas') or []) if isinstance(p, dict)]
    if patas:
        # la combinada se lee como sus dos patas: es lo que hay que marcar
        apuesta = ' + '.join(str(p.get('texto') or '?') for p in patas)
    return {'icono': ICONO.get(nivel, '🟡'),
            'nivel': nivel or '',
            'dia': dia_relativo(pick, hoy),
            'hora': hora(pick),
            'apuesta': apuesta,
            'partido': str(pick.get('partido') or '?'),
            'casa': str(pick.get('casa') or ''),
            'cuota': cuota,
            'prob': prob,
            'resultado': str(pick.get('resultado_c1') or ''),    # v342
            'anunciada': bool(pick.get('anunciada')),             # v346
            'marcador': str(pick.get('marcador') or ''),
            'hora_apuesta': _hora_apuesta(pick),                  # v351
            'porque': ' · '.join(
                [x for x in [str((sf.get('etiqueta') if isinstance(sf, dict)
                                  else '') or pick.get('etiqueta_probable')
                                 or '')] + extra if x])}


def html_lista(picks: List[Dict], hoy: Optional[_dt.date] = None,
               con_cabecera: bool = True, con_css: bool = True) -> str:
    """La lista entera en HTML. Cadena vacía si no hay nada que pintar."""
    filas = [f for f in (fila(p, hoy) for p in (picks or [])) if f]
    if not filas:
        return ''
    out = [CSS] if con_css else []
    out.append('<div class="vc-lista">')
    if con_cabecera:
        out.append('<div class="vc-cab"><span>Cuándo</span><span>Apuesta'
                   '</span><span>Cuota</span><span>Acierta</span></div>')
    for f in filas:
        pie = f['partido'] + ((' · ' + f['casa']) if f['casa'] else '')
        prob = ('%.0f %%' % (100 * f['prob'])) if f['prob'] is not None \
            else '—'
        titulo = f['porque'] or f['apuesta']
        res = f.get('resultado') or ''
        cuando = '%s <b>%s</b><br>%s' % (f['icono'], _esc(f['hora'] or '—'),
                                         _esc(f['dia']))
        if f.get('hora_apuesta'):
            # v351 — desde cuándo conviene apostarlo (`hora_apuesta`)
            cuando += '<br><span class="vc-hap">%s</span>' % _esc(f['hora_apuesta'])
        if res in _TEXTO_RES:
            # v342 — el resultado en lugar del día: ya no hace falta saber
            # cuándo se juega, sino cómo quedó
            cuando = '<b>%s</b><br><span class="vc-res">%s</span>' % (
                _esc(f.get('marcador') or f['hora'] or '—'), _TEXTO_RES[res])
        out.append(
            '<div class="vc-fila%s" title="%s">'
            '<div class="vc-cuando">%s</div>'
            '<div class="vc-que"><div class="vc-ap">%s</div>'
            '<div class="vc-par">%s</div></div>'
            '<div class="vc-num"><b>%.2f</b><span>cuota</span></div>'
            '<div class="vc-num"><b>%s</b><span>acierta</span></div>'
            '</div>' % (_CLASE_RES.get(res, ''), _esc(titulo), cuando,
                        ('📌 ' if f.get('anunciada') else '') + _esc(f['apuesta']),
                        _esc(pie), f['cuota'], prob))
    out.append('</div>')
    return ''.join(out)


def rotulo_dias(conteo: Dict[str, int]) -> Dict[str, str]:
    """{'hoy': 'Hoy (3)', ...} para el selector de día."""
    nombres = {'hoy': 'Hoy', 'mañana': 'Mañana', 'pasado': 'Pasado'}
    return {k: '%s (%d)' % (v, int(conteo.get(k) or 0))
            for k, v in nombres.items()}
