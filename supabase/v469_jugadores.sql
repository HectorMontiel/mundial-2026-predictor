-- v469 — quién puede anotar y tirar a puerta 1+/2+ (jugadores_prob.py): una columna jsonb en
-- picks con {h: [...], a: [...]}. Migración NUEVA: no se re-ejecuta ninguna anterior.
alter table public.picks add column if not exists jug jsonb;
notify pgrst, 'reload schema';
