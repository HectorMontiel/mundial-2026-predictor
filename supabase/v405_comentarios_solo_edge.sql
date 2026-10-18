-- v405 — cerrar el INSERT directo de comentarios después de publicar la web nueva.
-- Ejecutar sólo cuando web/cuenta.js use la Edge Function comentario y ésta
-- responda correctamente en producción. La ruta antigua queda deshabilitada:
-- los comentarios entran por Edge -> registrar_comentario -> rate limit.
begin;
alter table public.comentarios enable row level security;
drop policy if exists "cualquiera deja comentario" on public.comentarios;
revoke insert on public.comentarios from public, anon, authenticated;
grant all on public.comentarios to service_role;
grant all on sequence public.comentarios_id_seq to service_role;
notify pgrst, 'reload schema';
