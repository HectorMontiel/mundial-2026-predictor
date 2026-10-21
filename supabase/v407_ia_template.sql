-- v407 — la IA en TODOS los deportes con un template común: total y hándicap
-- (con su probabilidad y su verde o roja) además de lo de cada deporte.
alter table public.ia_analisis
  add column if not exists total_esperado numeric,
  add column if not exists linea_total numeric,
  add column if not exists pred_total text,
  add column if not exists prob_total numeric,
  add column if not exists ok_total boolean,
  add column if not exists linea_handicap numeric,
  add column if not exists pred_handicap text,
  add column if not exists prob_handicap numeric,
  add column if not exists ok_handicap boolean;

-- la calibración, ahora también del total y del hándicap (y por deporte)
drop view if exists public.ia_medicion;
create view public.ia_medicion as
with p as (
  select deporte, 'goles' as que, prob_goles as pr, ok_goles as ok from public.ia_analisis
  union all select deporte, 'ambos', case when btts = 'si' then prob_ambos else 1 - prob_ambos end, ok_btts from public.ia_analisis
  union all select deporte, 'corners', prob_corners, ok_corners from public.ia_analisis
  union all select deporte, 'tarjetas', prob_tarjetas, ok_tarjetas from public.ia_analisis
  union all select deporte, 'mejor', prob_mejor_apuesta, ok_mejor from public.ia_analisis
  union all select deporte, 'total', prob_total, ok_total from public.ia_analisis
  union all select deporte, 'handicap', prob_handicap, ok_handicap from public.ia_analisis
)
select coalesce(deporte, 'Fútbol') as deporte, que,
       case when pr < 0.6 then '50-60 %' when pr < 0.7 then '60-70 %' when pr < 0.8 then '70-80 %' else '80 % o más' end as banda,
       (count(*) filter (where ok))::int as ok, count(*)::int as total, round(avg(pr)::numeric, 3) as prometido
  from p
 where ok is not null and pr is not null and pr >= 0.5
 group by 1, 2, 3;
grant select on public.ia_medicion to anon, authenticated;
notify pgrst, 'reload schema';
