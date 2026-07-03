#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Punto de entrada para Streamlit Community Cloud.

La aplicación real (login con contraseña + predictor completo) vive en
dashboard_ui.py; este archivo existe porque el despliegue usa `app.py`
como main file. Ejecuta el dashboard en el mismo contexto de script.
"""

import runpy

runpy.run_path("dashboard_ui.py", run_name="__main__")
