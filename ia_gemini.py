#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v387 — LA IA DE SHARPICKS (Gemini): ANALIZA, PREDICE Y SE LE MIDE.

El usuario: «que pueda analizar el partido con todo lo que tenemos —el
modelo, el reciente, el H2H, toda la información de la aplicación— y dé una
predicción, y vamos a cuantificar sus aciertos y sus errores».

1. ANALIZAR. Para los partidos de fútbol con picks que empiezan en las
   próximas 30 h, se le dan a Gemini SÓLO nuestros datos (las probabilidades
   del mercado sin margen, nuestros picks con lo que se cumplen, el error de
   cuota si hay, la forma, el H2H y las bajas) y devuelve, en JSON: un
   análisis de 3-4 líneas en español sencillo, SUS probabilidades de local /
   empate / visita, si habrá más o menos de 2,5 goles, su confianza (1-5),
   el pick que más le gusta y si coincide con el nuestro.
2. MEDIR. Al terminar el partido se le pone su ✅/❌ (resultado y goles) y
   el del FAVORITO DEL MERCADO, que es la vara mínima: si la IA no le gana a
   «elegir al favorito», no aporta. La vista `ia_aciertos` lo resume.

Una vez por partido (lo ya analizado no se repite) y con tope por pasada,
para quedar dentro del nivel gratis de Gemini. Sin `GEMINI_API_KEY` o sin la
base, no hace nada. Nunca falla.

Ejecutar:  python ia_gemini.py [--seco]
"""
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional

logger = logging.getLogger('ia_gemini')
DATOS = os.environ.get('WEB_DATOS', os.path.join('web', 'datos', 'hoy.json'))
PRIVADO = os.environ.get('WEB_PRIVADO', os.path.join('datos_privados', 'premium.json'))
MODELOS = [m for m in (os.environ.get('GEMINI_MODELO'), 'gemini-flash-latest', 'gemini-2.5-flash', 'gemini-2.5-flash-lite') if m]
MAX_POR_PASADA = int(os.environ.get('IA_MAX', '15'))
HORAS = 30
PAUSA_S = 4.5            # ~13 por minuto: debajo del límite del nivel gratis

ESQUEMA = {
    'type': 'OBJECT',
    'properties': {
        'analisis': {'type': 'STRING'},
        'p_local': {'type': 'NUMBER'}, 'p_empate': {'type': 'NUMBER'}, 'p_visita': {'type': 'NUMBER'},
        'pred_goles': {'type': 'STRING', 'enum': ['mas', 'menos']},
        'confianza': {'type': 'INTEGER'},
        'pick_ia': {'type': 'STRING'},
        'coincide': {'type': 'BOOLEAN'},
    },
    'required': ['analisis', 'p_local', 'p_empate', 'p_visita', 'pred_goles', 'confianza', 'pick_ia', 'coincide'],
}
INSTRUCCION = (
    'Eres el analista de fútbol de SharPicks, una app mexicana de pronósticos. Recibes los datos de UN partido '
    'en JSON. Reglas: 1) Usa SÓLO esos datos; no inventes jugadores, lesiones, rachas ni noticias que no estén. '
    '2) Estima TUS probabilidades de que gane el local, empaten o gane el visitante (suman 1) y si habrá más o '
    'menos de 2.5 goles. Las probabilidades del mercado son una base muy buena: muévete de ellas sólo si la '
    'forma, el H2H o las bajas lo justifican claramente. 3) Escribe un análisis de 3 o 4 frases en español '
    'sencillo, para alguien que no sabe de estadística: qué dicen los datos y por qué. Nada de garantías ni de '
    '"apuesta segura". 4) Di cuál de NUESTROS picks te gusta más (copia su texto) o "ninguno", y si coincide '
    'con tu lectura del partido. 5) Confianza de 1 (muy dudoso) a 5 (muy claro).'
)


def _id(fecha, partido) -> str:
    return hashlib.sha1(('%s|%s' % (fecha, partido)).encode('utf-8')).hexdigest()[:20]


def _utc(s) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(str(s).replace(' ', 'T')[:19]).replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _mercado() -> Dict:
    """partido → {'1x2': {...}, 'mas25': p} del cálculo del día (sin margen)."""
    out = {}
    try:
        import precalculo_dia as pc
        for p in ((pc.leer() or {}).get('datos') or {}).get('pronosticos') or []:
            im = p.get('implicitas') or {}
            x = im.get('1x2') or {}
            if x.get('home') is not None:
                g = ((im.get('goles') or {}).get('2.5') or {}).get('p')
                out[p.get('partido')] = {'1x2': {k: round(float(v), 3) for k, v in x.items()}, 'mas25': g}
    except Exception as e:
        logger.debug('[ia] mercado: %s', e)
    return out


def partidos(picks: List[Dict], ahora: dt.datetime) -> List[Dict]:
    """Los partidos de fútbol con picks que empiezan pronto, los mejores primero."""
    g = {}
    for p in picks:
        ini = _utc(p.get('inicio'))
        if (str(p.get('deporte')) != 'Fútbol' or p.get('estado') != 'pendiente' or ini is None
                or not (ahora < ini <= ahora + dt.timedelta(hours=HORAS))):
            continue
        g.setdefault((p.get('fecha'), p.get('partido')), []).append(p)
    out = []
    for (fecha, partido), ps in g.items():
        peso = max((3 if x.get('elige') else 2 if x.get('tipo') == 'error' else 1 if (x.get('prob') or 0) >= 0.85 else 0) for x in ps)
        out.append({'id': _id(fecha, partido), 'fecha': fecha, 'partido': partido, 'picks': ps, 'peso': peso,
                    'inicio': ps[0].get('inicio'), 'liga': ps[0].get('liga'), 'ctx': next((x.get('ctx') for x in ps if x.get('ctx')), None)})
    return sorted(out, key=lambda x: (-x['peso'], str(x['inicio'])))


def datos_del_partido(m: Dict, mercado: Dict) -> Dict:
    mk = mercado.get(m['partido']) or {}
    ctx = m.get('ctx') or {}
    home, _, away = str(m['partido']).partition(' vs ')
    return {
        'partido': m['partido'], 'local': home, 'visitante': away, 'liga': m.get('liga'),
        'probabilidades_del_mercado_sin_margen': mk.get('1x2'),
        'probabilidad_mercado_mas_de_2_5_goles': mk.get('mas25'),
        'nuestros_picks': [{'apuesta': x.get('apuesta'), 'cuota': x.get('cuota'),
                            'se_cumplen_las_apuestas_asi': x.get('prob'),
                            'error_de_cuota': x.get('tipo') == 'error',
                            'paga_de_mas': x.get('ventaja')} for x in m['picks']],
        'forma_local_ultimos_5': ctx.get('fl'), 'forma_visitante_ultimos_5': ctx.get('fv'),
        'nota_forma': 'G=ganó, E=empató, P=perdió; el más reciente a la derecha',
        'h2h_ultimos': [{'fecha': h[0], 'local': h[1], 'marcador': h[2], 'visitante': h[3]} for h in ctx.get('h2h') or []],
        'bajas_local': ctx.get('bl'), 'bajas_visitante': ctx.get('bv'),
    }


def preguntar(datos: Dict) -> Optional[Dict]:
    import requests
    k = os.environ.get('GEMINI_API_KEY')
    if not k:
        return None
    cuerpo = {'systemInstruction': {'parts': [{'text': INSTRUCCION}]},
              'contents': [{'role': 'user', 'parts': [{'text': json.dumps(datos, ensure_ascii=False)}]}],
              'generationConfig': {'temperature': 0.3, 'responseMimeType': 'application/json', 'responseSchema': ESQUEMA}}
    for modelo in MODELOS:
        try:
            for intento in range(3):          # 503 = Gemini saturado: se espera y se reintenta
                r = requests.post('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % modelo,
                                  params={'key': k}, json=cuerpo, timeout=60)
                if r.status_code != 503:
                    break
                time.sleep(6 * (intento + 1))
            if r.status_code == 429:
                logger.warning('[ia] %s: límite del nivel gratis; se sigue en la próxima pasada', modelo)
                return {'_limite': True}
            if not r.ok:
                logger.warning('[ia] %s respondió %s', modelo, r.status_code)
                continue
            txt = r.json()['candidates'][0]['content']['parts'][0]['text']
            d = json.loads(txt)
            d['_modelo'] = modelo
            return d
        except Exception as e:
            logger.warning('[ia] %s: %s', modelo, type(e).__name__)
    return None


def fila(m: Dict, d: Dict, mercado: Dict) -> Dict:
    pl, pe, pv = (max(0.0, float(d.get(k) or 0)) for k in ('p_local', 'p_empate', 'p_visita'))
    s = (pl + pe + pv) or 1.0
    pl, pe, pv = pl / s, pe / s, pv / s
    mk = (mercado.get(m['partido']) or {}).get('1x2') or {}
    return {'id': m['id'], 'fecha': m['fecha'], 'inicio': str(m['inicio']), 'deporte': 'Fútbol', 'liga': m.get('liga'),
            'partido': m['partido'], 'analisis': str(d.get('analisis') or '')[:900],
            'pred_resultado': ['local', 'empate', 'visita'][max(range(3), key=lambda i: (pl, pe, pv)[i])],
            'p_local': round(pl, 3), 'p_empate': round(pe, 3), 'p_visita': round(pv, 3),
            'pred_goles': d.get('pred_goles') if d.get('pred_goles') in ('mas', 'menos') else None,
            'confianza': max(1, min(5, int(d.get('confianza') or 3))), 'pick_ia': str(d.get('pick_ia') or '')[:160],
            'coincide': bool(d.get('coincide')), 'modelo': d.get('_modelo'),
            'p_mercado_local': mk.get('home'), 'p_mercado_empate': mk.get('draw'), 'p_mercado_visita': mk.get('away')}


# ---------- la base ----------
def _sb():
    url, key = os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_SERVICE_KEY')
    if not url or not key:
        return None
    return url.rstrip('/') + '/rest/v1/ia_analisis', {'apikey': key, 'Authorization': 'Bearer ' + key,
                                                      'Content-Type': 'application/json'}


def ya_hechos(sb) -> Optional[set]:
    import requests
    desde = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    r = requests.get(sb[0], headers=sb[1], params={'select': 'id', 'fecha': 'gte.' + desde, 'limit': 5000}, timeout=30)
    return {x['id'] for x in r.json()} if r.ok else None


def _final(partido: str, fecha: str, picks: List[Dict]):
    """(goles local, goles visita) del partido terminado: de nuestros picks ya
    liquidados o del histórico de Flashscore."""
    for p in picks:
        if p.get('partido') == partido and p.get('estado') in ('verde', 'roja') and p.get('marcador'):
            try:
                a, b = str(p['marcador']).split('-')
                return int(a), int(b)
            except Exception:
                pass
    try:
        import errores_web
        df, idx = errores_web._flashscore()
        home, _, away = partido.partition(' vs ')
        comun = sorted(set(idx.get(home.strip(), [])) & set(idx.get(away.strip(), [])))
        if comun:
            m = df.iloc[comun]
            m = m[m['date'].dt.strftime('%Y-%m-%d') >= str(fecha)]
            if len(m):
                r = m.iloc[0]
                return (int(r.gh), int(r.ga)) if r.home == home.strip() else (int(r.ga), int(r.gh))
    except Exception:
        pass
    return None


def evaluar(sb, picks: List[Dict]) -> int:
    """✅/❌ a lo que la IA predijo de los partidos ya terminados."""
    import requests
    hace = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2.5)).isoformat()
    r = requests.get(sb[0], headers=sb[1], timeout=30,
                     params={'select': '*', 'evaluado': 'is.null', 'inicio': 'lt.' + hace, 'limit': 500})
    n = 0
    for x in (r.json() if r.ok else []):
        g = _final(x['partido'], x['fecha'], picks)
        if not g:
            continue
        real = 'local' if g[0] > g[1] else ('visita' if g[0] < g[1] else 'empate')
        mk = [x.get('p_mercado_local'), x.get('p_mercado_empate'), x.get('p_mercado_visita')]
        fav = ['local', 'empate', 'visita'][max(range(3), key=lambda i: mk[i] or 0)] if all(v is not None for v in mk) else None
        cambio = {'marcador': '%d-%d' % g, 'ok_resultado': x['pred_resultado'] == real,
                  'ok_goles': (x['pred_goles'] == ('mas' if sum(g) > 2.5 else 'menos')) if x.get('pred_goles') else None,
                  'ok_mercado': (fav == real) if fav else None, 'evaluado': dt.datetime.now(dt.timezone.utc).isoformat()}
        u = requests.patch(sb[0], headers=sb[1], params={'id': 'eq.' + x['id']}, json=cambio, timeout=30)
        n += bool(u.ok)
    return n


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    seco = '--seco' in sys.argv
    sb = _sb()
    if not seco and (sb is None or not os.environ.get('GEMINI_API_KEY')):
        print('ia: sin GEMINI_API_KEY o sin la base: no se hace nada')
        return 0
    try:
        picks = json.load(open(DATOS, encoding='utf-8')).get('picks') or []
    except Exception as e:
        print('ia: sin datos del sitio (%s)' % e)
        return 0
    try:                                  # el texto real de lo premium (el público va tapado)
        reales = json.load(open(PRIVADO, encoding='utf-8'))
        for p in picks:
            if p.get('id') in reales:
                p['apuesta'] = reales[p['id']]
    except Exception:
        pass
    ahora = dt.datetime.now(dt.timezone.utc)
    evaluados = 0 if seco else evaluar(sb, picks)
    hechos = set() if seco else (ya_hechos(sb) or set())
    mercado = _mercado()
    nuevos = [m for m in partidos(picks, ahora) if m['id'] not in hechos][:MAX_POR_PASADA]
    if seco:
        for m in nuevos[:2]:
            print(json.dumps(datos_del_partido(m, mercado), ensure_ascii=False, indent=1))
        print('ia (seco): %d partidos por analizar' % len(nuevos))
        return 0
    import requests
    hechos_ahora = 0
    for m in nuevos:
        d = preguntar(datos_del_partido(m, mercado))
        if not d:
            continue
        if d.get('_limite'):
            break
        r = requests.post(sb[0], headers=dict(sb[1], Prefer='resolution=merge-duplicates,return=minimal'),
                          json=fila(m, d, mercado), timeout=30)
        hechos_ahora += bool(r.ok)
        time.sleep(PAUSA_S)
    print('ia: %d analizados, %d evaluados' % (hechos_ahora, evaluados))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
