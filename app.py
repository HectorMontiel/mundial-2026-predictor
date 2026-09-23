#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Punto de entrada para Streamlit Community Cloud.

La aplicación real (login con contraseña + predictor completo) vive en
dashboard_ui.py; este archivo existe porque el despliegue usa `app.py`
como main file. Ejecuta el dashboard en el mismo contexto de script.
"""

import runpy

# v303 — Streamlit Cloud NO reinicia el proceso al desplegar: sin esto, todo
# lo que `dashboard_ui` importa se queda en la versión anterior. Ver
# `recarga_modulos`.
try:
    import recarga_modulos
    recarga_modulos.recargar_cambiados()
except Exception:
    pass

runpy.run_path("dashboard_ui.py", run_name="__main__")
