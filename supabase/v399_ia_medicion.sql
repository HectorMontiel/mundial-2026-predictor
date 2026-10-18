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

-- Vista agregada que usa la cuenta para mostrar los aciertos de la IA.
-- Se crea después de v394/v396 porque depende de sus columnas.
create or replace view public.ia_aciertos with (security_invoker = false) as
with v as (
  select x.opinion, x.estado
    from public.ia_analisis a,
         lateral jsonb_to_recordset(coalesce(a.veredictos, '[]'::jsonb))
           x(apuesta text, opinion text, motivo text, estado text)
), c as (
  select
    count(*) filter (where a.ok_resultado) as r_ok,
    count(*) filter (where a.ok_resultado = false) as r_mal,
    count(*) filter (where a.ok_goles) as g_ok,
    count(*) filter (where a.ok_goles = false) as g_mal,
    count(*) filter (where a.ok_mercado) as m_ok,
    count(*) filter (where a.ok_mercado = false) as m_mal,
    count(*) filter (where a.ok_resultado and a.coincide) as c_ok,
    count(*) filter (where a.ok_resultado = false and a.coincide) as c_mal,
    count(*) filter (where a.ok_marcador) as mc_ok,
    count(*) filter (where a.ok_marcador = false) as mc_mal,
    count(*) filter (where a.ok_btts) as b_ok,
    count(*) filter (where a.ok_btts = false) as b_mal,
    count(*) filter (where a.ok_corners) as k_ok,
    count(*) filter (where a.ok_corners = false) as k_mal,
    count(*) filter (where a.ok_tarjetas) as t_ok,
    count(*) filter (where a.ok_tarjetas = false) as t_mal,
    count(*) filter (where a.evaluado is null) as pend,
    count(*) as total
  from public.ia_analisis a
)
select
  r_ok as resultado_ok,
  r_mal as resultado_mal,
  g_ok as goles_ok,
  g_mal as goles_mal,
  m_ok as mercado_ok,
  m_mal as mercado_mal,
  c_ok as coincide_ok,
  c_mal as coincide_mal,
  (select count(*) from v where opinion = 'en_contra' and estado = 'roja') as aviso_bien,
  (select count(*) from v where opinion = 'en_contra' and estado = 'verde') as aviso_mal,
  (select count(*) from v where opinion = 'a_favor' and estado = 'verde') as favor_bien,
  (select count(*) from v where opinion = 'a_favor' and estado = 'roja') as favor_mal,
  pend as pendientes,
  total as analizados,
  mc_ok as marcador_ok,
  mc_mal as marcador_mal,
  b_ok as btts_ok,
  b_mal as btts_mal,
  k_ok as corners_ok,
  k_mal as corners_mal,
  t_ok as tarjetas_ok,
  t_mal as tarjetas_mal
from c;
grant select on public.ia_aciertos to anon, authenticated;
notify pgrst, 'reload schema';