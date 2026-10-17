-- v394 — la IA dice qué metería y los goles de cada equipo (ver ia_gemini.py)
alter table public.ia_analisis
  add column if not exists goles_local_esperados numeric,
  add column if not exists goles_visita_esperados numeric,
  add column if not exists mejor_apuesta text,
  add column if not exists prob_mejor_apuesta numeric;
notify pgrst, 'reload schema';
