-- v395 — Stripe además de Mercado Pago, renovación automática opcional,
-- cancelar cuando quiera, y aviso 7 días antes de cada renovación.

-- ¿se volverá a cobrar? (false: pago único, o cancelada al final del periodo)
alter table public.suscripciones add column if not exists renueva boolean not null default true;
-- la fecha de cobro de la que YA se avisó (para avisar una sola vez por renovación)
alter table public.suscripciones add column if not exists avisado_para timestamptz;

-- VIP de un solo pago: suma el periodo a lo que ya tenga (sólo el servidor)
create or replace function public.sumar_vip(p_usuario uuid, p_meses integer) returns void
language sql security definer set search_path = public as $$
  update public.perfiles
     set plan = 'pro',
         plan_hasta = greatest(coalesce(plan_hasta, now()), now()) + make_interval(months => greatest(p_meses, 1))
   where id = p_usuario;
$$;
revoke all on function public.sumar_vip(uuid, integer) from public, anon, authenticated;
grant execute on function public.sumar_vip(uuid, integer) to service_role;

notify pgrst, 'reload schema';
