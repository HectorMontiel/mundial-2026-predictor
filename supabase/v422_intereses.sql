-- v422 — «al crear la cuenta preguntarle qué deportes y ligas le interesan».
-- deportes ya existía; se agregan sus ligas (las cambia sólo él, como su nombre).
alter table public.perfiles add column if not exists ligas text[];
grant update (nombre, deportes, usuario, ligas) on public.perfiles to authenticated;
notify pgrst, 'reload schema';
