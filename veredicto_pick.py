#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v218 — METER o NO METER: un veredicto visual, sin párrafos que leer.

LA PETICIÓN
-----------
«Que la app entienda: ésta tiene un 80 % pero no se puede dar por esto; o al
revés, ésta tiene 60 % y sí es probable porque el otro equipo viene de mala
racha. Que fácilmente se vea cuáles sí debo meter y cuáles no, y que se
identifique VISUALMENTE, porque hay mucho texto.»

LO QUE HACE QUE ESTO NO SEA UN ADORNO
--------------------------------------
Un 55 % no vale lo mismo en todos los mercados, y está MEDIDO sobre los picks
que esta aplicación publicó y se resolvieron:

    Goles              50-60 %   dijo 55,3 %   acertó 47,0 %   ← engaña
    Doble oportunidad  50-60 %   dijo 55,3 %   acertó 63,0 %   ← vale más

Ocho puntos de diferencia entre dos picks que la pantalla enseñaba idénticos.
Eso es lo que corrige este módulo: la probabilidad que se enseña deja de ser la
del modelo y pasa a ser **la del modelo corregida por lo que ese mercado y esa
banda han acertado de verdad**.

LA SEPARACIÓN QUE LO MANTIENE HONESTO
-------------------------------------
Hay dos cosas distintas y se pintan distinto:

    LO MEDIDO      la corrección por fiabilidad. Tiene muestra, tiene
                   intervalo, y es lo único que mueve el veredicto.
    EL CONTEXTO    bajas, racha, entrenador nuevo. Se ENSEÑA con su flecha
                   —es lo que el usuario pidió ver— pero NO decide, porque
                   ninguna de esas reglas está medida contra ROI todavía
                   (ver `archivo_contexto`, que existe para poder medirlas).

Si el contexto decidiera, esto sería otra capa de intuición con pinta de dato.
Enseñarlo al lado del veredicto y dejar claro cuál manda es la diferencia.

EL VEREDICTO ES BINARIO, A PROPÓSITO
------------------------------------
«Es sí o no.» Un tercer estado invita a apostar lo dudoso. Lo que sí hay es
FUERZA: cuánto margen le sobra al sí, o cuánto le falta al no.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger('veredicto_pick')

METER, NO_METER = 'meter', 'no_meter'

# El listón, que es una decisión de producto y no una medición: por debajo de
# aquí no compensa meterla en una combinada de varias patas, porque el
# producto de probabilidades se desploma. Con cuatro patas al 65 % el boleto
# entero está al 17,9 %.
UMBRAL_METER = 0.65

# Cuánto puede corregir la fiabilidad medida. Topado porque una banda con
# muestra corta puede tener una brecha grande por azar, y sin tope esa brecha
# se convertiría en una corrección enorme.
CORRECCION_MAXIMA = 0.10

# Señales de contexto: se enseñan, no deciden. El signo es el que entiende
# `ajuste_contexto.PESOS`.
_A_FAVOR = ('regreso_clave', 'racha_positiva', 'invicto_local',
            'h2h_favorable', 'descanso_extra')
_EN_CONTRA = ('lesion_clave', 'lesion_multiple', 'baja_defensiva',
              'entrenador_nuevo_rival', 'racha_negativa', 'fatiga')

_ETIQUETA = {
    'lesion_clave': 'baja importante', 'lesion_multiple': 'varias bajas',
    'baja_defensiva': 'baja en defensa', 'entrenador_nuevo_rival': 'rival con técnico nuevo',
    'racha_negativa': 'mala racha', 'fatiga': 'poco descanso',
    'regreso_clave': 'vuelve un titular', 'racha_positiva': 'en racha',
    'invicto_local': 'invicto en casa', 'h2h_favorable': 'historial a favor',
    'descanso_extra': 'más descanso',
}


def _f(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def correccion(prob: Optional[float], mercado: str = '',
               cuota: Optional[float] = None) -> Dict:
    """Cuánto hay que mover ese porcentaje según lo que ha acertado de verdad.

    Devuelve la brecha medida (acierto real − prometido) topada, y de dónde
    sale. Si no hay muestra, la corrección es CERO y se dice: no medir no es
    lo mismo que medir cero, pero corregir sin medir es peor que no corregir.
    """
    p = _f(prob)
    vacio = {'delta': 0.0, 'medido': False, 'n': 0, 'fuente': '',
             'veredicto_banda': 'sin_medir'}
    if p is None:
        return vacio
    try:
        import fiabilidad_picks as fp
        fi = fp.fiabilidad(p, str(mercado or ''))
    except Exception as e:
        logger.debug('[veredicto] fiabilidad: %s', e)
        return vacio
    # v224 — DOS MEDICIONES, Y SE USA LA QUE TIENE MÁS EVIDENCIA DETRÁS.
    #
    # Hay dos formas medidas de corregir el mismo número, y no siempre
    # coinciden:
    #
    #   `fiabilidad_picks`   por MERCADO y banda de probabilidad, sobre los
    #                        picks que esta app publicó. Muy pertinente, pero
    #                        con muestras pequeñas: `1X2|70-80 %` tiene n=31.
    #   `calibrador_bandas`  por BANDA DE CUOTA, isotónica walk-forward sobre
    #                        el ledger. `1,20-1,50` tiene n=24.282.
    #
    # El caso que lo destapó: «Gana Milan» a 1,25. El mercado lo ve al 80 %, el
    # modelo dice 72 %, y la medición por banda de cuota dice que ahí el
    # modelo se queda CORTO +4,5 puntos. Con sólo la corrección por mercado
    # (n=31, −2,4) el pick bajaba a 70 % y se pintaba rojo — se estaba
    # escondiendo un favorito claro por la medición más débil de las dos.
    #
    # Se elige por tamaño de muestra, que es lo único defendible cuando dos
    # mediciones honestas discrepan.
    # v225 — NO SE CORRIGE DOS VECES EL MISMO ERROR.
    #
    # Las dos correcciones de abajo se midieron sobre las probabilidades TAL Y
    # COMO SALÍAN DEL MODELO, sin calibrar. Si `calibrador_goles` está activo,
    # la escalera de goles ya llega arreglada en origen: aplicar encima la
    # corrección por fiabilidad —ajustada sobre los picks viejos, los que sí
    # iban descalibrados— empujaría el número una segunda vez en el mismo
    # sentido.
    #
    # Sólo afecta a los mercados de goles, que son los que el calibrador toca.
    # El 1X2, la doble oportunidad y el BTTS siguen corrigiéndose igual.
    try:
        import calibrador_goles as _cgol
        if (_cgol.USAR_CALIBRACION_GOLES
                and str(mercado or '').strip().lower().startswith('goles')):
            return {'delta': 0.0, 'medido': True, 'n': 0,
                    'veredicto_banda': 'de_fiar',
                    'real': p, 'prometido': p,
                    'fuente': 'la escalera de goles ya viene calibrada en '
                              'origen (calibrador_goles)'}
    except Exception as e:
        logger.debug('[veredicto] calibrador de goles: %s', e)

    cand = []
    if fi.get('veredicto') != 'sin_medir' and fi.get('real') is not None:
        cand.append({
            'delta': float(fi['real']) - float(fi['prometido']),
            'n': int(fi.get('n') or 0),
            'veredicto_banda': fi.get('veredicto', ''),
            'real': fi.get('real'), 'prometido': fi.get('prometido'),
            'fuente': f"{fi.get('n')} picks publicados de este mercado"})

    c = _f(cuota)
    if c is not None:
        try:
            import calibrador_bandas as cb
            banda = cb.nombre_banda(c)
            curva = ((cb.cargar().get('bandas') or {}).get(banda) or {})
            calibrada = cb.calibrar(p, c)
            if curva.get('n_train') and calibrada is not None:
                cand.append({
                    'delta': float(calibrada) - p,
                    'n': int(curva['n_train']),
                    'veredicto_banda': ('conservador' if calibrada > p
                                        else 'optimista' if calibrada < p
                                        else 'de_fiar'),
                    'real': calibrada, 'prometido': p,
                    'fuente': f"{curva['n_train']:,} picks en la banda de "
                              f"cuota {banda}".replace(',', '.')})
        except Exception as e:
            logger.debug('[veredicto] calibrador de bandas: %s', e)

    if not cand:
        return vacio
    mejor = max(cand, key=lambda x: x['n'])
    delta = max(-CORRECCION_MAXIMA, min(CORRECCION_MAXIMA, mejor['delta']))
    return {'delta': round(delta, 4), 'medido': True, 'n': mejor['n'],
            'veredicto_banda': mejor['veredicto_banda'],
            'real': mejor['real'], 'prometido': mejor['prometido'],
            'fuente': mejor['fuente']}


def senales_visibles(pick: Dict, con_contexto: bool = False) -> List[Dict]:
    """Las señales de contexto, con su signo. Se ENSEÑAN, no deciden.

    `con_contexto=False` por defecto: consultar bajas sale a la red y esto se
    llama una vez por tarjeta. La vista de un partido concreto sí lo pide.
    """
    if not con_contexto:
        return []
    try:
        import scraper_contexto as sc
        p = pick or {}
        partido = str(p.get('partido') or '')
        h, a = (partido.split(' vs ') + ['', ''])[:2]
        crudas = sc.senales({'clave_liga': p.get('clave_liga'),
                             'home': h.strip(), 'away': a.strip(),
                             'partido': partido,
                             'deporte': str(p.get('deporte') or 'futbol').lower(),
                             'fecha': p.get('fecha')})
    except Exception as e:
        logger.debug('[veredicto] señales: %s', e)
        return []

    fuera = []
    for s in crudas:
        tipo = str(s.get('tipo') or '')
        # `scraper_contexto` emite tipos genéricos; el detalle trae el matiz
        detalle = str(s.get('detalle') or '')
        signo = 0
        if tipo in _EN_CONTRA or 'baja' in detalle.lower() or 'lesión' in detalle.lower():
            signo = -1
        elif tipo in _A_FAVOR or 'ganó' in detalle.lower():
            signo = +1
        if signo == 0:
            continue
        fuera.append({'signo': signo,
                      'texto': _ETIQUETA.get(tipo, tipo.replace('_', ' ')),
                      'detalle': detalle[:90]})
    return fuera[:4]


# ---------------------------------------------------------------------------
def evaluar(pick: Dict, con_contexto: bool = False) -> Dict:
    """El veredicto: meter o no, con su fuerza y su porqué en una línea.

    Barato por defecto: sin `con_contexto` no toca red ni disco pesado, para
    poder llamarse una vez por tarjeta sin repetir lo de la v216.
    """
    p = dict(pick or {})
    prob = _f(p.get('prob'))
    mercado = str(p.get('mercado') or '')
    cuota = _f(p.get('cuota'))

    base = {'veredicto': NO_METER, 'fuerza': 0.0, 'prob_modelo': prob,
            'prob_ajustada': prob, 'correccion': 0.0, 'medido': False,
            'razones': [], 'senales': [], 'mercado': mercado}
    if prob is None:
        return {**base, 'razones': ['sin probabilidad']}

    c = correccion(prob, mercado, cuota)
    ajustada = max(0.01, min(0.99, prob + c['delta']))

    # v243 — LA SEGUNDA OPINIÓN: LO QUE LA CASA DICE DE ESTA MISMA APUESTA.
    #
    # Va DESPUÉS de `correccion` a propósito, y no en su lugar. No es corregir
    # dos veces: `correccion` endereza el sesgo propio del modelo, y esto
    # promedia el resultado con una estimación INDEPENDIENTE del mismo suceso,
    # hecha por gente que se juega dinero.
    #
    # Medido sobre 47.948 partidos de `pick_ledger.csv` y 47.794 de
    # `pick_ledger_totales.csv`, la mezcla con el mercado baja el log-loss en
    # los cuatro mercados con p5 positivo y el 100 % de los remuestreos a
    # favor. Y por bandas separa muchísimo: en «Más de 2.5», banda 60-70 %,
    # los picks que concuerdan con la casa aciertan el 63,7 % (prometen 64,6)
    # y los que discrepan, el 49,7 %. La discrepancia no es ventaja: es error.
    #
    # El peso es 0,5 y NO el 0,0 que dicen los datos, porque el ledger guarda
    # cuotas de CIERRE y batir al cierre es casi imposible por construcción.
    # Todo el razonamiento y lo que se intentó para medirlo mejor está en
    # `concordancia.py`.
    conc = {'hay': False}
    try:
        import concordancia as _conc
        conc = _conc.evaluar(p, str(p.get('apuesta') or ''), mercado,
                             prob_modelo=ajustada)
        if conc.get('hay') and conc.get('p_mezcla') is not None:
            ajustada = float(conc['p_mezcla'])
    except Exception as e:
        logger.debug('[veredicto] concordancia: %s', e)

    razones = []
    if c['medido']:
        if c['veredicto_banda'] == 'optimista':
            razones.append(
                f"este {prob:.0%} en «{mercado}» históricamente acierta "
                f"{c['real']:.0%} ({c['n']} picks): va sobrado")
        elif c['veredicto_banda'] == 'conservador':
            razones.append(
                f"este {prob:.0%} en «{mercado}» históricamente acierta "
                f"{c['real']:.0%} ({c['n']} picks): se queda corto")
        else:
            razones.append(
                f"el {prob:.0%} se sostiene: {c['real']:.0%} real en "
                f"{c['n']} picks de este mercado")
    else:
        razones.append('sin histórico de este mercado y banda todavía')

    # v243 — la segunda opinión va la PRIMERA de las razones cuando las dos
    # fuentes se separan, porque entonces es lo más importante que hay que
    # saber de ese número.
    if conc.get('hay') and conc.get('razon'):
        if (conc.get('brecha') or 0) > 0.03:
            razones.insert(0, conc['razon'])
        else:
            razones.append(conc['razon'])

    mete = ajustada >= UMBRAL_METER
    if not mete and c['medido'] and c['veredicto_banda'] != 'optimista':
        razones.append(f'queda por debajo del {UMBRAL_METER:.0%} que pide '
                       f'una pata de combinada')

    # La fuerza es cuánto margen sobra (o falta) respecto al listón, llevada
    # a 0-1 sobre una ventana de 20 puntos. No es una probabilidad: es cuánto
    # de claro está el sí o el no.
    fuerza = max(0.0, min(1.0, abs(ajustada - UMBRAL_METER) / 0.20))

    senales = senales_visibles(p, con_contexto)
    return {**base,
            'veredicto': METER if mete else NO_METER,
            'fuerza': round(fuerza, 3),
            'prob_ajustada': round(ajustada, 4),
            'correccion': c['delta'],
            'medido': c['medido'],
            'n_muestra': c.get('n', 0),
            'veredicto_banda': c['veredicto_banda'],
            'concordancia': conc,          # v243: para pintar y para auditar
            'cuota': cuota,
            'razones': razones[:2],
            'senales': senales}


def evaluar_lista(picks, con_contexto: bool = False) -> List[Dict]:
    """Ordena por lo que hay que meter primero. Nunca lanza."""
    fuera = []
    for p in list(picks or []):
        if not isinstance(p, dict):
            continue
        try:
            v = evaluar(p, con_contexto)
            fuera.append({**v, 'pick': p})
        except Exception as e:
            logger.debug('[veredicto] pick saltado: %s', e)
    fuera.sort(key=lambda v: (v['veredicto'] != METER, -v['prob_ajustada']))
    return fuera


# ---------------------------------------------------------------------------
# La parte visual: poco texto, mucho color
# ---------------------------------------------------------------------------
CSS = """
<style>
.vp{display:flex;align-items:center;gap:.6rem;margin:.25rem 0;
    padding:.45rem .6rem;border-radius:.5rem;
    background:color-mix(in srgb, var(--fondo,#111) 92%, transparent);
    border-left:4px solid var(--vp-c)}
.vp-ic{font-size:1.15rem;line-height:1}
.vp-ap{flex:1;min-width:0;font-size:.86rem;
       overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vp-pb{position:relative;width:78px;height:7px;border-radius:4px;
       background:rgba(255,255,255,.12);overflow:hidden;flex:none}
.vp-pb>i{position:absolute;inset:0 auto 0 0;background:var(--vp-c)}
.vp-pb>u{position:absolute;top:-3px;bottom:-3px;width:2px;
         background:rgba(255,255,255,.55)}
.vp-n{font-variant-numeric:tabular-nums;font-weight:600;font-size:.86rem;
      color:var(--vp-c);min-width:3.1rem;text-align:right;flex:none}
.vp-d{font-size:.7rem;opacity:.72;min-width:3.2rem;text-align:right;flex:none}
.vp-s{display:flex;gap:.25rem;flex:none}
.vp-s span{font-size:.72rem;padding:.05rem .32rem;border-radius:.3rem;
           background:rgba(255,255,255,.08);white-space:nowrap}
.vp-up{color:var(--ok,#3ddc84)} .vp-dn{color:var(--no,#ff5c5c)}
</style>
"""


def html(v: Dict, etiqueta: str = '') -> str:
    """Una fila visual: icono, apuesta, barra con el listón, % y señales.

    El LISTÓN dibujado dentro de la barra es lo que hace la fila legible de un
    vistazo: no hay que comparar números contra un umbral que el usuario tiene
    que recordar — se ve si la barra lo pasa o no.
    """
    color = 'var(--ok,#3ddc84)' if v.get('veredicto') == METER \
        else 'var(--no,#ff5c5c)'
    icono = '🟢' if v.get('veredicto') == METER else '🔴'
    p = float(v.get('prob_ajustada') or 0.0)
    d = float(v.get('correccion') or 0.0)

    chips = []
    for s in (v.get('senales') or [])[:3]:
        clase = 'vp-up' if s['signo'] > 0 else 'vp-dn'
        flecha = '▲' if s['signo'] > 0 else '▼'
        chips.append('<span class="%s" title="%s">%s %s</span>'
                     % (clase, _esc(s.get('detalle', '')), flecha,
                        _esc(s['texto'])))

    delta = ''
    if v.get('medido') and abs(d) >= 0.005:
        delta = '<span class="vp-d">%s%.0f pp</span>' % (
            '+' if d > 0 else '−', abs(d) * 100)

    return (
        '<div class="vp" style="--vp-c:%s">'
        '<span class="vp-ic">%s</span>'
        '<span class="vp-ap">%s</span>'
        '<span class="vp-s">%s</span>'
        '%s'
        '<span class="vp-pb"><i style="width:%.0f%%"></i>'
        '<u style="left:%.0f%%"></u></span>'
        '<span class="vp-n">%.0f %%</span>'
        '</div>'
        % (color, icono,
           _esc(etiqueta or v.get('pick', {}).get('apuesta', '') or ''),
           ''.join(chips), delta,
           max(2.0, min(100.0, p * 100)), UMBRAL_METER * 100, p * 100))


def _esc(t) -> str:
    return (str(t).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def estilos(st) -> None:
    """Inyecta el CSS UNA vez. Lo llama quien pinta la lista, no cada fila.

    EL CSS NO PUEDE IR POR TARJETA. Medido con AppTest sobre la vista real: se
    inyectaba 138 veces, una por llamada a `pintar`, o sea 138 bloques
    `<style>` idénticos. No rompe nada —el navegador los colapsa— pero es peso
    muerto en cada render y en cada reenvío por websocket.

    Y NO PUEDE MEMORIZARSE EN `session_state`: ese diccionario sobrevive entre
    pasadas, pero Streamlit reconstruye la página entera en cada una. Marcarlo
    como «ya inyectado» dejaría la segunda pasada SIN estilos. Por eso lo
    controla el llamador, que sabe dónde empieza y acaba un render.
    """
    try:
        st.markdown(CSS, unsafe_allow_html=True)
    except Exception as e:
        logger.debug('[veredicto] estilos: %s', e)


def pintar(st, veredictos: List[Dict], titulo: str = '',
           con_estilos: bool = False) -> None:
    """Pinta la lista entera. Un solo `markdown`, que es lo barato."""
    if not veredictos:
        return
    trozos = [CSS] if con_estilos else []
    if titulo:
        trozos.append('<div style="font-size:.8rem;opacity:.7;'
                      'margin:.4rem 0 .2rem">%s</div>' % _esc(titulo))
    for v in veredictos:
        trozos.append(html(v, (v.get('pick') or {}).get('apuesta', '')))
    st.markdown(''.join(trozos), unsafe_allow_html=True)


if __name__ == '__main__':
    ejemplos = [
        {'apuesta': 'Goles: Menos de 3.5', 'mercado': 'Goles', 'prob': 0.80,
         'cuota': 1.45},
        {'apuesta': 'Goles: Más de 2.5', 'mercado': 'Goles', 'prob': 0.55,
         'cuota': 1.90},
        {'apuesta': 'Boulogne o empate', 'mercado': 'Doble oportunidad',
         'prob': 0.55, 'cuota': 1.75},
        {'apuesta': 'Ambos marcan: No', 'mercado': 'BTTS', 'prob': 0.53,
         'cuota': 1.80},
    ]
    for v in evaluar_lista(ejemplos):
        print('%-8s %-26s modelo %3.0f%% -> ajustada %3.0f%%  fuerza %.2f'
              % (v['veredicto'].upper(), v['pick']['apuesta'][:26],
                 v['prob_modelo'] * 100, v['prob_ajustada'] * 100,
                 v['fuerza']))
        for r in v['razones']:
            print('        · ' + r)
