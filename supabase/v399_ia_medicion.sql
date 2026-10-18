-- v399 — «lo que metería la IA» con verde o roja, y si sus probabilidades son honestas
alter table public.ia_analisis add column if not exists ok_mejor boolean;

create or replace view public.ia_medicion as
with p as (
  select 'goles' as que, prob_goles as pr, ok_goles as ok from public.ia_analisis
  union all select 'ambos', case when btts = 'si' then prob_ambos else 1 - prob_ambos end, ok_btts from public.ia_analisis
  union all select 'corners', prob_corners, ok_corners from public.ia_analisis
  union all select 'tarjetas', prob_tarjetas, ok_tarjetas from public.ia_analisis
  union all select 'mejor', prob_mejor_apuesta, ok_mejor from public.ia_analisis
)
select que,
       case when pr < 0.6 then '50-60 %' when pr < 0.7 then '60-70 %' when pr < 0.8 then '70-80 %' else '80 % o más' end as banda,
       (count(*) filter (where ok))::int as ok, count(*)::int as total, round(avg(pr)::numeric, 3) as prometido
  from p
 where ok is not null and pr is not null and pr >= 0.5
 group by 1, 2;
grant select on public.ia_medicion to anon, authenticated;
notify pgrst, 'reload schema';
