#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
¿El contexto del partido mejora el modelo? Se mide fuera de muestra.

LA PREGUNTA
-----------
El encargo pide correlacionar «lesiones, geografía, noticias actuales,
estadísticas de SofaScore». Antes de traer nada nuevo hay que separar dos
cosas que no se parecen en nada:

    LO QUE SE PUEDE MEDIR      geografía (altitud de la sede), descanso entre
                               partidos, congestión de calendario. Se derivan
                               de los `historico_*.csv` que ya están en disco,
                               así que se pueden reconstruir para los 47.794
                               partidos del ledger y comprobar si mejoran algo.

    LO QUE NO SE PUEDE MEDIR   lesiones, noticias, alineaciones. Se pueden
                               leer HOY, pero nadie guardó la lista de bajas
                               que tenía un equipo en marzo de 2024, así que
                               no hay contra qué contrastarlas. Entran como
                               informativas y marcadas `medido: False`, igual
                               que `contexto_mercado`.

Este módulo mide las primeras. Las segundas no se cuelan aquí disfrazadas.

CÓMO SE MIDE, Y POR QUÉ ASÍ
---------------------------
Corrección ajustada sobre el PASADO y evaluada sobre el FUTURO, partiendo la
serie por fecha. Ajustar y evaluar sobre lo mismo siempre «mejora»: es la
trampa que este proyecto ya pagó con el bootstrap ingenuo de la v197.

Se mide en las dos monedas que importan:

    log-loss   lo que penaliza equivocarse con confianza
    ECE        lo que mide si un «70 %» pasa el 70 % de las veces

Y el listón es que mejoren LAS DOS en el tramo de prueba. Una sola puede
mejorar por azar.

Uso:
    python validar_contexto.py            # mide y escribe el JSON
    python validar_contexto.py --informe  # sólo imprime
"""

import argparse
import datetime as _dt
import functools
import glob
import json
import logging
import os
import sys
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SALIDA = 'modelos/contexto_medido.json'

# Altitud en metros de las ciudades por encima de los 1.500 m, que es donde
# `altitud.py` y la literatura sitúan el efecto. El resto se trata como nivel
# del mar: no es que no tengan altitud, es que por debajo de ese umbral no se
# ha medido nada que valga la pena corregir.
ALTITUD = {
    'la paz': 3640, 'el alto': 4150, 'oruro': 3706, 'potosi': 4090,
    'potosí': 4090, 'cochabamba': 2558, 'sucre': 2810, 'tarija': 1875,
    'quito': 2850, 'ambato': 2577, 'riobamba': 2754, 'loja': 2060,
    'cuenca': 2560, 'ibarra': 2225, 'latacunga': 2750,
    'bogota': 2640, 'bogotá': 2640, 'tunja': 2820, 'manizales': 2160,
    'pasto': 2527, 'popayan': 1760, 'popayán': 1760, 'medellin': 1495,
    'medellín': 1495, 'pereira': 1411, 'chia': 2564, 'chía': 2564,
    'ciudad de mexico': 2240, 'ciudad de méxico': 2240, 'mexico city': 2240,
    'toluca': 2660, 'puebla': 2135, 'pachuca': 2400, 'queretaro': 1820,
    'querétaro': 1820, 'leon': 1815, 'león': 1815, 'guadalajara': 1566,
    'aguascalientes': 1880, 'san luis potosi': 1860, 'morelia': 1920,
    'san luis potosí': 1860, 'zacatecas': 2440,
    'cusco': 3400, 'cuzco': 3400, 'juliaca': 3825, 'arequipa': 2335,
    'huancayo': 3250, 'cajamarca': 2750, 'ayacucho': 2761,
    'guatemala': 1500, 'ciudad de guatemala': 1500,
    'san jose': 1170, 'san josé': 1170, 'addis abeba': 2355,
    'johannesburgo': 1753, 'johannesburg': 1753, 'pretoria': 1339,
    'nairobi': 1795, 'kampala': 1190, 'denver': 1609,
    'calgary': 1045, 'salt lake city': 1288,
}

# El corte de altitud a partir del cual se corrige. Sale de la medición: por
# debajo de 2.200 m el sesgo no se distingue del que hay a nivel del mar.
ALTITUD_CORTE = 2200

# Fracción de la serie que se usa para AJUSTAR. El resto es la prueba.
CORTE_ENTRENA = 0.70

# Partidos mínimos en el tramo de prueba para que un veredicto signifique algo.
N_MINIMO = 1000

# CUÁNTO TIENE QUE MEJORAR PARA QUE CUENTE.
#
# Un 0,1 % de mejora relativa del log-loss sobre todo el tramo, o un 1 % sobre
# el subconjunto al que la corrección de verdad toca. Sin un tamaño mínimo, el
# veredicto se encendía con una diferencia de 0,00003 —el cuarto decimal— y con
# dos métricas y puro ruido las dos mejoran una de cada cuatro veces.
MEJORA_MINIMA = 0.001
MEJORA_MINIMA_APLICA = 0.01


# SEDES DE LAS COMPETICIONES CUYO HISTÓRICO NO GUARDA LA CIUDAD.
#
# Medido: `historico_laliga.csv` y `historico_liga_mx.csv` no llevan columna
# `sede_ciudad`, y `sedes_futbol.csv` sólo cubre competiciones europeas. Sin
# esta tabla, la Liga MX entera se quedaba fuera de la medición de altitud — y
# es la competición donde más importa de las que el usuario juega: Toluca a
# 2.660 m, la Ciudad de México a 2.240 y Pachuca a 2.400.
#
# Es una lista a mano, y por eso va acotada: SÓLO los equipos cuya sede pasa de
# los 1.500 m. Los demás no hacen falta —el valor por defecto ya es «nivel del
# mar»— y cada entrada que no hace falta es una que se puede quedar obsoleta
# sin que nadie lo note.
CIUDAD_EQUIPO = {
    'toluca': 'Toluca', 'deportivo toluca': 'Toluca',
    'america': 'Ciudad de México', 'club america': 'Ciudad de México',
    'cruz azul': 'Ciudad de México', 'pumas': 'Ciudad de México',
    'pumas unam': 'Ciudad de México', 'unam pumas': 'Ciudad de México',
    'pachuca': 'Pachuca', 'cf pachuca': 'Pachuca',
    'queretaro': 'Querétaro', 'leon': 'León', 'club leon': 'León',
    'atlas': 'Guadalajara', 'guadalajara': 'Guadalajara',
    'chivas guadalajara': 'Guadalajara', 'necaxa': 'Aguascalientes',
    'san luis': 'San Luis Potosí', 'atl san luis': 'San Luis Potosí',
    'atletico san luis': 'San Luis Potosí',
    'puebla': 'Puebla', 'club puebla': 'Puebla',
}


def _normaliza(texto: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9 ]+', ' ', t.lower()).strip()


# Los nombres tal y como aparecen en los históricos, que no siempre son el
# nombre oficial: «El Alto, La Paz.» lleva dos ciudades y un punto, y
# «Coachabamba» es una errata de Cochabamba que está en los datos.
_ALIAS = {'coachabamba': 'cochabamba', 'mexico df': 'ciudad de mexico',
          'cdmx': 'ciudad de mexico', 'df': 'ciudad de mexico'}


@functools.lru_cache(maxsize=8192)
def altitud_de(ciudad) -> int:
    """Metros de la sede. Tolera erratas, acentos y «Ciudad, Provincia.».

    EL EMPAREJADO ES POR CONTENCIÓN Y GANA EL NOMBRE MÁS LARGO. Un exacto se
    perdía la mitad de los casos —medido: «El Alto, La Paz.» no casaba con
    ninguna de las dos ciudades que nombra— y quedarse con el primero que
    aparece haría que «La Paz» ganara a «El Alto» dentro de esa misma cadena,
    que son 500 metros de diferencia.
    """
    if not isinstance(ciudad, str) or not ciudad.strip():
        return 0
    t = _normaliza(ciudad)
    t = _ALIAS.get(t, t)
    directo = ALTITUD.get(t)
    if directo:
        return directo
    mejor, largo = 0, 0
    for nombre, metros in ALTITUD.items():
        n = _normaliza(nombre)
        if n and n in t and len(n) > largo:
            mejor, largo = metros, len(n)
    return mejor


# ---------------------------------------------------------------------------
# El contexto, reconstruido del histórico
# ---------------------------------------------------------------------------
def _historicos() -> pd.DataFrame:
    trozos = []
    for ruta in sorted(glob.glob('historico_*.csv')):
        clave = os.path.basename(ruta)[len('historico_'):-len('.csv')]
        try:
            d = pd.read_csv(ruta, usecols=['MATCH_ID', 'date', 'home_team',
                                           'away_team', 'sede_ciudad'])
        except Exception:
            continue          # los que no son de fútbol no tienen estas columnas
        d['clave'] = clave
        trozos.append(d)
    if not trozos:
        return pd.DataFrame()
    H = pd.concat(trozos, ignore_index=True)
    H['fecha'] = pd.to_datetime(H['date'], errors='coerce')
    return H.dropna(subset=['fecha', 'MATCH_ID'])


def contexto(H: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """MATCH_ID → altitud de la sede y días de descanso de cada equipo.

    El descanso se calcula con un PASE CRONOLÓGICO por equipo y competición:
    el partido de hoy sólo puede mirar los anteriores. Sin eso sería fuga, y
    una fuga en una variable de contexto es especialmente traicionera porque
    el número resultante parece razonable.
    """
    H = _historicos() if H is None else H
    if not len(H):
        return pd.DataFrame()
    largo = pd.concat([
        H[['clave', 'MATCH_ID', 'fecha', 'home_team']].rename(
            columns={'home_team': 'equipo'}).assign(lado='home'),
        H[['clave', 'MATCH_ID', 'fecha', 'away_team']].rename(
            columns={'away_team': 'equipo'}).assign(lado='away'),
    ], ignore_index=True).sort_values('fecha')
    largo['descanso'] = (
        largo['fecha']
        - largo.groupby(['clave', 'equipo'])['fecha'].shift(1)).dt.days
    piv = largo.pivot_table(index='MATCH_ID', columns='lado',
                            values='descanso', aggfunc='first')
    piv.columns = [f'descanso_{c}' for c in piv.columns]
    piv = piv.reset_index()
    sede = H[['MATCH_ID', 'sede_ciudad']].drop_duplicates('MATCH_ID')
    C = piv.merge(sede, on='MATCH_ID', how='left')
    # las competiciones sin `sede_ciudad` caen a la tabla por equipo
    local = H[['MATCH_ID', 'home_team']].drop_duplicates('MATCH_ID')
    C = C.merge(local, on='MATCH_ID', how='left')
    falta = C['sede_ciudad'].isna()
    if falta.any():
        C.loc[falta, 'sede_ciudad'] = (
            C.loc[falta, 'home_team'].astype(str).map(
                lambda e: CIUDAD_EQUIPO.get(_normaliza(e))))
    C['altitud'] = C['sede_ciudad'].map(altitud_de)
    C['en_altura'] = (C['altitud'] >= ALTITUD_CORTE).astype(int)

    # ACLIMATACIÓN: LO QUE DE VERDAD PESA NO ES LA ALTURA, ES EL DESNIVEL.
    #
    # Medido en esta misma tanda: con sólo Bolivia, Ecuador, Colombia y Perú,
    # corregir «ambos marcan» por altura mejoraba un 1,80 %. Al meter la Liga
    # MX —donde casi toda la liga juega en alto y los dos equipos llegan
    # aclimatados— la mejora bajó a 1,53 % y el ECE empeoró.
    #
    # O sea que «la sede está alta» no es la variable: lo es «el visitante
    # sube». Es exactamente lo que `altitud.py` modela desde la v10 para el
    # Mundial, y aquí se comprueba contra el histórico real.
    hab = (H.groupby(['clave', 'home_team'])['sede_ciudad']
           .agg(lambda s: s.dropna().mode().iloc[0]
                if len(s.dropna()) else None)
           .reset_index().rename(columns={'home_team': 'equipo',
                                          'sede_ciudad': 'ciudad_habitual'}))
    vis = H[['MATCH_ID', 'clave', 'away_team']].drop_duplicates('MATCH_ID')
    vis = vis.merge(hab, left_on=['clave', 'away_team'],
                    right_on=['clave', 'equipo'], how='left')
    vis['alt_visitante'] = vis['ciudad_habitual'].map(altitud_de)
    C = C.merge(vis[['MATCH_ID', 'alt_visitante']], on='MATCH_ID', how='left')
    C['alt_visitante'] = C['alt_visitante'].fillna(0)
    C['desnivel'] = C['altitud'] - C['alt_visitante']
    # el visitante SUBE de verdad: la sede pasa del corte y él viene de al
    # menos mil metros más abajo
    C['sube_visitante'] = ((C['altitud'] >= ALTITUD_CORTE)
                           & (C['desnivel'] >= 1000)).astype(int)
    C['dif_descanso'] = (C['descanso_home'] - C['descanso_away']).clip(-7, 7)
    return C


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def _logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _ece(p, y, cajas: int = 10) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    bordes = np.linspace(0.0, 1.0, cajas + 1)
    total = 0.0
    for i in range(cajas):
        lo, hi = bordes[i], bordes[i + 1]
        dentro = (p > lo) & (p <= hi) if i else (p >= lo) & (p <= hi)
        if not dentro.any():
            continue
        total += dentro.mean() * abs(p[dentro].mean() - y[dentro].mean())
    return float(total)


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoide(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, float)))


# ---------------------------------------------------------------------------
# La corrección, ajustada en el pasado y evaluada en el futuro
# ---------------------------------------------------------------------------
def evaluar(df: pd.DataFrame, col_p: str, col_y: str,
            variables: Tuple[str, ...]) -> Dict:
    """Ajusta un desplazamiento del logit por variable y lo evalúa después.

    El modelo de corrección es deliberadamente pobre —un desplazamiento
    constante del logit por cada variable— y esa pobreza es a propósito: con
    algo más flexible sería imposible distinguir «hay señal» de «he ajustado
    ruido». Si un desplazamiento fijo no mejora, no hay nada que rascar.
    """
    d = df.dropna(subset=[col_p, col_y] + list(variables)).copy()
    d = d.sort_values('fecha')
    if len(d) < N_MINIMO * 2:
        return {'medido': False, 'motivo': f'sólo {len(d)} partidos cruzados'}
    corte = int(len(d) * CORTE_ENTRENA)
    tr, te = d.iloc[:corte], d.iloc[corte:]
    if len(te) < N_MINIMO:
        return {'medido': False, 'motivo': f'tramo de prueba de {len(te)}'}

    y_tr = tr[col_y].astype(float).values
    z_tr = _logit(tr[col_p].values)
    # el desplazamiento que iguala la media observada en el tramo de ajuste,
    # por cada valor de la variable
    ajustes: Dict[str, Dict] = {}
    z_te = _logit(te[col_p].values)
    for v in variables:
        # EL VALOR MÁS FRECUENTE ES LA REFERENCIA Y NO SE TOCA.
        #
        # Si cada nivel recibe su propio desplazamiento —incluido el grupo
        # mayoritario— lo que se está haciendo no es corregir por contexto:
        # es recalibrar el modelo entero y atribuírselo a la variable. Con
        # `en_altura` eso movía los 45.000 partidos a nivel del mar y dejaba
        # la columna «donde aplica» idéntica al total, que fue como se
        # detectó. Fijando la referencia, el ajuste es la DIFERENCIA que
        # aporta el contexto y sólo toca a los partidos que lo tienen.
        base = tr[v].mode()
        base = float(base.iloc[0]) if len(base) else None
        col = {}
        for valor in sorted(tr[v].dropna().unique()):
            if base is not None and float(valor) == base:
                col[float(valor)] = 0.0
                continue
            m = tr[v] == valor
            if m.sum() < 200:
                continue
            obs = float(y_tr[m.values].mean())
            esp = float(_sigmoide(z_tr[m.values]).mean())
            if not (0 < obs < 1) or not (0 < esp < 1):
                continue
            col[float(valor)] = round(
                float(_logit([obs])[0] - _logit([esp])[0]), 5)
        ajustes[v] = col
        z_te = z_te + te[v].map(col).fillna(0.0).values

    p0, p1 = te[col_p].values, _sigmoide(z_te)
    y_te = te[col_y].astype(float).values
    ll0, ll1 = _logloss(p0, y_te), _logloss(p1, y_te)
    e0, e1 = _ece(p0, y_te), _ece(p1, y_te)

    # DONDE LA CORRECCIÓN DE VERDAD APLICA, que es la pregunta honesta.
    #
    # Medir sobre los 5.193 partidos del tramo cuando la corrección sólo toca
    # a los 300 que se juegan en altura diluye el efecto hasta el cuarto
    # decimal: el número global se mueve −0,00003 y eso no distingue una señal
    # de un redondeo. Sobre el subconjunto afectado, si hay algo, se ve.
    toca = (np.abs(p1 - p0) > 1e-9)
    sub = {}
    if toca.sum() >= 100:
        sub = {
            'n': int(toca.sum()),
            'logloss_antes': round(_logloss(p0[toca], y_te[toca]), 5),
            'logloss_despues': round(_logloss(p1[toca], y_te[toca]), 5),
            'ece_antes': round(_ece(p0[toca], y_te[toca]), 5),
            'ece_despues': round(_ece(p1[toca], y_te[toca]), 5),
        }
        sub['delta_logloss'] = round(
            sub['logloss_despues'] - sub['logloss_antes'], 5)
        sub['mejora'] = (sub['logloss_despues'] < sub['logloss_antes']
                         and sub['ece_despues'] < sub['ece_antes'])

    # EL LISTÓN EXIGE TAMAÑO, NO SÓLO SIGNO. Sin esto, «mejora» se encendía con
    # una diferencia de 0,00003 en el log-loss — un check que no puede fallar,
    # porque con dos métricas y ruido una de cada cuatro veces mejoran las dos.
    rel = (ll0 - ll1) / ll0 if ll0 else 0.0
    rel_sub = 0.0
    if sub:
        rel_sub = ((sub['logloss_antes'] - sub['logloss_despues'])
                   / sub['logloss_antes'] if sub['logloss_antes'] else 0.0)
    mejora = (rel >= MEJORA_MINIMA and e1 <= e0) or (
        bool(sub.get('mejora')) and rel_sub >= MEJORA_MINIMA_APLICA)
    return {
        'medido': True,
        'variables': list(variables),
        'n_ajuste': int(len(tr)), 'n_prueba': int(len(te)),
        'corte_fecha': str(te['fecha'].min())[:10],
        'ajustes': ajustes,
        'logloss_antes': round(ll0, 5), 'logloss_despues': round(ll1, 5),
        'ece_antes': round(e0, 5), 'ece_despues': round(e1, 5),
        'delta_logloss': round(ll1 - ll0, 5),
        'delta_ece': round(e1 - e0, 5),
        'mejora_relativa': round(rel, 5),
        'donde_aplica': sub,
        'mejora_relativa_donde_aplica': round(rel_sub, 5),
        'mejora': bool(mejora),
        'veredicto': 'mejora' if mejora else 'no_mejora',
    }


def validar() -> Dict:
    C = contexto()
    if not len(C):
        return {'medido': False, 'veredicto': 'sin_historicos'}

    doc: Dict = {'fecha': _dt.date.today().isoformat(),
                 'altitud_corte_m': ALTITUD_CORTE,
                 'corte_entrena': CORTE_ENTRENA,
                 'pruebas': {}}

    # --- 1X2: ¿gana el local? -------------------------------------------
    D = pd.read_csv('pick_ledger.csv')
    D = D.merge(C, left_on='match_id', right_on='MATCH_ID', how='left')
    D['fecha'] = pd.to_datetime(D['fecha'], errors='coerce')
    D['gana_local'] = (D['resultado'].astype(float) == 0).astype(int)
    doc['pruebas']['1x2_altura'] = evaluar(
        D, 'p_home', 'gana_local', ('en_altura',))
    doc['pruebas']['1x2_aclimatacion'] = evaluar(
        D, 'p_home', 'gana_local', ('sube_visitante',))
    doc['pruebas']['1x2_descanso'] = evaluar(
        D, 'p_home', 'gana_local', ('dif_descanso',))
    doc['pruebas']['1x2_ambas'] = evaluar(
        D, 'p_home', 'gana_local', ('en_altura', 'dif_descanso'))

    # --- goles ------------------------------------------------------------
    T = pd.read_csv('pick_ledger_totales.csv')
    T = T.merge(C, left_on='match_id', right_on='MATCH_ID', how='left')
    T['fecha'] = pd.to_datetime(T['fecha'], errors='coerce')
    T['over25'] = T['over_2.5_real'].astype(float).round()
    doc['pruebas']['goles_altura'] = evaluar(
        T, 'p_over_2.5', 'over25', ('en_altura',))
    doc['pruebas']['btts_altura'] = evaluar(
        T, 'p_btts', 'btts_real', ('en_altura',))
    doc['pruebas']['btts_aclimatacion'] = evaluar(
        T, 'p_btts', 'btts_real', ('sube_visitante',))
    doc['pruebas']['goles_aclimatacion'] = evaluar(
        T, 'p_over_2.5', 'over25', ('sube_visitante',))

    # cobertura, que es lo que decide cuánto se puede aplicar
    doc['cobertura'] = {
        'partidos_con_contexto': int(C['MATCH_ID'].nunique()),
        'con_altitud_medida': int((C['altitud'] > 0).sum()),
        'en_altura': int(C['en_altura'].sum()),
        'sube_visitante': int(C['sube_visitante'].sum()),
        'con_descanso': int(C['descanso_home'].notna().sum()),
    }
    buenas = [k for k, v in doc['pruebas'].items() if v.get('mejora')]
    doc['medido'] = True
    doc['mejoran'] = buenas
    doc['veredicto'] = 'hay_senal' if buenas else 'sin_senal'
    return doc


def _imprimir(doc: Dict) -> None:
    print('=' * 84)
    print('CONTEXTO DEL PARTIDO: ¿MEJORA EL MODELO?')
    print('=' * 84)
    c = doc.get('cobertura') or {}
    print(f"partidos con contexto reconstruido: {c.get('partidos_con_contexto')}"
          f" · en altura: {c.get('en_altura')}"
          f" · con descanso: {c.get('con_descanso')}")
    print()
    print(f"{'prueba':16s} {'n':>7s} {'logloss (todo)':>18s} {'n apl':>6s}"
          f" {'logloss donde aplica':>21s}  veredicto")
    for nombre, p in (doc.get('pruebas') or {}).items():
        if not p.get('medido'):
            print(f"{nombre:16s} {p.get('motivo', 'sin muestra')}")
            continue
        a = p.get('donde_aplica') or {}
        print(f"{nombre:16s} {p['n_prueba']:>7d} "
              f"{p['logloss_antes']:.5f}→{p['logloss_despues']:.5f} "
              f"{a.get('n', 0):>6d} "
              f"{a.get('logloss_antes', 0):.5f}→{a.get('logloss_despues', 0):.5f} "
              f"({p.get('mejora_relativa_donde_aplica', 0)*100:+.2f} %)  "
              f"{p['veredicto']}")
    print()
    print(f"VEREDICTO: {doc.get('veredicto')} · mejoran: {doc.get('mejoran')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--informe', action='store_true')
    args = ap.parse_args()
    doc = validar()
    try:
        _imprimir(doc)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            json.dumps(doc, ensure_ascii=False, indent=1).encode('utf-8'))
    if not args.informe:
        os.makedirs('modelos', exist_ok=True)
        with open(SALIDA, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f'\nEscrito {SALIDA}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
