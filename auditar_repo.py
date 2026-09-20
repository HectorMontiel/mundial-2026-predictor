#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v212 — Auditoría automática del repositorio: qué módulos hay y quién los usa.

POR QUÉ ES UN SCRIPT Y NO UN DOCUMENTO ESCRITO A MANO
-----------------------------------------------------
Son 360 módulos. Un inventario escrito a mano nace desactualizado y nadie lo
vuelve a mirar: es exactamente el fallo que la auditoría busca (código que
nadie recuerda). Escrito como script, se vuelve a correr y dice la verdad del
día que se corre.

QUÉ MIDE, Y QUÉ NO PUEDE MEDIR
------------------------------
MIDE, leyendo el AST y el índice de git:
  · líneas, fecha del último commit que lo tocó
  · quién lo importa (grafo de imports real, no grep de texto)
  · si se llama a sí mismo como script (`__main__`)
  · marcas de medición en el propio código (`medido`, ROI, p5, REFUTADA)

NO PUEDE MEDIR, y por eso el estado nunca dice «muerto» a secas:
  · si un módulo se importa dinámicamente (`importlib`, `__import__`)
  · si lo llama un workflow de GitHub, un cron o el usuario a mano

Por eso el estado `sin_importadores` es una PREGUNTA, no una sentencia. La
v209 encontró justo ese caso: `filtro_contexto` tenía cero importadores y no
estaba muerto — estaba escrito, probado y sin enchufar.

Uso:
    python auditar_repo.py              # escribe AUDITORIA_v212.md
    python auditar_repo.py --resumen    # sólo imprime el resumen
"""

import argparse
import ast
import collections
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Set

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('auditar_repo')

SALIDA = 'AUDITORIA_v212.md'

# Prefijos de módulos que son SONDEOS de una versión concreta: se escribieron
# para contestar una pregunta, se contestó, y se quedaron. No son código
# muerto —son el cuaderno de laboratorio— pero tampoco son la aplicación.
PREFIJO_SONDEO = '_v'

# Los que arrancan solos por diseño (scripts de construcción y mantenimiento).
PREFIJOS_SCRIPT = ('build_', 'train_', 'importar_', 'import_', 'backfill_',
                   'publicar_', 'validar_', 'valida_', 'simular_', 'auditar_',
                   'test_', 'smoke_', 'medir_', 'calibrar_')

DEPORTES = ('futbol', 'nfl', 'mlb', 'tenis', 'kbo', 'nba')

# Palabras que delatan que un módulo lleva su medición encima.
MARCAS_MEDIDO = ('roi', 'p5', 'bootstrap', 'ece', 'brier', 'log_loss',
                 'medido', 'percentil')
# v226 — se añaden las formas en que este repositorio dice «medido y aparcado».
# `lineup_impact` (470 líneas) salía como bandera roja y no lo era: está medido
# —«+0,07 pp, dirección correcta, magnitud de ruido»— y su `lineup_coef.json`
# declara «NINGUNA liga los tiene adoptados». Eso no es código sin enchufar: es
# una hipótesis que se midió, no llegó al listón, y se dejó lista por si algún
# día cambia la fuente. Marcarla igual que a lo olvidado enseña a ignorar las
# banderas.
MARCAS_REFUTADO = ('refutada', 'refutado', 'no separa', 'anti-indicador',
                   'esta apagada', 'está apagada',
                   'no se adopt', 'ninguna liga los tiene adoptados',
                   'magnitud de ruido', 'no llega al liston',
                   'no llega al listón', 'queda listo por si',
                   'quedan listos por si')

# ---------------------------------------------------------------------------
# §1.2 — INVENTARIO DE REGLAS DE NEGOCIO
# ---------------------------------------------------------------------------
# Esto NO se puede derivar del código: una regla es una decisión con evidencia
# detrás, y la evidencia vive en mediciones, no en el AST. Va aquí —y no en un
# .md suelto— porque el script REGENERA el documento entero: una sección
# escrita a mano en el .md se perdería en la siguiente pasada.
#
# Columnas: regla · módulo · versión · evidencia medida · estado.
REGLAS = [
    {'regla': 'Ventaja de precio al lado local (Sección 1)',
     'modulo': 'clasificador.canal_del_pick', 'version': 'v128',
     'evidencia': 'p5 de bootstrap +1,73 % en el tramo de juicio; ROI +8,22 % '
                  'entre 5 % y 100 % de ventaja contra −11,48 % entre 0 y 5 %',
     'estado': 'VIGENTE — medida y positiva', 'tocar': 'no sin nueva evidencia'},
    {'regla': 'EV del modelo como criterio de selección',
     'modulo': 'alpha_finder / valor_apuesta', 'version': 'v128',
     'evidencia': '−4,66 % a −6,52 % de ROI sobre 37.158 apuestas; '
                  'anti-indicador del cierre',
     'estado': 'REFUTADA — se publica, no asciende',
     'tocar': 'no sin nueva evidencia'},
    {'regla': 'ECE por competición como índice de riesgo',
     'modulo': 'riesgo_liga', 'version': 'v202',
     'evidencia': 'Pearson −0,460 y Spearman −0,563 contra ROI real; '
                  '5,19 puntos entre mejor y peor cuartil (14.647 patas)',
     'estado': 'VIGENTE — medida', 'tocar': 'no sin nueva evidencia'},
    {'regla': 'IVL (volatilidad de goles) por liga',
     'modulo': 'riesgo_liga', 'version': 'v202',
     'evidencia': 'Pearson −0,031 contra ROI. Rango 0,54-0,72 en 69 ligas: '
                  'ningún umbral del encargo original era alcanzable',
     'estado': 'REFUTADA — se publica como descriptor, no bloquea',
     'tocar': 'ya resuelto; no reintroducir sin medir'},
    {'regla': 'Brier por competición → «🔴 Alta incertidumbre»',
     'modulo': 'alpha_finder.etiqueta_fiabilidad', 'version': 'v32',
     'evidencia': 'Brier real de los picks publicados (mínimo 30 por liga); '
                  'corte en 0,22',
     'estado': 'VIGENTE — medida', 'tocar': 'umbral 0,22 es convención, no '
                                            'está optimizado'},
    {'regla': 'Aclimatación por desnivel sobre el 1X2',
     'modulo': 'contexto_ampliado', 'version': 'v205',
     'evidencia': 'fuera de muestra: log-loss −1,54 %, ECE −34 % en 376 '
                  'partidos con subida ≥ 1.000 m',
     'estado': 'VIGENTE — la única señal de contexto que corrige un número',
     'tocar': 'no'},
    {'regla': 'Altura bruta de la sede',
     'modulo': 'contexto_ampliado', 'version': 'v205',
     'evidencia': '+0,10 % en 1X2 y +0,49 % en goles: ruido. Se cayó al '
                  'incluir la Liga MX',
     'estado': 'REFUTADA — se publica, no corrige', 'tocar': 'no'},
    {'regla': 'Rebote por entrenador nuevo (7 días, cuota < 1,85, −0,15)',
     'modulo': 'filtro_contexto', 'version': 'v202, enchufada en v209',
     'evidencia': 'NINGUNA. El efecto nunca se ha medido; la fuente '
                  '(Wikidata) sí funciona desde la v209',
     'estado': 'ACTIVA SIN MEDIR — avisa, no corrige probabilidad',
     'tocar': 'candidata a medición en cuanto haya ledger con la bandera'},
    {'regla': 'Tope de 2 patas por partido en combinada',
     'modulo': 'auditoria_pick.patas_compatibles', 'version': 'v209',
     'evidencia': 'ninguna; es una regla de sentido común sobre correlación',
     'estado': 'ACTIVA SIN MEDIR', 'tocar': 'barata de mantener'},
    {'regla': 'Divergencia extrema > 15 pp → −20 % de confianza',
     'modulo': 'auditoria_pick.divergencia', 'version': 'v209',
     'evidencia': 'ninguna', 'estado': 'ACTIVA SIN MEDIR — sólo recorta '
                                       'confianza',
     'tocar': 'medir cuando haya ledger con la bandera escrita'},
    {'regla': 'Cuota inflada ratio > 1,30 → −30 % de confianza',
     'modulo': 'auditoria_pick.cuota_inflada', 'version': 'v209',
     'evidencia': 'ninguna directa; emparentada con `EV_SOSPECHOSO`, que sí '
                  'está medido',
     'estado': 'ACTIVA SIN MEDIR', 'tocar': 'medir'},
    {'regla': 'Racha negativa ≥ 5 sin ganar',
     'modulo': 'auditoria_pick.racha_negativa', 'version': 'v209',
     'evidencia': 'ninguna', 'estado': 'ACTIVA SIN MEDIR — sólo avisa',
     'tocar': 'medir'},
    {'regla': 'Kelly fraccional ¼ con tope del 5 %',
     'modulo': 'bankroll_manager', 'version': 'v19',
     'evidencia': 'teoría estándar; el ¼ es práctica de oficio, no una '
                  'medición de este proyecto',
     'estado': 'VIGENTE — informativa', 'tocar': 'no urge'},
    {'regla': 'Excepción del tenis: prob ≥ 90 % con precio → verde',
     'modulo': 'clasificador.semaforo', 'version': 'v128',
     'evidencia': 'p5 +0,18 %: aprueba raspando',
     'estado': 'VIGENTE — medida, al límite',
     'tocar': 'vigilar; una racha mala la pone en negativo'},
    {'regla': 'Ventaja > 30 % es error de datos, no ventaja',
     'modulo': 'clasificador.semaforo', 'version': 'v128',
     'evidencia': 'entre dos casas reales es imposible; detecta partidos '
                  'desemparejados',
     'estado': 'VIGENTE', 'tocar': 'no'},
    {'regla': 'Modo Seguridad (prob ≥ 60 %, cuota 1,30-1,90, |Δ| ≤ 8 pp)',
     'modulo': 'modo_seguridad', 'version': 'v212',
     'evidencia': 'ver `backtesting_v212.md`: mejora Brier, hit rate y ROI en '
                  'fútbol y MLB, pero el p5 sigue negativo',
     'estado': 'APAGADA por la puerta de activación',
     'tocar': 'reevaluar con más ledger'},
    {'regla': 'Escalada de líneas por 3 de 4 fuentes',
     'modulo': 'escalada_lineas', 'version': 'v212',
     'evidencia': 'NO MEDIBLE: dos de las cuatro fuentes no existen en el '
                  'histórico (xG sintético, contexto no archivado)',
     'estado': 'APAGADA por no medible',
     'tocar': 'necesita xG observado y archivo de contexto hacia delante'},
]

# ---------------------------------------------------------------------------
# §1.6 — TRIAJE DE LOS MODULOS SIN IMPORTADORES
# ---------------------------------------------------------------------------
# La clasificacion automatica llega hasta donde llega: sabe quien importa a
# quien y quien comparte fichero de datos, pero no sabe PARA QUE se escribio un
# modulo. Esto es la lectura, uno a uno, de los que quedaban sin explicar.
#
# La regla del §10.1 del encargo v212 manda: «se documenta, se decide, no se
# borra sin test de regresion». Ninguno se ha borrado; lo que cambia es que
# ahora cada uno tiene una respuesta en vez de una bandera roja.
#
# Cuatro familias, y solo UNA pide accion:
#
#   generador   produce un catalogo o un dataset. Se corre cuando hace falta.
#   sondeo      contesto una pregunta concreta. La respuesta esta en su
#               docstring y en su JSON `_vNNN_*`. Es el cuaderno de laboratorio.
#   aparcada    hipotesis medida que no llego al liston. Se deja lista.
#   sin_enchufar  escrita, correcta y sin llamar. AQUI si hay decision.
TRIAJE_MODULOS = {
    # --- generadores y ingesta: se corren cuando hace falta ----------------
    'generar_universo_selecciones': ('generador',
        'v66. Genera el universo de selecciones del modelo internacional. Se '
        'corre al ampliar el catalogo, no en cada barrido.'),
    'generar_ligas_v68': ('generador',
        'v68. Genera el catalogo de ligas de futbol. Mismo caso.'),
    'entrenar_ligas_v68': ('generador',
        'v68. Entrena las competiciones nuevas y decide cuales se despliegan. '
        'Lo sustituyo el workflow de reentrenamiento diario.'),
    'precalcular_goleadores': ('generador',
        'v147. Precalcula la cache de goleadores EN EL RUNNER y no en el '
        'navegador. Es la misma idea que la v220 generalizo: calcular fuera '
        'del render.'),
    'ingesta_cuotas_leagues_cup': ('generador',
        'v100. Cuotas de cierre historicas de la Leagues Cup desde '
        'BetExplorer. Ingesta de una vez.'),
    'retrosheet_scraper': ('generador',
        'v29. Game logs historicos de MLB. Ingesta.'),
    'nba_scraper': ('generador',
        'v30. Game logs de NBA via nba_api. Ingesta.'),
    'pipeline_mundial': ('generador',
        'Pipeline diario del Mundial con tres fuentes abiertas.'),

    # --- sondeos: la pregunta ya tiene respuesta --------------------------
    'sondeo_casas': ('sondeo',
        'v126. Barrio las casas de apuestas para ver cuales se pueden '
        'integrar. La respuesta gobierna `cuotas_multi` desde entonces.'),
    'sondeo_odds_api': ('sondeo',
        'v127. Contesto si The Odds API cubre las 24 ligas sin historico de '
        'cuotas.'),
    'backtest_btts': ('sondeo',
        'v75. Contesto si el mercado BTTS merecia entrar en la Capa 1. La '
        'respuesta quedo en `_v75_btts.json`.'),

    # --- aparcadas: medidas, no llegaron al liston ------------------------
    'elo_global': ('aparcada',
        'v105. ELO cross-competicion para las copas, donde el ELO por '
        'competicion no converge (68 de 135 equipos de la Conference tienen 8 '
        'partidos o menos). Medido en `_v105_ab_elo_global.json`.'),
    'indice_forma': ('aparcada',
        'v99.1. Indice de Dispersion de Forma y factor de parque de la KBO. '
        'Medido en `_v102_ab_idf_*.json`.'),
    'nba_features': ('aparcada',
        'v70 Mejora F. Fatiga, viajes y avanzadas de NBA. El motor ya llevaba '
        'descanso y back-to-back; esto añadia densidad de calendario y millas.'),
    'tenis_saque': ('aparcada',
        'v69. Estadisticas de saque y resto desde TennisAbstract, que v67 dio '
        'por imposible. La fuente FUNCIONA; lo que falta es medir si el ELO de '
        'saque mejora algo.'),
    'kbo_preview': ('aparcada',
        'v104. Calidad del abridor y bullpen de la KBO desde Naver. Produce '
        '`kbo_preview.csv`, que hoy no lee nadie.'),
    'props_model': ('aparcada',
        'v45. Modelo de props de ponches. Lo sustituyo `beisbol_pitchers`, que '
        'si esta enchufado.'),
    'portfolio_optimizer': ('aparcada',
        'v33. Optimizador de Markowitz, marcado EXPERIMENTAL por su propio '
        'autor.'),

    # --- SIN ENCHUFAR: aqui si hay una decision que tomar ------------------
    # `ventaja_ponches` ESTUVO aqui y ya no: en la v227 se le escribio el
    # conductor que le faltaba (`snapshot_diario`, llamado desde
    # `precalculo_dia`), asi que dejo de ser un modulo sin importadores y su
    # ficha la borro este mismo fichero via `triaje_rancio`, que fallo en el
    # primer test en cuanto la explicacion dejo de ser cierta. Sigue sin
    # publicar picks: acumula `ponches_snapshots.csv` hasta que haya ROI y p5.
    'historico_agrupado': ('aparcada',
        'v184, CERRADO en v227. Agrupaba el historico de una copa con el de '
        'las ligas de sus equipos para predecir a los que no tienen muestra. '
        'Medido dos veces y NO se engancha: en global el logloss empeora '
        '(`_v184`), y en los huecos —los partidos que motivaron el modulo— '
        'acierta 0,4615 contra 0,5000 del modelo de la copa y ni gana a la '
        'base tonta (0,4808). Ver `_v227_agrupado_huecos.json`.'),
}


# ---------------------------------------------------------------------------
# §1.5 — DECISIONES ABIERTAS
# ---------------------------------------------------------------------------
DECISIONES_ABIERTAS = [
    {'asunto': '`ventaja_ponches` (267 líneas, v132) está escrito y nadie lo '
               'importa',
     'contexto': 'decide la escalera de ponches por VENTAJA DE PRECIO, que es '
                 'el único criterio con p5 positivo del proyecto. Es el mismo '
                 'patrón que `filtro_contexto`: escrito, correcto y sin '
                 'enchufar.',
     'decision': 'engancharlo a la vista de MLB o retirarlo con test de '
                 'regresión. NO se ha tocado en la v212: enchufarlo cambia '
                 'qué picks salen, y eso pide su propia medición.'},
    {'asunto': '`historico_agrupado` (144 líneas, v184) está escrito y nadie '
               'lo importa',
     'contexto': 'arregla el 1X2 de equipos de copa que no están en el '
                 'catálogo de su competición y salen con `prob: None`. '
                 'Medido en su día: 3 de 12 partidos de Champions.',
     'decision': 'engancharlo TOCA EL NÚCLEO PREDICTIVO, así que queda fuera '
                 'de esta tanda por la regla del propio encargo.'},
    {'asunto': '`feature_engineering` (411 líneas) y `handicap` (321) son '
               'grandes, activos y sin medición declarada',
     'contexto': 'dos o más módulos de producción dependen de cada uno y '
                 'ninguno lleva ROI, p5 ni ECE encima.',
     'decision': 'no es una avería: es deuda de medición. Ordenar por cuánto '
                 'deciden.'},
    {'asunto': 'NFL y KBO no tienen ledger fuera de muestra',
     'contexto': 'sin él, ninguna regla nueva puede activarse ahí: la puerta '
                 'del §7 exige ROI y p5, y no hay con qué calcularlos. KBO '
                 'además no tiene NINGUNA cuota histórica.',
     'decision': 'construir `build_ledger_nfl.py` y conseguir cuotas de KBO, '
                 'o aceptar que esos deportes se quedan sin reglas nuevas.'},
    {'asunto': 'El umbral 0,22 del Brier («Alta incertidumbre») no está '
               'optimizado',
     'contexto': 'es una convención heredada de la v32 y hoy gobierna '
                 'exclusiones de combinada y recortes de stake.',
     'decision': 'barrer el umbral contra ROI real y fijarlo con dato.'},
]


# ---------------------------------------------------------------------------
def _ficheros() -> List[str]:
    return sorted(f for f in os.listdir('.') if f.endswith('.py'))


def _fecha_git(ruta: str) -> str:
    """Fecha del último commit que tocó el fichero. '' si git no sabe."""
    try:
        out = subprocess.run(
            ['git', 'log', '-1', '--format=%ad', '--date=short', '--', ruta],
            capture_output=True, text=True, timeout=20)
        return (out.stdout or '').strip()
    except Exception as e:
        logger.debug('[auditoria] git log de %s: %s', ruta, e)
        return ''


def _analizar(ruta: str) -> Dict:
    """Lee un módulo y devuelve lo que se puede saber de él sin ejecutarlo."""
    ficha = {'modulo': ruta[:-3], 'fichero': ruta, 'lineas': 0,
             'importa': set(), 'tiene_main': False, 'defs': 0,
             'docstring': '', 'marcas_medido': [], 'marcas_refutado': [],
             'deportes': [], 'error': '', 'artefactos': set()}
    try:
        with open(ruta, encoding='utf-8') as f:
            src = f.read()
    except Exception as e:
        ficha['error'] = f'no se pudo leer: {e}'
        return ficha

    ficha['lineas'] = src.count('\n') + 1
    bajo = src.lower()
    ficha['marcas_medido'] = [m for m in MARCAS_MEDIDO if m in bajo]
    ficha['marcas_refutado'] = [m for m in MARCAS_REFUTADO if m in bajo]
    ficha['deportes'] = [d for d in DEPORTES if d in bajo]

    # v226 — LA ARISTA QUE FALTABA EN EL GRAFO: el ARTEFACTO.
    #
    # Dos módulos pueden depender uno del otro sin que ninguno importe al
    # otro: A escribe un JSON y B lo lee. El grafo de imports no ve esa
    # relación, y por eso `backtest_thresholds` salía como huérfano cuando en
    # realidad produce `umbrales_capa1.json`, que leen `alpha_finder`,
    # `dashboard_ui`, `frescura_datos` y `recalibrar_todo`. Marcar como
    # olvidado algo de lo que dependen cuatro módulos de producción es el peor
    # falso positivo posible: enseña a no fiarse de la lista.
    #
    # Se recogen los nombres de fichero de datos que el módulo menciona. No se
    # distingue lectura de escritura a propósito: para saber si un módulo está
    # ACOPLADO a producción basta con que compartan el fichero.
    import re as _re
    for m in _re.finditer(r"['\"]([A-Za-z0-9_\-./]+\.(?:json|csv|pkl|db|gz))['\"]",
                          src):
        nombre = os.path.basename(m.group(1))
        # los `historico_*.csv` y los `roi_bets_*.json` los toca medio
        # repositorio: acoplarían todo con todo y el criterio dejaría de
        # separar nada.
        if nombre.startswith(('historico_', 'roi_bets_', 'modelo', 'metadata')):
            continue
        ficha['artefactos'].add(nombre)

    try:
        arbol = ast.parse(src)
    except SyntaxError as e:
        ficha['error'] = f'no parsea: {e}'
        return ficha

    ficha['docstring'] = ((ast.get_docstring(arbol) or '').strip()
                          .split('\n')[0])[:160]
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            for a in n.names:
                ficha['importa'].add(a.name.split('.')[0])
        elif isinstance(n, ast.ImportFrom):
            if n.module and n.level == 0:
                ficha['importa'].add(n.module.split('.')[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ficha['defs'] += 1
    # `if __name__ == '__main__'`
    for n in arbol.body:
        if isinstance(n, ast.If):
            try:
                if '__name__' in ast.dump(n.test):
                    ficha['tiene_main'] = True
            except Exception:
                pass
    return ficha


def _estado(f: Dict, importadores: Set[str],
            acoplados: Optional[Set[str]] = None) -> str:
    """El estado del módulo, con el sesgo de NO declarar muerto sin pruebas."""
    nombre = f['modulo']
    if f['error']:
        return 'error'
    if nombre.startswith(PREFIJO_SONDEO):
        return 'sondeo_historico'
    if f['marcas_refutado']:
        return 'refutado_o_apagado'
    if importadores:
        return 'activo_medido' if f['marcas_medido'] else 'activo_sin_medir'
    # Nadie lo importa, pero comparte fichero de datos con producción: es un
    # productor de artefactos, no un huérfano. Ver la nota del artefacto.
    if acoplados:
        return 'productor_de_artefacto'
    # v222 — EL PUNTO CIEGO QUE ESTA AUDITORÍA TENÍA.
    #
    # Antes bastaba un `if __name__ == '__main__'` para salir clasificado como
    # `script_de_entrada` y dejar de aparecer en las banderas. Pero casi todo
    # módulo de librería de este repositorio lleva un bloque `__main__` de
    # demostración, así que la regla estaba absolviendo justo lo que hay que
    # cazar: una librería escrita, con su API, que nadie importa.
    #
    # Lo comprobó la propia auditoría de la v222: `archivo_contexto` y
    # `feedback_humano` tenían CERO importadores y salían limpios.
    #
    # Ahora sólo se considera script de entrada lo que su NOMBRE anuncia como
    # tal (`build_`, `train_`, `validar_`…). Un `__main__` sin ese prefijo
    # baja a `sin_importadores`, que es una pregunta, no una condena.
    if nombre.startswith(PREFIJOS_SCRIPT) or nombre in _invocados_por_workflow():
        return 'script_de_entrada'
    return 'sin_importadores'


_CACHE_WORKFLOWS: Optional[Set[str]] = None


def _invocados_por_workflow() -> Set[str]:
    """Módulos que algún workflow ejecuta con `python <modulo>.py`.

    ES LA EVIDENCIA QUE FALTABA. Un script de cron no lo importa nadie —lo
    invoca YAML— así que por el grafo de imports parece muerto. Mirar el
    nombre no bastaba: `liquidador`, `recalibrar_todo` y `frescura_datos` no
    empiezan por ninguno de los prefijos y son de los más vivos del repo.

    Al quitar la absolución por `__main__` salieron 38 banderas, casi todas
    falsas por este motivo. Con esto quedan las que de verdad no las llama
    nadie, ni Python ni CI.
    """
    global _CACHE_WORKFLOWS
    if _CACHE_WORKFLOWS is not None:
        return _CACHE_WORKFLOWS
    _CACHE_WORKFLOWS = set()
    import re as _re
    for carpeta in ('.github/workflows',):
        if not os.path.isdir(carpeta):
            continue
        for fichero in os.listdir(carpeta):
            if not fichero.endswith(('.yml', '.yaml')):
                continue
            try:
                with open(os.path.join(carpeta, fichero), encoding='utf-8') as f:
                    texto = f.read()
            except Exception as e:
                logger.debug('[auditoria] %s: %s', fichero, e)
                continue
            for m in _re.finditer(r'python3?\s+(?:-m\s+)?([A-Za-z_][\w]*)\.py',
                                  texto):
                _CACHE_WORKFLOWS.add(m.group(1))
            for m in _re.finditer(r'python3?\s+-m\s+([A-Za-z_][\w]*)', texto):
                _CACHE_WORKFLOWS.add(m.group(1))
    return _CACHE_WORKFLOWS


def construir() -> Dict:
    """El inventario entero. Devuelve el documento como diccionario."""
    ficheros = _ficheros()
    fichas = {}
    for ruta in ficheros:
        fichas[ruta[:-3]] = _analizar(ruta)

    # Grafo de imports: quién importa a quién, restringido a módulos locales.
    locales = set(fichas)
    importadores: Dict[str, Set[str]] = collections.defaultdict(set)
    for nombre, f in fichas.items():
        for dep in f['importa']:
            if dep in locales and dep != nombre:
                importadores[dep].add(nombre)

    for nombre, f in fichas.items():
        f['importadores'] = sorted(importadores.get(nombre, ()))
        f['n_importadores'] = len(f['importadores'])
        # los sondeos y los tests no cuentan como «uso en producción»
        f['importadores_produccion'] = sorted(
            i for i in f['importadores']
            if not i.startswith(PREFIJO_SONDEO) and not i.startswith('test_'))
        f['estado'] = _estado(f, set(f['importadores_produccion']))
        f['fecha'] = _fecha_git(f['fichero'])
        f['importa'] = sorted(f['importa'])

    # SEGUNDA PASADA para el acoplamiento por artefacto. Va aparte porque
    # necesita los `artefactos` de TODOS los modulos ya calculados: hacerlo en
    # el bucle de arriba comparaba contra los que aun no se habian visto.
    for nombre, f in fichas.items():
        f['acoplados'] = sorted(
            otro for otro, g in fichas.items()
            if otro != nombre
            and not otro.startswith(PREFIJO_SONDEO)
            and not otro.startswith('test_')
            and (f['artefactos'] & g['artefactos']))
        if f['estado'] == 'sin_importadores' and f['acoplados']:
            f['estado'] = 'productor_de_artefacto'
    for f in fichas.values():
        f['artefactos'] = sorted(f['artefactos'])

    conteo = collections.Counter(f['estado'] for f in fichas.values())
    return {'generado': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'n_modulos': len(fichas),
            'lineas_totales': sum(f['lineas'] for f in fichas.values()),
            'conteo_estado': dict(conteo),
            'modulos': fichas}


# ---------------------------------------------------------------------------
def banderas_rojas(doc: Dict) -> List[Dict]:
    """Lo que merece una decisión, ordenado por cuánto código hay detrás."""
    fuera = []
    for nombre, f in doc['modulos'].items():
        if f['estado'] == 'sin_importadores' and f['lineas'] >= 80:
            # §1.6: un módulo triado ya NO es un hallazgo pendiente. Tiene una
            # respuesta escrita de por qué nadie lo importa, y esa respuesta es
            # el entregable. Los únicos que siguen siendo bandera son los
            # `sin_enchufar`: código correcto que de verdad espera decisión.
            cat, porque = TRIAJE_MODULOS.get(nombre, (None, ''))
            if cat is not None and cat != 'sin_enchufar':
                continue
            fuera.append({
                'modulo': nombre, 'lineas': f['lineas'], 'fecha': f['fecha'],
                'tipo': ('escrito_sin_enchufar' if cat
                         else 'escrito_sin_importadores'),
                'nota': porque or ('nadie lo importa y no es script de '
                                   'entrada: o se engancha, o se retira con '
                                   'test de regresión')})
        elif f['estado'] == 'error':
            fuera.append({'modulo': nombre, 'lineas': f['lineas'],
                          'fecha': f['fecha'], 'tipo': 'no_parsea',
                          'nota': f['error']})
        elif (f['estado'] == 'activo_sin_medir' and f['lineas'] >= 300
              and len(f['importadores_produccion']) >= 2):
            fuera.append({
                'modulo': nombre, 'lineas': f['lineas'], 'fecha': f['fecha'],
                'tipo': 'grande_activo_sin_medicion',
                'nota': f"{len(f['importadores_produccion'])} módulos "
                        f"dependen de él y no lleva medición encima"})
    return sorted(fuera, key=lambda x: -x['lineas'])


def triaje_rancio(doc: Dict) -> List[str]:
    """Entradas del §1.6 que ya no describen la realidad del repo.

    Dos formas de envejecer mal. Una, el módulo se borró y la ficha se quedó
    hablando de un fichero que no existe. Otra, más traicionera: alguien lo
    enganchó, el módulo pasó a producción, y el triaje sigue diciendo que está
    aparcado. Esa segunda es la que convierte una tabla honesta en una coartada.
    """
    fuera = []
    for nombre, (cat, _) in sorted(TRIAJE_MODULOS.items()):
        f = doc['modulos'].get(nombre)
        if f is None:
            fuera.append(f'{nombre}: triado como «{cat}» y ya no está en el '
                         f'repo — quita la entrada')
        elif f['estado'] not in ('sin_importadores', 'sondeo_historico',
                                 'script_de_entrada', 'refutado_o_apagado',
                                 'productor_de_artefacto'):
            fuera.append(f'{nombre}: triado como «{cat}» pero ahora está '
                         f'«{f["estado"]}» — el triaje ya no vale, revísalo')
    return fuera


def cobertura_por_deporte(doc: Dict) -> Dict[str, List[str]]:
    """Matriz módulo × deporte, contando sólo módulos de producción."""
    fuera: Dict[str, List[str]] = {d: [] for d in DEPORTES}
    for nombre, f in doc['modulos'].items():
        if f['estado'] in ('sondeo_historico', 'error'):
            continue
        for d in f['deportes']:
            fuera[d].append(nombre)
    return {k: sorted(v) for k, v in fuera.items()}


# ---------------------------------------------------------------------------
def _tabla(filas: List[List[str]], cabecera: List[str]) -> str:
    out = ['| ' + ' | '.join(cabecera) + ' |',
           '|' + '|'.join(['---'] * len(cabecera)) + '|']
    for f in filas:
        out.append('| ' + ' | '.join(str(x) for x in f) + ' |')
    return '\n'.join(out)


def escribir(doc: Dict, ruta: str = SALIDA) -> str:
    rojas = banderas_rojas(doc)
    cobertura = cobertura_por_deporte(doc)
    mods = doc['modulos']

    part = [f"# AUDITORÍA v212 — inventario del repositorio\n",
            f"Generado automáticamente por `auditar_repo.py` el "
            f"{doc['generado']}. **Se vuelve a correr y se actualiza solo.**\n",
            f"- Módulos Python: **{doc['n_modulos']}**",
            f"- Líneas totales: **{doc['lineas_totales']:,}**".replace(',', '.'),
            ""]

    part.append("## 1.0 Reparto por estado\n")
    expl = {
        'activo_medido': 'lo importa producción y lleva su medición encima',
        'activo_sin_medir': 'lo importa producción y no declara medición',
        'script_de_entrada': 'se ejecuta solo (build, train, validación)',
        'sondeo_historico': 'sondeo `_vNNN_*`: cuaderno de laboratorio',
        'refutado_o_apagado': 'contiene marca de refutado o apagado',
        'sin_importadores': '**nadie lo importa** — pregunta abierta',
        'error': 'no se pudo leer o no parsea',
    }
    part.append(_tabla(
        [[e, n, expl.get(e, '')]
         for e, n in sorted(doc['conteo_estado'].items(), key=lambda x: -x[1])],
        ['estado', 'módulos', 'qué significa']))
    part.append("")

    part.append("## 1.1 Inventario — módulos de producción\n")
    part.append("Ordenado por número de módulos que dependen de él. Se listan "
                "los que tienen al menos un importador de producción.\n")
    prod = [(n, f) for n, f in mods.items() if f['importadores_produccion']]
    prod.sort(key=lambda x: (-x[1]['n_importadores'], -x[1]['lineas']))
    part.append(_tabla(
        [[n, f['lineas'], len(f['importadores_produccion']), f['fecha'] or '?',
          f['estado'], (f['docstring'] or '')[:70]]
         for n, f in prod[:70]],
        ['módulo', 'líneas', 'usado por', 'último commit', 'estado', 'qué es']))
    part.append(f"\n_Se muestran 70 de {len(prod)}._\n")

    part.append("## 1.2 Inventario de reglas de negocio\n")
    part.append("Una regla es una decisión con evidencia detrás. Esta tabla no "
                "sale del AST: se mantiene a mano en `auditar_repo.REGLAS` "
                "porque el documento se regenera entero.\n")
    part.append(_tabla(
        [[r['regla'], f"`{r['modulo']}`", r['version'], r['evidencia'],
          r['estado']] for r in REGLAS],
        ['regla', 'módulo', 'versión', 'evidencia medida', 'estado']))
    _vig = sum(1 for r in REGLAS if r['estado'].startswith('VIGENTE'))
    _ref = sum(1 for r in REGLAS if r['estado'].startswith('REFUTADA'))
    _sin = sum(1 for r in REGLAS if 'SIN MEDIR' in r['estado'])
    _apa = sum(1 for r in REGLAS if r['estado'].startswith('APAGADA'))
    part.append(f"\n**{len(REGLAS)} reglas: {_vig} vigentes y medidas · "
                f"{_ref} refutadas por datos propios · {_sin} activas sin "
                f"medir · {_apa} apagadas por la puerta de activación.**\n")

    part.append("## 1.3 Banderas rojas\n")
    if rojas:
        part.append(_tabla(
            [[r['modulo'], r['lineas'], r['fecha'] or '?', r['tipo'], r['nota']]
             for r in rojas[:40]],
            ['módulo', 'líneas', 'último commit', 'tipo', 'qué decidir']))
        part.append(f"\n_{len(rojas)} banderas en total._\n")
    else:
        part.append("Ninguna.\n")

    part.append("## 1.4 Cobertura por deporte\n")
    part.append("Módulos de producción que mencionan cada deporte. Es una "
                "cota SUPERIOR: mencionar no es cubrir.\n")
    part.append(_tabla(
        [[d, len(v), ', '.join(v[:8]) + ('…' if len(v) > 8 else '')]
         for d, v in cobertura.items()],
        ['deporte', 'módulos', 'algunos']))
    part.append("")

    part.append("## 1.6 Triaje de los modulos sin importadores\n")
    part.append("La clasificacion automatica sabe quien importa a quien y "
                "quien comparte fichero de datos, pero no sabe PARA QUE se "
                "escribio un modulo. Esto es la lectura, uno a uno.\n")
    _fam = {}
    for _m, (_cat, _txt) in TRIAJE_MODULOS.items():
        _fam.setdefault(_cat, []).append((_m, _txt))
    _ROTULO = {'generador': 'Generadores e ingesta — se corren cuando hace falta',
               'sondeo': 'Sondeos — la pregunta ya tiene respuesta',
               'aparcada': 'Aparcadas — medidas, no llegaron al liston',
               'sin_enchufar': 'SIN ENCHUFAR — aqui si hay decision'}
    for _cat in ('sin_enchufar', 'aparcada', 'sondeo', 'generador'):
        if _cat not in _fam:
            continue
        part.append("### %s\n" % _ROTULO[_cat])
        part.append(_tabla([[m, t] for m, t in sorted(_fam[_cat])],
                           ['modulo', 'que es y que se decide']))
        part.append("")

    part.append("## 1.5 Decisiones abiertas\n")
    part.append("Lo que necesita una decisión antes de tocar código. Ninguna "
                "se ha tomado por cuenta propia en la v212.\n")
    for i, d in enumerate(DECISIONES_ABIERTAS, 1):
        part.append(f"**{i}. {d['asunto']}**\n")
        part.append(f"{d['contexto']}\n")
        part.append(f"→ _{d['decision']}_\n")

    texto = '\n'.join(part)
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(texto)
    return texto


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--resumen', action='store_true')
    ap.add_argument('--json', default='')
    a = ap.parse_args()

    doc = construir()
    print(f"módulos: {doc['n_modulos']}  líneas: {doc['lineas_totales']:,}"
          .replace(',', '.'))
    for e, n in sorted(doc['conteo_estado'].items(), key=lambda x: -x[1]):
        print(f'  {e:24s} {n:4d}')
    rojas = banderas_rojas(doc)
    print(f'\nbanderas rojas: {len(rojas)}')
    for r in rojas[:15]:
        print(f"  {r['modulo']:34s} {r['lineas']:5d} líneas  {r['tipo']}")

    # Una tabla curada envejece: el módulo se borra, o se engancha y la excusa
    # deja de ser cierta. Si no se avisa, el triaje pasa de documentar a tapar.
    for rancio in triaje_rancio(doc):
        print(f'  AVISO  {rancio}')

    if a.json:
        serial = {k: (sorted(v) if isinstance(v, set) else v)
                  for k, v in doc.items() if k != 'modulos'}
        serial['modulos'] = {n: {k: (sorted(v) if isinstance(v, set) else v)
                                 for k, v in f.items()}
                             for n, f in doc['modulos'].items()}
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False, indent=1)
        print(f'\njson -> {a.json}')

    if not a.resumen:
        escribir(doc)
        print(f'\ndocumento -> {SALIDA}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
