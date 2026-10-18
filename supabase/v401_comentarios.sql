-- v401 — «Déjanos tu comentario»: cualquiera puede ESCRIBIR (no leer); el bot
-- los manda por correo al de Brevo (`comentarios_correo.py`) y los marca.
create table if not exists public.comentarios (
  id bigserial primary key,
  creado timestamptz not null default now(),
  tipo text check (tipo in ('idea', 'falla', 'otro')),
  texto text not null check (char_length(texto) between 3 and 2000),
  correo text check (correo is null or char_length(correo) <= 200),
  usuario uuid default auth.uid(),
  pagina text check (pagina is null or char_length(pagina) <= 300),
  enviado timestamptz
);
alter table public.comentarios enable row level security;
drop policy if exists "cualquiera deja comentario" on public.comentarios;
create policy "cualquiera deja comentario" on public.comentarios for insert to anon, authenticated
  with check (enviado is null and (usuario is null or usuario = auth.uid()));
grant insert on public.comentarios to anon, authenticated;
grant usage on sequence public.comentarios_id_seq to anon, authenticated;
grant all on public.comentarios to service_role;
grant all on sequence public.comentarios_id_seq to service_role;
notify pgrst, 'reload schema';
