-- v453 — «LO QUE DIJIMOS VS LO QUE SALIÓ»: los picks terminados agrupados por la
-- probabilidad que les dimos, con cuánto salieron de verdad. Pública (como el
-- historial): es la prueba de que nuestro 80 % sí es 80 %.
-- Migración NUEVA: no se re-ejecuta ninguna anterior.
create or replace view public.calibracion_picks with (security_invoker = true) as
select case when prob < 0.80 then 1 when prob < 0.85 then 2 when prob < 0.90 then 3 else 4 end as orden,
       case when prob < 0.80 then '70 a 80 %' when prob < 0.85 then '80 a 85 %' when prob < 0.90 then '85 a 90 %' else '90 % o más' end as banda,
       count(*)::int as n,
       round(avg(prob) * 100)::int as dijimos,
       round(100.0 * avg((estado = 'verde')::int))::int as salio,
       min(fecha) as desde
  from public.picks
 where estado in ('verde', 'roja') and prob >= 0.70 and coalesce(tipo, 'pick') not in ('analisis', 'error', 'combinada')
 group by 1, 2;
grant select on public.calibracion_picks to anon, authenticated;
notify pgrst, 'reload schema';
