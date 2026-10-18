-- Prueba de humo contra un PostgreSQL limpio: tablas, permisos, precios e idempotencia.
-- Se ejecuta sólo en la base efímera de GitHub Actions, nunca en Supabase de producción.

DO $checks$
BEGIN
  IF to_regclass('public.ia_analisis') IS NULL THEN
    RAISE EXCEPTION 'FALLO: falta public.ia_analisis';
  END IF;
  IF to_regclass('public.paquetes') IS NULL THEN
    RAISE EXCEPTION 'FALLO: falta public.paquetes';
  END IF;
  IF to_regclass('public.compras') IS NULL THEN
    RAISE EXCEPTION 'FALLO: falta public.compras';
  END IF;
  IF to_regclass('public.ia_aciertos') IS NULL OR to_regclass('public.ia_medicion') IS NULL THEN
    RAISE EXCEPTION 'FALLO: faltan vistas de medición de IA';
  END IF;
  IF to_regprocedure('public.acreditar_compra(text,uuid,text,numeric)') IS NULL THEN
    RAISE EXCEPTION 'FALLO: falta acreditar_compra';
  END IF;
  IF has_function_privilege('anon','public.acreditar_compra(text,uuid,text,numeric)','EXECUTE')
     OR has_function_privilege('authenticated','public.acreditar_compra(text,uuid,text,numeric)','EXECUTE') THEN
    RAISE EXCEPTION 'FALLO: cliente puede invocar acreditar_compra';
  END IF;
  IF NOT has_function_privilege('service_role','public.acreditar_compra(text,uuid,text,numeric)','EXECUTE') THEN
    RAISE EXCEPTION 'FALLO: service_role no puede invocar acreditar_compra';
  END IF;
  IF has_table_privilege('anon','public.compras','INSERT')
     OR has_table_privilege('authenticated','public.compras','INSERT') THEN
    RAISE EXCEPTION 'FALLO: cliente puede insertar compras';
  END IF;
  IF (SELECT count(*) FROM public.paquetes) <> 4 THEN
    RAISE EXCEPTION 'FALLO: catálogo inicial de paquetes incompleto';
  END IF;
END
$checks$;

-- Precio por cuota, incluyendo el mercado de error y la selección no premium.
DO $prices$
DECLARE
  v_premium integer;
  v_error integer;
  v_free integer;
BEGIN
  SELECT public.precio_pick(jsonb_populate_record(null::public.picks,
    '{"id":"ci-premium","fecha":"2026-10-18","partido":"A-B","apuesta":"test","cuota":1.04,"elige":true,"prob":0.86,"tipo":"pick"}'::jsonb))
    INTO v_premium;
  SELECT public.precio_pick(jsonb_populate_record(null::public.picks,
    '{"id":"ci-error","fecha":"2026-10-18","partido":"A-B","apuesta":"error","cuota":3.5,"elige":false,"prob":0.5,"tipo":"error"}'::jsonb))
    INTO v_error;
  SELECT public.precio_pick(jsonb_populate_record(null::public.picks,
    '{"id":"ci-free","fecha":"2026-10-18","partido":"A-B","apuesta":"normal","cuota":1.5,"elige":false,"prob":0.79,"tipo":"pick"}'::jsonb))
    INTO v_free;
  IF v_premium <> 5 OR v_error <> 25 OR v_free <> 0 THEN
    RAISE EXCEPTION 'FALLO precios; premium=%, error=%, normal=%', v_premium, v_error, v_free;
  END IF;
END
$prices$;

-- La doble entrega de un mismo pago acredita exactamente una vez. Todo se
-- revierte dentro de la transacción de prueba; no deja compras ni cuentas sintéticas.
BEGIN;
UPDATE public.ajustes SET valor = '0' WHERE clave = 'monedas_bienvenida';
INSERT INTO auth.users (id, email, raw_user_meta_data)
VALUES ('fefefefe-fefe-fefe-fefe-fefefefefefe', 'ci-sharpicks@example.invalid', '{}'::jsonb);

DO $purchase$
DECLARE
  v_primera text;
  v_duplicada text;
  v_monedas integer;
  v_compras integer;
  v_movimientos integer;
BEGIN
  v_primera := public.acreditar_compra(
    'ci-pago-idempotente', 'fefefefe-fefe-fefe-fefe-fefefefefefe', 'prueba', 29.00
  );
  v_duplicada := public.acreditar_compra(
    'ci-pago-idempotente', 'fefefefe-fefe-fefe-fefe-fefefefefefe', 'prueba', 29.00
  );

  SELECT monedas INTO v_monedas FROM public.perfiles
   WHERE id = 'fefefefe-fefe-fefe-fefe-fefefefefefe';
  SELECT count(*) INTO v_compras FROM public.compras WHERE id = 'ci-pago-idempotente';
  SELECT count(*) INTO v_movimientos FROM public.movimientos
   WHERE usuario = 'fefefefe-fefe-fefe-fefe-fefefefefefe' AND motivo = 'compra Prueba';

  IF v_primera <> 'ok' OR v_duplicada <> 'ya'
     OR v_monedas <> 50 OR v_compras <> 1 OR v_movimientos <> 1 THEN
    RAISE EXCEPTION 'FALLO idempotencia: primera=%, duplicada=%, monedas=%, compras=%, movimientos=%',
      v_primera, v_duplicada, v_monedas, v_compras, v_movimientos;
  END IF;
END
$purchase$;
ROLLBACK;

SELECT 'PASS: instalación limpia, tablas/vistas, permisos, precios e idempotencia de compra' AS test_result;
