#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pantalla «Armar Soñadora»: dos controles, permutaciones propuestas y elección
manual.

QUÉ CAMBIÓ RESPECTO A LA PRIMERA VERSIÓN
----------------------------------------
La primera tenía seis controles, una advertencia roja permanente y salía vacía.
Vacía no por prudencia: la rama de fútbol del barrido estaba reventando
(arreglado en `alpha_finder`) y encima el filtro de calibración tiraba 133 de
174 patas. Ahora:

    · **Configuración corta**: rango de cuota, número de patas y qué deportes
      entran. La probabilidad mínima queda fija en 55 % y el filtro de
      calibración desapareció — cada pata lleva su semáforo y el usuario
      decide.
    · **Nunca vacía**: si el rango no deja nada, el motor lo ensancha solo y la
      pantalla lo dice en una línea.
    · **Sin advertencia roja**: un aviso pequeño arriba y una casilla antes de
      confirmar. El rendimiento medido sigue estando, al lado del premio.

EL SEMÁFORO
-----------
🟢 sólida · 🟡 moderada · 🔴 alto riesgo · ⚪ sin probabilidad. Lo calcula
`sonadora_motor.color` y aquí sólo se pinta. Las rojas se esconden por defecto
y hay un interruptor para verlas; si un día NO hay nada mejor que rojas, se
enseñan igual — esconder lo único que hay es dejar la pantalla vacía por otra
vía.

EL ORDEN DE LO QUE SE ENSEÑA
----------------------------
Permutación A (la más segura) primero, y el ROI medido junto al premio y no al
pie: al pie no se lee. Es la misma lección que puso la alarma de datos al
principio del mensaje diario en la v41.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

AVISO = ('ℹ️ Sección de entretenimiento. No es asesoramiento financiero ni una '
         'recomendación del sistema.')

N_PATAS_OPCIONES = (4, 6, 8, 10, 13)


def _pct(x, dec=1) -> str:
    try:
        return f"{float(x) * 100:.{dec}f} %"
    except (TypeError, ValueError):
        return '—'


def _sello(q: Dict) -> str:
    """El semáforo de la pata.

    Normalmente lo trae el motor. Si faltara —una pata de un camino antiguo, o
    un estado guardado de antes— se recalcula aquí en vez de caer a gris: gris
    es «no se sabe», y con la probabilidad delante sí se sabe. Es justo el
    síntoma que el usuario reportó, «veo puro blanco», y esta red lo cierra
    venga de donde venga la pata.
    """
    color = q.get('color')
    if color:
        return color
    try:
        import sonadora_motor as sm
        return sm.color(q.get('prob'), q.get('ece'),
                        bool(q.get('calibracion_floja')))
    except Exception:
        return '⚪'


_FLECHA = {'a_favor': '📉 el mercado se mueve a favor',
           'en_contra': '📈 el mercado se mueve en contra',
           'estable': ''}
_ALI = {'confirmada': '✅ alineación confirmada',
        'probable': '🔸 alineación probable',
        'ultimo_once': '', 'desconocida': ''}


_RIESGO = {'alta': '⚠️ competición del peor cuarto por calibración',
           'baja': '', 'media': '', 'sin_medir': ''}


def _cuenta_del_otro_dia(st, sm, r, dia, lo, hi, deportes, rojas, casa,
                         solo_bajo):
    """(día, nº de patas) del día contiguo, o None si tampoco hay.

    Cuesta una pasada más, así que sólo se llama cuando el día pedido salió
    vacío — que es justo cuando el usuario necesita saber si el problema es el
    día o la configuración.
    """
    import mercados_dia as md
    try:
        hoy = md.dia_cdmx()
        otro = md.dia_cdmx(1) if str(dia) == hoy else hoy
        res = sm.patas_del_dia(r, otro, cuota_min=lo, cuota_max=hi,
                               deportes=list(deportes), con_rojas=rojas,
                               casa=casa, solo_riesgo_bajo=solo_bajo)
        return otro, len(res.get('patas') or [])
    except Exception:
        return None


def _linea_pata(q: Dict) -> str:
    cola = '' if q.get('medido') else '  ·  _sin calibración medida_'
    extra = [x for x in (_FLECHA.get(q.get('movimiento') or '', ''),
                         _ALI.get(q.get('alineacion') or '', ''),
                         _RIESGO.get(q.get('nivel_riesgo') or '', '')) if x]
    pie = ('  \n     ' + ' · '.join(extra)) if extra else ''
    cal = ''
    if q.get('prob_calibrada') and q.get('prob_modelo') is not None:
        cal = f" _(el modelo decía {_pct(q['prob_modelo'], 0)})_"
    return (f"{_sello(q)} **{q['etiqueta']}** · {q['partido']} "
            f"— `{q['cuota']:.2f}` · {_pct(q['prob'], 0)}{cal} "
            f"· {q['liga']}{(' · ' + q['hora']) if q.get('hora') else ''}"
            f"{cola}{pie}")


def _a_pata_de_motor(q: Dict, dia: Optional[str]) -> Dict:
    """La pata del veredicto, con los nombres que usa `sonadora_motor`.

    Las dos mitades del proyecto nombran lo mismo de forma distinta —el
    veredicto dice `apuesta` y `mercado`, el motor dice `etiqueta` y
    `categoria`— y hasta la v257 eso no importaba porque cada armador usaba su
    propio motor. Ahora sólo queda un armador, y para que conserve el premio,
    la exposición y el registro de boletos vivos hay que traducir una vez.

    Se traduce AQUÍ y no en `patas_veredicto`: el veredicto lo consumen
    también las tarjetas y el Telegram, y renombrarle las claves habría
    obligado a tocar los tres sitios para arreglar uno.
    """
    return {
        'id': '%s|%s' % (q.get('partido'), q.get('apuesta')),
        'partido': q.get('partido'),
        'etiqueta': q.get('apuesta'),
        'categoria': q.get('mercado'),
        'liga': q.get('liga') or '',
        'deporte': q.get('deporte') or '',
        'cuota': float(q.get('cuota') or 1.0),
        'prob': float(q.get('prob') or 0.0),
        'prob_modelo': q.get('prob_modelo'),
        'medido': bool(q.get('medido')),
        'dia': q.get('fecha') or dia,
        'hora': q.get('inicio'),
        'color': 'verde' if q.get('verde') else 'rojo',
    }


def render(st, r: Dict, dia: Optional[str] = None,
           dias: Optional[List[str]] = None) -> None:
    """Pinta la pantalla. `r` es un barrido YA calculado."""
    import mercados_dia as md
    import sonadora_motor as sm

    st.header('🎰 Armar Soñadora')
    st.info(AVISO)

    # ------------------------------------------------------------------ #
    # v223 — LA SOÑADORA ARMADA CON LOS PICKS DEL DÍA
    #
    # Lo que se pidió: «que sólo me extraiga las apuestas, una de cada partido
    # y que sea la que esté en verde». Esta sección hace exactamente eso, y es
    # una FUENTE DISTINTA de la de abajo: aquí entran las mismas
    # recomendaciones que se ven en «Apuestas del Día», con su veredicto y su
    # probabilidad ya corregida por lo que cada mercado acierta de verdad. El
    # armador clásico de más abajo sigue intacto, recorriendo el tablero
    # entero de la casa.
    #
    # Van separadas a propósito: mezclarlas daría un boleto que no se puede
    # explicar, porque las dos mitades se habrían elegido con criterios
    # distintos.
    # ------------------------------------------------------------------ #
    with st.expander('⚡ Armar con los picks de «Apuestas del Día»',
                     expanded=True):
        st.caption('Una pata por partido, la que está en verde. Si no hay '
                   'verdes suficientes se completa con las rojas **más '
                   'probables** — no con las mejor pagadas: en un boleto la '
                   'probabilidad se multiplica.')
        # v257 — CON QUÉ DEPORTES SE ARMA.
        #
        # «Tienes que agregar con qué deportes se tiene que usar. Puede ser un
        # solo deporte u opción múltiple, además de con todos.»
        #
        # Sin marcar ninguno entran TODOS, que es exactamente el boleto que
        # salía antes de que este control existiera: quien no lo toque no ve
        # cambiar nada. El número al lado de cada deporte es cuántos partidos
        # suyos trae ESTE barrido, y un deporte sin partidos hoy ni aparece —
        # ofrecer un filtro que sólo puede devolver vacío es la trampa que la
        # v238 documentó en el selector de «Apuestas del Día».
        _EMOJI_DEP = {'Fútbol': '⚽', 'MLB': '⚾', 'NBA': '🏀', 'Tenis': '🎾',
                      'NFL': '🏈', 'KBO': '⚾'}
        _cuenta_son = {}
        for _p_s in (r.get('pronosticos') or []):
            _d_s = _p_s.get('deporte') if isinstance(_p_s, dict) else None
            if _d_s:
                _cuenta_son[_d_s] = _cuenta_son.get(_d_s, 0) + 1
        _deps_disp = sorted(_cuenta_son, key=lambda k: (-_cuenta_son[k], k))

        def _rotulo_son(d):
            return '%s %s · %d' % (_EMOJI_DEP.get(d, '•'), d,
                                   _cuenta_son.get(d, 0))

        _deps_v = []
        if len(_deps_disp) > 1:
            _ayuda_dep = ('Marca uno, varios o ninguno. Sin marcar entran '
                          'todos. El boleto sigue poniendo UNA pata por '
                          'partido: elegir dos deportes no duplica nada.')
            if hasattr(st, 'pills'):
                _deps_v = st.pills(
                    'Deportes', _deps_disp, selection_mode='multi',
                    key='son_v_deportes', format_func=_rotulo_son,
                    help=_ayuda_dep) or []
            else:
                # `st.pills` es de Streamlit 1.40. El despliegue va muy por
                # encima, pero un entorno viejo no puede quedarse sin el
                # control: se degrada al multiselector de toda la vida.
                _deps_v = st.multiselect(
                    'Deportes', _deps_disp, key='son_v_deportes',
                    format_func=_rotulo_son, help=_ayuda_dep) or []
            st.caption(
                ('Armando con **%s**.' % ' + '.join(_deps_v)) if _deps_v
                else ('Sin marcar ninguno: entran **los %d deportes** del '
                      'barrido (%d partidos).'
                      % (len(_deps_disp), sum(_cuenta_son.values()))))

        # v257 — LOS PARTIDOS DE UN BOLETO VIVO NO SE REPITEN.
        #
        # Venía del armador manual y el caso lo trajo el usuario: Boyacá Chicó
        # en dos parlays a la vez, que no es diversificar sino doblar la
        # apuesta al mismo resultado con la pantalla diciendo que son dos
        # boletos distintos. El filtro va ANTES de `seleccionar` para que los
        # topes por liga y por mercado se repartan sobre lo que de verdad
        # puede entrar.
        _comprometidos = set()
        try:
            _comprometidos = sm.partidos_comprometidos(dia=dia)
        except Exception as _e_com:
            logger.debug('[sonadora] boletos vivos: %s', _e_com)
        _r_libre = r
        if _comprometidos:
            _r_libre = dict(r or {})
            _r_libre['pronosticos'] = [
                _p_c for _p_c in ((r or {}).get('pronosticos') or [])
                if str((_p_c or {}).get('partido')) not in _comprometidos]
            _cc = st.columns([3, 1])
            _cc[0].caption(
                '🔒 %d partido(s) ya están en un boleto que diste por jugado '
                'hoy, así que no vuelven a entrar: %s%s'
                % (len(_comprometidos), ', '.join(sorted(_comprometidos)[:3]),
                   '…' if len(_comprometidos) > 3 else ''))
            if _cc[1].button('Vaciar registro', key='son_vaciar'):
                sm.olvidar_parlays()
                st.rerun()

        _cv1, _cv2, _cv3 = st.columns([1, 1, 1])
        _n_v = _cv1.number_input('Patas', min_value=1, max_value=20, value=4,
                                 step=1, key='son_v_patas')
        _cuota_v = _cv2.number_input('Cuota mínima por pata', min_value=1.05,
                                     max_value=5.0, value=1.30, step=0.05,
                                     key='son_v_cuota')
        _princ_v = _cv3.checkbox('Sólo principales', key='son_v_principales',
                                 help='Deja sólo competiciones grandes de '
                                      'fútbol. Sin marcar entra cualquiera, '
                                      'incluidos los otros deportes.')
        try:
            import patas_veredicto as _pv
            _sel = _pv.seleccionar(_r_libre, int(_n_v), float(_cuota_v),
                                   bool(_princ_v),
                                   deportes=list(_deps_v) or None)
            if _sel['patas']:
                _c1, _c2, _c3 = st.columns(3)
                _c1.metric('Cuota del boleto', '%.2f' % (_sel['cuota_total'] or 0))
                _c2.metric('Probabilidad', '%.1f %%'
                           % ((_sel['prob_total'] or 0) * 100))
                _c3.metric('Verdes', '%d de %d'
                           % (_sel['n_verdes'], len(_sel['patas'])))
                for _q in _sel['patas']:
                    st.markdown(
                        '%s **%s** · %s _(%s)_ — @%.2f · **%.0f %%**'
                        % ('🟢' if _q['verde'] else '🔴',
                           _q.get('apuesta', '?'), _q.get('partido', '?'),
                           _q.get('liga', ''), _q['cuota'],
                           (_q['prob'] or 0) * 100))
                st.caption(_sel['motivo'])
                # La probabilidad de un parlay se desploma con cada pata, y
                # enseñar sólo la cuota invita a pedir veinte.
                st.caption(
                    'Con %d patas el boleto acierta **%.1f %%** de las veces. '
                    'Cada pata que añades multiplica la cuota y divide esa '
                    'probabilidad.'
                    % (len(_sel['patas']), (_sel['prob_total'] or 0) * 100))

                # v257 — EL PREMIO, LO MEDIDO, EL RIESGO Y EL REGISTRO.
                #
                # Todo esto vivía al final del armador manual. Quitar aquel
                # menú sin traérselo habría dejado la pantalla enseñando
                # cuánto paga y callando cuánto rinde, que es exactamente la
                # mitad que conviene a la casa. El usuario pidió un solo menú,
                # no la mitad de uno: «todo se mantiene con eso».
                _parlay = sm.armar([_a_pata_de_motor(_q, dia)
                                    for _q in _sel['patas']])
                _stake = st.number_input(
                    '¿Cuánto apostarías?', min_value=1.0, value=46.0,
                    step=1.0, key='son_v_apuesta',
                    help='46 es lo que costó el parlay que ganaste.')
                st.markdown('### Premio: **$%s**'
                            % format(_stake * (_parlay['multiplicador'] or 1),
                                     ',.2f'))
                _roi = _parlay.get('roi_esperado_medido')
                _cfg = _parlay.get('configuracion_medida')
                _dicho = []
                if _roi is not None:
                    _dicho.append(
                        '**Rendimiento histórico de un boleto de %d patas: '
                        '%s** (≈ $%s por cada $%s). Sale de aplicar %d veces '
                        'lo que rinde una pata suelta: combinar multiplica el '
                        'rendimiento de las patas, no lo mejora.'
                        % (_parlay['n_patas'], _pct(_roi),
                           format(_stake * _roi, ',.2f'),
                           format(_stake, ',.2f'), _parlay['n_patas']))
                if _cfg and _cfg.get('intentos'):
                    _dicho.append(
                        'La configuración medida más parecida (%s patas, %s) '
                        'acertó %s de %s veces (%s), con un multiplicador '
                        'medio de %.1fx.'
                        % (_cfg.get('n_patas'), _cfg.get('rango_cuota'),
                           _cfg.get('ganadas', 0), _cfg.get('intentos', 0),
                           _pct(_cfg.get('hit_rate'), 2),
                           _cfg.get('multiplicador_medio', 0)))
                if _parlay.get('n_sin_medir'):
                    _dicho.append(
                        '%d de las %d patas no tienen calibración medida: su '
                        'probabilidad es la del modelo sin corregir.'
                        % (_parlay['n_sin_medir'], _parlay['n_patas']))
                if _dicho:
                    st.caption('  \n'.join(_dicho))

                _ex = _parlay.get('exposicion') or {}
                if not _ex.get('respeta_topes', True):
                    st.warning(
                        '⚠️ Concentración alta: %s patas de %s y %s del '
                        'mercado «%s». No baja el rendimiento esperado —eso '
                        'sólo depende de las patas— pero sí sube el riesgo de '
                        'que falle todo a la vez, porque los partidos de una '
                        'misma liga y una misma jornada fallan juntos.'
                        % (_ex.get('max_por_liga'),
                           _ex.get('liga_mas_repetida'),
                           _ex.get('max_por_mercado'),
                           _ex.get('mercado_mas_repetido')))

                _dias_b = _parlay.get('dias') or []
                if len(_dias_b) > 1:
                    st.info(
                        '📅 Este boleto reparte sus patas en **%d días** (%s a '
                        '%s). La casa lo acepta, pero el rendimiento '
                        'histórico de arriba está medido sobre boletos de un '
                        'solo día: los partidos de una misma jornada '
                        'comparten contexto y los de días distintos no.'
                        % (len(_dias_b), _dias_b[0], _dias_b[-1]))

                _entendido = st.checkbox(
                    'Entiendo que este parlay tiene un alto riesgo.',
                    key='son_entendido')
                if st.button('🎲 Confirmar parlay', key='son_confirmar',
                             type='primary', disabled=not _entendido):
                    st.success('Listo: esta pantalla no apuesta por ti ni '
                               'manda nada a ningún sitio.')
                    st.code('\n'.join(
                        '%s — %s @ %.2f' % (_q.get('partido'),
                                            _q.get('apuesta'), _q['cuota'])
                        for _q in _sel['patas']), language=None)
                    try:
                        sm.registrar_parlay(_parlay, dia)
                        st.caption(
                            'Apuntado como boleto vivo de hoy: sus partidos '
                            'no volverán a salir en otra combinada hasta que '
                            'vacíes el registro.')
                    except Exception as _e_reg:
                        logger.exception('[sonadora] registrar parlay')
                        st.caption('No se pudo apuntar el boleto (%s).'
                                   % type(_e_reg).__name__)
            elif _deps_v:
                # Un «no hay patas» a secas, con un filtro puesto, se lee como
                # un fallo del modelo. Casi siempre es el filtro.
                st.info('%s — con el filtro de deporte puesto (%s). Quita '
                        'deportes del filtro o baja la cuota mínima.'
                        % (_sel['motivo'], ' + '.join(_deps_v)))
            else:
                st.info(_sel['motivo'])
        except Exception as _e_pv:
            logger.exception('[sonadora] armado por veredicto')
            st.caption('Armado por veredicto no disponible en este barrido '
                       f'({type(_e_pv).__name__}).')

    st.divider()
    # v257 — UN SOLO MENU, Y ES EL DE LOS PICKS DEL DIA.
    #
    # «Las sonadoras tienen dos menus: el de picks del dia y el otro que son
    # de permutaciones. Quiero que solo dejes uno, vas a dejar el de picks del
    # dia. Mantenlo como el principal, es el unico que deberias tener.»
    #
    # Aqui vivia el armador manual —recorrer el tablero entero de la casa con
    # un rango de cuota y un numero de patas— y su escalera de permutaciones.
    # Hacian la misma pregunta que el de arriba por un camino mas largo, y con
    # dos caminos la pantalla podia contradecirse consigo misma: el mismo
    # partido con una pata distinta segun por donde entraras.
    #
    # Lo que se conserva de ellos es lo unico que no duplicaba nada: el
    # historico de que rindio cada longitud, que esta justo debajo.
    # ------------------------------------------------------------------ #
    # 6. Lo medido, para quien quiera mirarlo
    # ------------------------------------------------------------------ #
    hist = sm.historico()
    with st.expander('📊 Qué rindió cada longitud en el histórico'):
        ps = hist.get('pata_suelta') or {}
        if ps.get('n'):
            st.caption(
                f"Periodo {hist.get('periodo', '?')} · "
                f"{hist.get('n_partidos', 0)} partidos. Una pata suelta de "
                f"cuota 1,10-1,80 con probabilidad ≥ 55 %: el modelo le da "
                f"{_pct(ps.get('prob_media'))} y acierta "
                f"{_pct(ps.get('acierto'))} (n={ps.get('n')}).")
        filas = []
        for c in (hist.get('configuraciones') or []):
            if not c.get('intentos'):
                continue
            rango = c.get('rango_cuota') or [0, 0]
            filas.append({
                'Patas': c['n_patas'],
                'Cuota': f"{rango[0]:.2f}–{rango[1]:.2f}",
                'Jornadas': c.get('dias_con_suficientes_partidos'),
                'Acierto': _pct(c.get('hit_rate'), 2),
                'Multiplicador': f"{c.get('multiplicador_medio', 0):.1f}x",
                'Rendimiento': _pct(c.get('roi_simulado')),
            })
        if filas:
            st.dataframe(filas, width='stretch', hide_index=True)
        st.caption(
            'Una fila con pocas jornadas describe esas jornadas, no una '
            'estrategia: por eso va al lado el número de jornadas.')
