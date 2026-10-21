-- v417 — LOS PLANES CON SUS NÚMEROS REALES Y LA IA «BLOQUEADA» A LA VISTA.
--
-- 1) historial_niveles: verdes y rojas de los últimos 30 días por nivel
--    (💎 Diamante, 🔷 Platino, 🥇 Oro, 🥈 Plata, 💰 Cuota alta), con la MISMA
--    regla que la página (`nivel` en web/app.js y exportar_web.py). Las
--    tarjetas de «sólo análisis» (sin pick) no cuentan.
create or replace view public.historial_niveles with (security_invoker = true) as
select case when tipo = 'error' then 'Cuota alta'
            when elige then 'Diamante'
            when prob >= 0.85 then 'Platino'
            when prob >= 0.80 then 'Oro'
            else 'Plata' end as nivel,
       (count(*) filter (where estado = 'verde'))::int as verdes,
       (count(*) filter (where estado = 'roja'))::int as rojas,
       min(fecha) as desde, max(fecha) as hasta
  from public.picks
 where fecha >= current_date - 30 and coalesce(tipo, 'pick') <> 'analisis'
 group by 1;
grant select on public.historial_niveles to anon, authenticated;

-- 2) ia_disponibles: QUÉ partidos tienen análisis de la IA (sólo el nombre y
--    la fecha, nunca el contenido), para enseñar «🤖 Análisis IA 🔒 VIP» a
--    quien no lo tiene. El contenido sigue protegido por la RLS de ia_analisis.
create or replace view public.ia_disponibles as
select distinct partido, fecha from public.ia_analisis where fecha >= current_date - 2;
grant select on public.ia_disponibles to anon, authenticated;
notify pgrst, 'reload schema';
