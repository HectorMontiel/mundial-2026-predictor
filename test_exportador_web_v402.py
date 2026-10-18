#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas de regresión v402: el sitio no publica datos premium incompletos."""
import os
import sys
import types
import unittest
from unittest.mock import patch

import exportar_web
import combinadas_web


class Respuesta:
    def __init__(self, ok=True, datos=None, status_code=200, text=''):
        self.ok = ok
        self._datos = [] if datos is None else datos
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._datos


class ExportadorFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.entorno = patch.dict(os.environ, {
            'SUPABASE_URL': 'https://example.supabase.co',
            'SUPABASE_SERVICE_KEY': 'test-key-only',
        }, clear=True)
        self.entorno.start()
        self.addCleanup(self.entorno.stop)
        self.errores_fake = types.SimpleNamespace(_resultados_anunciados=lambda: {})
        self.modulos = patch.dict(sys.modules, {'errores_web': self.errores_fake})
        self.modulos.start()
        self.addCleanup(self.modulos.stop)

    def test_premium_without_supabase_credentials_blocks_publication(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'faltan SUPABASE_URL'):
                exportar_web.subir_supabase(
                    [{'id': 'pick-1', 'apuesta': '🔒 Pick Diamante'}],
                    [{'id': 'pick-1', 'apuesta': 'Victoria local'}],
                )

    def test_premium_write_failure_blocks_publication(self):
        import requests

        def post(url, *args, **kwargs):
            if url.endswith('/rest/v1/picks_premium'):
                return Respuesta(False, status_code=500, text='simulated failure')
            return Respuesta(True, status_code=201)

        with patch.object(requests, 'get', return_value=Respuesta(True, [])), \
             patch.object(requests, 'post', side_effect=post), \
             patch.object(requests, 'delete', return_value=Respuesta(True, status_code=204)):
            with self.assertRaisesRegex(RuntimeError, 'texto premium'):
                exportar_web.subir_supabase(
                    [{'id': 'pick-1', 'fecha': '2026-10-19', 'partido': 'A-B',
                      'inicio': '2026-10-19T18:00:00Z', 'apuesta': '🔒 Pick Diamante',
                      'estado': 'pendiente'}],
                    [{'id': 'pick-1', 'apuesta': 'Victoria local'}],
                )

    def test_failed_individual_retry_blocks_publication(self):
        import requests

        def post(url, *args, **kwargs):
            return Respuesta(False, status_code=500, text='simulated failure')

        with patch.object(requests, 'get', return_value=Respuesta(True, [])), \
             patch.object(requests, 'post', side_effect=post):
            with self.assertRaisesRegex(RuntimeError, 'incluso tras reintentar'):
                exportar_web.subir_supabase(
                    [{'id': 'pick-1', 'fecha': '2026-10-19', 'partido': 'A-B',
                      'inicio': '2026-10-19T18:00:00Z', 'apuesta': 'Gana A',
                      'estado': 'pendiente'}],
                    [],
                )


class CombinadasFailClosedTests(unittest.TestCase):
    def test_empty_pick_list_does_not_delete_existing_combinations(self):
        import requests
        with patch.object(requests, 'get') as get, patch.object(requests, 'delete') as delete:
            self.assertEqual(combinadas_web.subir([], 'https://example.supabase.co', 'test-key'), 0)
            get.assert_not_called()
            delete.assert_not_called()

    def test_ai_read_failure_blocks_combination_sync(self):
        import requests
        with patch.object(requests, 'get', return_value=Respuesta(False, status_code=503, text='offline')):
            with self.assertRaisesRegex(RuntimeError, 'ia_analisis'):
                combinadas_web.subir(
                    [{'id': 'pick-1', 'estado': 'pendiente', 'inicio': '2026-10-19T18:00:00Z',
                      'partido': 'A-B', 'cuota': 1.2, 'prob': .8, 'deporte': 'Fútbol'}],
                    'https://example.supabase.co',
                    'test-key',
                )


if __name__ == '__main__':
    unittest.main(verbosity=2)
