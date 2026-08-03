#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v86 — Escritura atómica de JSON, para archivos que se tocan durante una petición.

Por qué existe
--------------
Streamlit Cloud corre UN proceso y UNA hebra por sesión. Varios módulos hacen
lectura-modificación-escritura sobre el mismo archivo JSON en el camino de una
petición (el log de deriva de las predicciones, las cachés de clima y de
arbitraje, el estado de la API de fútbol). El patrón de siempre:

    with open(ruta, 'w') as f:      # <-- trunca a CERO inmediatamente
        json.dump(datos, f)

`open(..., 'w')` deja el archivo vacío antes de escribir nada. Si otra hebra
está leyéndolo en ese instante, ve un JSON truncado. Medido en
_v86_verifica_concurrencia.py con 6 hebras: **34,4 % de lecturas corruptas**.
Con esta función: **0 %**.

Los `try/except` que rodean esas escrituras evitaban la caída del proceso, pero
no evitaban que el archivo quedara corrupto y que la función dejara de servir
en silencio para todos los usuarios a partir de ese momento.

Cómo lo resuelve
----------------
Se escribe en un temporal exclusivo de la hebra y se hace `os.replace`, que es
atómico: cualquier lector ve el archivo entero antiguo o el entero nuevo, nunca
uno a medias.

Detalle de Windows: `os.replace` sobre un destino que otro proceso tiene abierto
lanza PermissionError (en POSIX no ocurre). Se reintenta unas cuantas veces con
espera corta; si aun así no se puede, se limpia el temporal y se devuelve False
en vez de dejar basura o propagar el fallo.
"""
import json
import os
import threading
import time

__all__ = ['escribir_json', 'leer_json']


def escribir_json(ruta: str, datos, *, indent=None, reintentos: int = 5) -> bool:
    """Vuelca `datos` a `ruta` de forma atómica. Devuelve True si lo consiguió."""
    tmp = f'{ruta}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=indent)
        espera = 0.01
        for intento in range(reintentos):
            try:
                os.replace(tmp, ruta)
                return True
            except PermissionError:
                # Windows: otro hilo/proceso tiene el destino abierto ahora mismo.
                if intento == reintentos - 1:
                    raise
                time.sleep(espera)
                espera *= 2
        return False
    except Exception:
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def escribir_texto(ruta: str, texto: str, *, reintentos: int = 5) -> bool:
    """
    Igual que `escribir_json` pero para texto plano (CSV commiteables).

    v92 — hace falta para `rendimiento_real.exportar`: el histórico de picks se
    persiste como CSV y se reescribe entero cada día, así que una escritura a
    medias lo dejaría truncado y se perdería el historial acumulado.
    """
    tmp = f'{ruta}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(texto)
        espera = 0.01
        for intento in range(reintentos):
            try:
                os.replace(tmp, ruta)
                return True
            except PermissionError:
                if intento == reintentos - 1:
                    raise
                time.sleep(espera)
                espera *= 2
        return False
    except Exception:
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def leer_json(ruta: str, por_defecto=None, *, reintentos: int = 4):
    """
    Lee un JSON tolerando que no exista, que esté corrupto de antes, o que otra
    hebra lo esté reemplazando justo en este instante.

    Ese último caso es específico de Windows: mientras `os.replace` sustituye el
    archivo, un lector puede recibir PermissionError durante unos milisegundos.
    En POSIX (que es lo que corre en Streamlit Cloud) no pasa, pero el reintento
    hace que el comportamiento sea el mismo en las dos plataformas y que el
    desarrollo en local no dé falsos fallos.

    Nótese la diferencia con el problema que esto sustituye: antes se leía JSON
    *truncado*, o sea datos malos que parecían buenos. Un PermissionError es un
    fallo limpio y reintentable.
    """
    vacio = {} if por_defecto is None else por_defecto
    if not os.path.exists(ruta):
        return vacio
    espera = 0.01
    for intento in range(reintentos):
        try:
            with open(ruta, encoding='utf-8') as f:
                return json.load(f)
        except PermissionError:
            if intento == reintentos - 1:
                return vacio
            time.sleep(espera)
            espera *= 2
        except Exception:
            return vacio
    return vacio
