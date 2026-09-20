# -*- coding: utf-8 -*-
"""
v258 — El historial entre los dos equipos pesa en el 1X2.

LO QUE PIDIÓ EL USUARIO
«Tú te preferiste ir por el visitante o empate y al final terminó perdiendo;
cuando se analiza el histórico, ahí mismo en la barrita se ve cómo el
Leverkusen tiene un mejor pronóstico en el H2H, el que es más fuerte. Eso es
lo que tienes que analizar también del histórico.»

LO QUE DICE LA MEDICIÓN, QUE NO ES EXACTAMENTE ESO
Medido sobre `pick_ledger_total.csv`, 15.473 partidos de fútbol con al menos
tres cruces previos, construyendo el H2H **sólo con los cruces anteriores a
cada partido** para que no pueda filtrarse el futuro:

    tramo de H2H del local      n        dijo    ganó    sesgo
    0,00-0,35                4.739      0,372   0,355   -0,017
    0,35-0,50                1.842      0,412   0,418   +0,006
    0,50-0,65                4.544      0,458   0,460   +0,002
    0,65-1,00                4.348      0,526   0,546   **+0,020**

O sea: cuando el H2H favorece claramente al local, el modelo lo subestima
**dos puntos**. Es real y es sistemático, pero es dos puntos, no veinte.

Y el caso exacto del Leverkusen —el modelo va con visitante/empate y el H2H
dice lo contrario— son 2.019 partidos: el modelo decía que el local gana el
41,2 % y ganó el 42,3 %. Un punto de diferencia. **Aquel boleto se perdió por
varianza, no por un punto ciego.** Conviene decirlo para no prometer lo que
esto no hace.

HACIA DÓNDE SE ENCOGE EL HISTORIAL, QUE ERA EL ERROR
La primera versión encogía el H2H hacia 0,5. Suena razonable —diez cruces son
pocos— pero tiene un efecto que no se pidió: arrastra al centro CUALQUIER
probabilidad extrema aunque el historial esté de acuerdo con el modelo. Eso no
es el historial informando: es regresión a la media disfrazada de H2H. Se vio
en el tablero, en un aviso que se contradecía solo: «Volos NFC ganó 1, empató
1 y perdió 8 — le va mejor de lo que decía el modelo».

El ancla correcta es la probabilidad DEL MODELO, de forma que sólo pese lo que
el historial discrepa de lo que ya se decía:

    p' = p + w · n/(n+K) · (tasa_H2H − p)

Medido sobre los mismos 15.473 partidos, gana en las dos cosas:

    ancla                 mejor w    mejora      p5        contradice la
                                                           lectura simple
    0,5                   0,10      +0,00253   +0,00077        45 %
    la probabilidad p     0,20      +0,00258   +0,00090        20 %

Y con esta forma el mensaje es coherente POR CONSTRUCCIÓN: el número sube si y
sólo si `tasa_H2H > p`, que es exactamente lo que dice el aviso («le va mejor
de lo que decía el modelo»). Con el ancla en 0,5 eso no se cumplía y el texto
podía mentir sin que nadie lo notara.

DOS CAUTELAS QUE SON PARTE DEL DISEÑO
  · Tres cruces no valen lo que diez: el historial pesa `n/(n+6)` de su
    discrepancia. Sin eso, un 3-0 en tres partidos movería la probabilidad
    como si fueran veinte.
  · No se aplica si el 1X2 YA VIENE ENCOGIDO hacia el mercado. La medición se
    hizo sobre la probabilidad del modelo; aplicarla encima de una ya
    arrastrada al precio empujaría en dirección CONTRARIA al mercado, que es
    la referencia más fiable que hay, y eso no se ha medido.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# el óptimo medido con el ancla en el modelo (ver la cabecera)
PESO = 0.20
# encogimiento del H2H HACIA LA PROBABILIDAD DEL MODELO: con n cruces, el
# historial pesa n/(n+K) de lo que se separa de ella
K_ENCOGIMIENTO = 6.0
# por debajo de esto el H2H no es una muestra, es una anécdota
MIN_CRUCES = 3
MAX_CRUCES = 10


def tasa(clave_liga: str, home: str, away: str) -> Dict:
    """Los puntos del local en sus últimos cruces, y cuántos son.

        {'n': cruces contados, 'tasa': 0..1 desde el local de hoy,
         'encogida': ya tirada hacia 0,5 por el tamaño de la muestra}

    El empate cuenta medio, que es lo que se midió: la pregunta del 1X2 es
    «¿gana el local?», y un empate ni la confirma ni la niega del todo.
    """
    vacio = {'n': 0, 'tasa': None, 'encogida': 0.5}
    try:
        import contexto_partido as cx
        d = cx.h2h(clave_liga, home, away, n=MAX_CRUCES) or {}
    except Exception as e:
        logger.debug('[pata_h2h] h2h de %s-%s: %s', home, away, e)
        return vacio
    n = int(d.get('n') or 0)
    if n < MIN_CRUCES:
        return vacio
    v_h = float(d.get('v_home') or 0)
    emp = float(d.get('empates') or 0)
    t = (v_h + 0.5 * emp) / n
    return {'n': n, 'tasa': round(t, 4), 'ganados': int(v_h),
            'empatados': int(emp),
            'peso': round(n / (n + K_ENCOGIMIENTO), 4)}


def aplicar(pick: Dict, tri: Tuple[float, float, float],
            ya_encogido: bool = False) -> Dict:
    """El 1X2 con el historial mutuo dentro. NUNCA lanza.

        {'tri': (local, empate, visitante), 'hay': bool, 'razon': str, 'n': int}

    Se mueve el LADO LOCAL, que es el único que se midió, y el empate y el
    visitante se reescalan en proporción para que los tres sigan sumando 1.
    Repartir la diferencia de otra forma —toda al visitante, por ejemplo—
    sería una decisión sin medición detrás.
    """
    fuera = {'tri': tri, 'hay': False, 'razon': '', 'n': 0}
    if ya_encogido:
        # ver la cabecera: no se empuja contra el mercado con algo medido
        # sobre la probabilidad cruda
        return fuera
    try:
        pl, px, pv = (float(tri[0]), float(tri[1]), float(tri[2]))
    except (TypeError, ValueError, IndexError):
        return fuera
    s = pl + px + pv
    if not (0.9 < s < 1.1) or pl <= 0:
        return fuera
    try:
        import modo_modelo as mm
        h, a = mm._equipos(pick)
    except Exception as e:
        logger.debug('[pata_h2h] equipos: %s', e)
        return fuera
    if not (h and a and pick.get('clave_liga')):
        return fuera
    d = tasa(pick['clave_liga'], h, a)
    if d.get('tasa') is None:
        return fuera

    # EL ANCLA ES EL MODELO, NO EL 50 %. Ver la cabecera: encogiendo hacia
    # 0,5 el numero se iba al centro aunque el historial estuviera de acuerdo
    # con el modelo, y eso no es H2H — es regresion a la media disfrazada.
    # Aqui solo pesa lo que el historial DISCREPA de lo que ya se decia.
    pl2 = pl + PESO * float(d['peso']) * (float(d['tasa']) - pl)
    pl2 = max(0.01, min(0.97, pl2))
    resto = px + pv
    if resto <= 0:
        return fuera
    f = (1.0 - pl2) / resto
    nuevo = (round(pl2, 4), round(px * f, 4), round(pv * f, 4))
    # SI AL REDONDEAR NO SE VE, NO SE DICE.
    #
    # El umbral no es sobre la probabilidad cruda sino sobre el ENTERO que se
    # pinta. Con 0,005 salian avisos como «su probabilidad pasa del 57 % al
    # 57 %», que no informan de nada y ademas parecen un fallo de la
    # aplicacion. El numero SI se mueve —y se usa— pero no se anuncia un
    # cambio que el lector no puede ver.
    if int(round(pl * 100)) == int(round(pl2 * 100)):
        return {'tri': nuevo, 'hay': False, 'razon': '', 'n': d['n']}
    # Se cuenta en PARTIDOS GANADOS, que es como lo mira cualquiera al abrir
    # el historial, y no en «tasa encogida hacia 0,5». El usuario lo pidió
    # así: «tiene que ser entendible para el que va a apostar».
    # Los ganados son GANADOS. `tasa` cuenta el empate como medio partido
    # porque eso es lo que se midió, pero escribir «ganó 6» cuando fueron 5
    # victorias y 2 empates sería un mensaje simple Y FALSO, que es peor que
    # uno complicado. Los empates se dicen aparte, y sólo si los hubo.
    # EL BALANCE ENTERO, INCLUIDAS LAS DERROTAS.
    #
    # Sin ellas el aviso se contradecia solo: «Mjallby ganó 1 y empataron 3,
    # por eso contamos algo más con él» se lee como un error. Con las
    # derrotas delante —ganó 1, empató 3 y perdió 1— se entiende de un
    # vistazo que casi no pierde en ese cruce, que es justo lo que mueve el
    # número.
    sube = pl2 > pl
    _g = int(d.get('ganados', 0))
    _e = int(d.get('empatados', 0))
    _p = max(0, int(d['n']) - _g - _e)
    razon = ('🤝 Se han enfrentado %d veces: %s ganó %d, empató %d y '
             'perdió %d. %s, así que su probabilidad pasa del %d %% al %d %%.'
             % (d['n'], h, _g, _e, _p,
                'Le va mejor de lo que decía el modelo' if sube
                else 'Le va peor de lo que decía el modelo',
                int(round(pl * 100)), int(round(pl2 * 100))))
    return {'tri': nuevo, 'hay': True, 'razon': razon, 'n': d['n'],
            'tasa': d['tasa']}
