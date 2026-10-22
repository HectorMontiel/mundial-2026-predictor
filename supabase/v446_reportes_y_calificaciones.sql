-- v446 — LO QUE APORTAN LOS USUARIOS (sin tocar el modelo ni los picks).
--   1) «⚠️ Reportar un error»: un resultado mal liquidado, un equipo confundido o
--      un dato raro. El administrador lo revisa; si es real, el servidor le da
--      5 🪙 al usuario (a lo más 3 pagados por día). Nadie se paga desde la página.
--   2) «¿Te sirvió el análisis de la IA? 👍 / 👎»: SÓLO para medir; no da monedas
--      ni cambia cómo trabaja la IA.
--   3) La IA marca si su análisis usó noticias de la web (bajas, alineaciones) y
--      guarda cuáles: para medir si con noticias acierta más.
-- Migración NUEVA: no se re-ejecuta ninguna anterior.

-- ---------- 1) reportes de errores ----------
create table if not exists public.reportes (
  id uuid primary key default gen_random_uuid(),
  usuario uuid not null default auth.uid() references auth.users on delete cascade,
  partido text not null,
  pick text,
  tipo text not null check (tipo in ('resultado', 'equipo', 'dato', 'otro')),
  detalle text not null check (char_length(detalle) between 5 and 400),
  estado text not null default 'pendiente' check (estado in ('pendiente', 'aceptado', 'rechazado')),
  monedas integer not null default 0,
  nota text,
  creado timestamptz not null default now(),
  resuelto timestamptz
);
create index if not exists reportes_usuario on public.reportes (usuario, creado desc);
create index if not exists reportes_pendientes on public.reportes (estado, creado) where estado = 'pendiente';
alter table public.reportes enable row level security;
drop policy if exists "cada quien sus reportes; el admin todos" on public.reportes;
create policy "cada quien sus reportes; el admin todos" on public.reportes for select using (
  auth.uid() = usuario or exists (select 1 from public.perfiles f where f.id = auth.uid() and f.admin));
revoke all on table public.reportes from public, anon, authenticated;
grant select on public.reportes to authenticated;

create or replace function public.reportar(p_partido text, p_pick text, p_tipo text, p_detalle text) returns uuid
language plpgsql security definer set search_path = public as $reportar$
declare v_usuario uuid := auth.uid(); v_id uuid;
begin
  if v_usuario is null then raise exception 'Inicia sesión para reportar.'; end if;
  if coalesce(trim(p_partido), '') = '' then raise exception 'Falta el partido.'; end if;
  if char_length(coalesce(trim(p_detalle), '')) < 5 then raise exception 'Cuéntanos un poco más (5 letras o más).'; end if;
  if (select count(*) from public.reportes r where r.usuario = v_usuario and r.creado > now() - interval '1 day') >= 5 then
    raise exception 'Llevas 5 reportes hoy: gracias, vuelve mañana.';
  end if;
  if exists (select 1 from public.reportes r where r.usuario = v_usuario and r.partido = trim(p_partido)
             and r.tipo = p_tipo and r.estado = 'pendiente') then
    raise exception 'Ya reportaste eso de este partido; lo estamos revisando.';
  end if;
  insert into public.reportes (usuario, partido, pick, tipo, detalle)
  values (v_usuario, left(trim(p_partido), 200), nullif(left(coalesce(p_pick, ''), 64), ''), p_tipo, left(trim(p_detalle), 400))
  returning id into v_id;
  return v_id;
end;
$reportar$;

create or replace function public.resolver_reporte(p_id uuid, p_aceptar boolean, p_nota text default null) returns integer
language plpgsql security definer set search_path = public as $resolver$
declare r public.reportes; v_pagados int; v_monedas int := 0;
begin
  if not exists (select 1 from public.perfiles f where f.id = auth.uid() and f.admin) then
    raise exception 'Sólo el administrador revisa reportes.';
  end if;
  select * into r from public.reportes where id = p_id for update;
  if r.id is null then raise exception 'No existe ese reporte.'; end if;
  if r.estado <> 'pendiente' then raise exception 'Ese reporte ya se revisó.'; end if;
  if p_aceptar then
    select count(*) into v_pagados from public.reportes x
     where x.usuario = r.usuario and x.monedas > 0 and x.resuelto > now() - interval '1 day';
    if v_pagados < 3 then v_monedas := 5; end if;
  end if;
  update public.reportes set estado = case when p_aceptar then 'aceptado' else 'rechazado' end,
         monedas = v_monedas, nota = left(p_nota, 300), resuelto = now() where id = p_id;
  if v_monedas > 0 then
    update public.perfiles set monedas = monedas + v_monedas where id = r.usuario;
    insert into public.movimientos (usuario, cantidad, motivo) values (r.usuario, v_monedas, 'reporte de error aceptado');
  end if;
  return v_monedas;
end;
$resolver$;

revoke all on function public.reportar(text, text, text, text) from public, anon;
grant execute on function public.reportar(text, text, text, text) to authenticated;
revoke all on function public.resolver_reporte(uuid, boolean, text) from public, anon;
grant execute on function public.resolver_reporte(uuid, boolean, text) to authenticated;

-- ---------- 2) calificar el análisis de la IA (sólo se mide) ----------
create table if not exists public.ia_calificaciones (
  usuario uuid not null default auth.uid() references auth.users on delete cascade,
  analisis text not null,
  voto smallint not null check (voto in (-1, 1)),
  motivo text check (motivo is null or motivo in ('datos', 'nada_util', 'se_equivoco', 'otro')),
  creado timestamptz not null default now(),
  primary key (usuario, analisis)
);
alter table public.ia_calificaciones enable row level security;
drop policy if exists "cada quien sus calificaciones" on public.ia_calificaciones;
create policy "cada quien sus calificaciones" on public.ia_calificaciones for all
  using (auth.uid() = usuario) with check (auth.uid() = usuario);
revoke all on table public.ia_calificaciones from public, anon, authenticated;
grant select, insert, update, delete on public.ia_calificaciones to authenticated;

-- el resumen para medir (sólo lo lee el administrador)
create or replace function public.ia_calificaciones_resumen() returns table (analisis text, partido text, buenos int, malos int, motivos text)
language sql stable security definer set search_path = public as $resumen$
  select c.analisis, a.partido, count(*) filter (where c.voto = 1)::int, count(*) filter (where c.voto = -1)::int,
         string_agg(c.motivo, ',') filter (where c.motivo is not null)
    from public.ia_calificaciones c left join public.ia_analisis a on a.id = c.analisis
   where exists (select 1 from public.perfiles f where f.id = auth.uid() and f.admin)
   group by c.analisis, a.partido;
$resumen$;
revoke all on function public.ia_calificaciones_resumen() from public, anon;
grant execute on function public.ia_calificaciones_resumen() to authenticated;

-- ---------- 3) la IA con noticias de la web ----------
alter table public.ia_analisis add column if not exists con_noticias boolean;
alter table public.ia_analisis add column if not exists noticias text;

notify pgrst, 'reload schema';
