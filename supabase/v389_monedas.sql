-- v386-v389 — corrido en Supabase (SQL Editor) el 17-oct-2026.
-- Errores de cuota como picks, historial con los 💰 aparte, la IA medida,
-- fin del «gratis con cuenta», precio por cuota, paquetes y compras.
alter table public.picks add column if not exists tipo text default 'pick';
alter table public.picks add column if not exists casa text;
alter table public.picks add column if not exists ventaja numeric(6,3);
alter table public.picks add column if not exists gratis boolean default false;
alter table public.picks add column if not exists ctx jsonb;
-- (ver el historial, ia_analisis/ia_aciertos, precios_cuota, paquetes, compras y
--  acreditar_compra en el historial de la sesión v386-v389; resumen:)
--   historial: verdes/rojas sin 💰 + verdes_error/rojas_error
--   ia_analisis: lo que la IA predice; ia_aciertos: sus ✅/❌ contra el favorito
--   ajustes: premium_con_cuenta = 0; precio_diamante 10, platino 5, error 10
--   precios_cuota: 1,00-1,30 → 5 · 1,30-1,60 → 8 · 1,60-2,00 → 12 · 2,00-3,00 → 18 · 3,00+ → 25
--   paquetes: prueba 50/$29 · popular 100/$49 · pro 220/$99 · mega 500/$199
--   acreditar_compra(id, usuario, paquete, precio): una vez por pago (sólo service_role)
--   picks_premium: se abre al TERMINAR el partido (verde/roja/nula), no al empezar
--   perfiles: el usuario sólo puede cambiar nombre, usuario y deportes (sin insert)

-- SHP-019 — DDL que faltaba en el repositorio para instalaciones nuevas.
-- Esta parte hace reproducibles los objetos que la aplicación ya usa en producción.
-- Es idempotente; no elimina ni reemplaza datos existentes.

-- Historial de análisis de IA. Las columnas añadidas en v394/v396/v399 siguen
-- en sus migraciones correspondientes, para que el orden de instalación quede claro.
create table if not exists public.ia_analisis (
  id text primary key,
  fecha date,
  inicio timestamptz,
  deporte text,
  liga text,
  partido text not null,
  analisis text,
  pred_resultado text check (pred_resultado in ('local', 'empate', 'visita')),
  p_local numeric,
  p_empate numeric,
  p_visita numeric,
  pred_goles text check (pred_goles in ('mas', 'menos')),
  confianza integer,
  pick_ia text,
  coincide boolean,
  p_mercado_local numeric,
  p_mercado_empate numeric,
  p_mercado_visita numeric,
  modelo text,
  creado timestamptz default now(),
  marcador text,
  ok_resultado boolean,
  ok_goles boolean,
  ok_mercado boolean,
  evaluado timestamptz,
  veredictos jsonb,
  clave_liga text,
  marcador_ia text,
  goles_esperados numeric,
  btts text,
  corners_esperados numeric,
  linea_corners numeric,
  pred_corners text,
  tarjetas_esperadas numeric,
  linea_tarjetas numeric,
  pred_tarjetas text,
  ok_marcador boolean,
  ok_btts boolean,
  ok_corners boolean,
  ok_tarjetas boolean,
  corners_real integer,
  tarjetas_real integer
);
alter table public.ia_analisis enable row level security;
drop policy if exists "la IA a quien le toca" on public.ia_analisis;
create policy "la IA a quien le toca" on public.ia_analisis for select using (
  public.es_pro()
  or evaluado is not null
  or (
    auth.uid() is not null
    and exists (
      select 1 from public.ajustes a
      where a.clave = 'premium_con_cuenta' and a.valor = '1'
    )
  )
);
grant select on public.ia_analisis to anon, authenticated;
grant all on public.ia_analisis to service_role;

-- Catálogo público de monedas. Los valores existentes se conservan.
create table if not exists public.paquetes (
  id text primary key,
  nombre text not null,
  monedas integer not null check (monedas > 0),
  precio numeric(8,2) not null check (precio >= 0),
  orden integer not null
);
alter table public.paquetes enable row level security;
drop policy if exists "todos leen paquetes" on public.paquetes;
create policy "todos leen paquetes" on public.paquetes for select using (true);
revoke insert, update, delete on public.paquetes from public, anon, authenticated;
grant select on public.paquetes to anon, authenticated;
grant all on public.paquetes to service_role;

insert into public.paquetes (id, nombre, monedas, precio, orden) values
  ('prueba', 'Prueba', 50, 29, 1),
  ('popular', 'Popular', 100, 49, 2),
  ('pro', 'Pro', 220, 99, 3),
  ('mega', 'Mega', 500, 199, 4)
on conflict (id) do nothing;

-- Registro de pagos de paquetes. El navegador sólo puede leer sus compras;
-- las escrituras se realizan desde el backend con service_role.
create table if not exists public.compras (
  id text primary key,
  usuario uuid not null references auth.users(id) on delete cascade,
  paquete text not null,
  monedas integer not null check (monedas > 0),
  precio numeric(8,2) not null check (precio >= 0),
  estado text not null,
  creado timestamptz default now()
);
alter table public.compras enable row level security;
drop policy if exists "cada quien sus compras" on public.compras;
create policy "cada quien sus compras" on public.compras
  for select to authenticated using (auth.uid() = usuario);
revoke all on public.compras from public, anon, authenticated;
grant select on public.compras to authenticated;
grant all on public.compras to service_role;

-- Acreditación idempotente: el INSERT con ON CONFLICT serializa webhooks
-- concurrentes con el mismo id de pago y sólo una llamada puede abonar monedas.
create or replace function public.acreditar_compra(
  p_id text,
  p_usuario uuid,
  p_paquete text,
  p_precio numeric
) returns text
language plpgsql security definer set search_path = public as $acreditar_compra$
declare
  k public.paquetes;
  v_insertado text;
begin
  if p_id is null or btrim(p_id) = '' or p_usuario is null
     or p_paquete is null or p_precio is null or p_precio < 0 then
    return 'parámetros inválidos';
  end if;

  select * into k from public.paquetes where id = p_paquete;
  if not found then return 'paquete no existe'; end if;
  if p_precio + 0.01 < k.precio then return 'monto distinto'; end if;

  insert into public.compras (id, usuario, paquete, monedas, precio, estado)
  values (p_id, p_usuario, p_paquete, k.monedas, p_precio, 'approved')
  on conflict (id) do nothing
  returning id into v_insertado;

  if v_insertado is null then return 'ya'; end if;

  update public.perfiles set monedas = monedas + k.monedas where id = p_usuario;
  if not found then
    raise exception 'No existe el perfil al que corresponde la compra';
  end if;

  insert into public.movimientos (usuario, cantidad, motivo)
  values (p_usuario, k.monedas, 'compra ' || k.nombre);

  return 'ok';
end;
$acreditar_compra$;
revoke all on function public.acreditar_compra(text, uuid, text, numeric)
  from public, anon, authenticated;
grant execute on function public.acreditar_compra(text, uuid, text, numeric)
  to service_role;
