# -*- coding: utf-8 -*-
"""
v303 — LOS MÓDULOS DEL PROYECTO SE RECARGAN CUANDO CAMBIAN EN DISCO.

EL FALLO, VISTO EN PRODUCCIÓN EL 2026-09-23
Tras desplegar la v302 el usuario mandó dos capturas: la Capa 1 sí había
cambiado, pero la tarjeta seguía con la tira «ESTABILIDAD DEL MERCADO» y la
recomendada en caja grande, la Capa 1 no seguía la pestaña de día y la
Escalera no tenía mando de día. Las tres cosas tienen la misma causa:

    · `dashboard_ui.py` se ejecuta con `runpy` en CADA pasada: siempre es el
      código nuevo. Por eso la Capa 1 cambió.
    · Todo lo que importa (`dia_picks`, `modo_modelo`, `escalera`...) vive en
      `sys.modules`, y el proceso de Streamlit Cloud NO se reinicia al
      desplegar: sigue sirviendo la versión que cargó al arrancar.
    · Con el `dia_picks` viejo no existían `modo_de_vista` ni `PASADO`, así
      que la pantalla nueva caía a su respaldo («hoy») sin decir nada.

La v301 ya lo había sufrido con `escalera` y lo parcheó recargando ESE
módulo. Esto lo hace para todos, de una vez.

CÓMO
    · La primera vez que este módulo corre en un proceso, recarga TODOS los
      módulos del proyecto que ya estuvieran importados. En un proceso nuevo
      no hay ninguno (no cuesta nada); en uno viejo que acaba de recibir un
      despliegue, son justo los que están obsoletos.
    · Después recuerda la fecha de cada fichero y sólo recarga los que
      cambien. Un despliegue es un `git pull`: cambia la fecha.

Sólo toca módulos cuyo fichero está en la carpeta del proyecto: nunca
Streamlit, pandas ni nada instalado.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

RAIZ = os.path.dirname(os.path.abspath(__file__))
_VISTOS: Dict[str, float] = {}
_ESTRENADO: List[bool] = []


def _del_proyecto(mod, raiz: str) -> Optional[str]:
    f = getattr(mod, '__file__', None)
    if not f or not str(f).endswith('.py'):
        return None
    f = os.path.abspath(f)
    return f if os.path.dirname(f) == raiz else None


def recargar_cambiados(raiz: Optional[str] = None) -> List[str]:
    """Recarga los módulos del proyecto que cambiaron. NUNCA lanza.

    Devuelve los nombres recargados (para el log y para el test).
    """
    raiz = os.path.abspath(raiz or RAIZ)
    primera = not _ESTRENADO
    if primera:
        _ESTRENADO.append(True)
    hechos: List[str] = []
    for nombre, mod in list(sys.modules.items()):
        if nombre in ('__main__', __name__) or mod is None:
            continue
        f = _del_proyecto(mod, raiz)
        if not f:
            continue
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        previo = _VISTOS.get(nombre)
        if (primera or (previo is not None and mt > previo)):
            try:
                importlib.reload(mod)
                hechos.append(nombre)
            except Exception as e:
                logger.warning('[recarga] %s no se pudo recargar: %s: %s',
                               nombre, type(e).__name__, e)
        _VISTOS[nombre] = mt
    if hechos:
        logger.info('[recarga] %d módulos recargados: %s', len(hechos),
                    ', '.join(sorted(hechos)[:20]))
    return hechos
