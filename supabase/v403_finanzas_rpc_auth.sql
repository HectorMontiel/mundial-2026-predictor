-- v403 — Privacidad de la API de resumen financiero.
-- La versión anterior aceptaba cualquier p_user_id en SECURITY DEFINER y
-- tenía EXECUTE concedido a PUBLIC/anon. Se restringe a la identidad autenticada
-- propietaria; service_role conserva el acceso de backend intencional.
-- No modifica ni borra transacciones.

create or replace function public.monthly_category_summary(
  p_user_id uuid,
  p_year integer,
  p_month integer
)
returns table(categoria text, total numeric, count bigint)
language sql
security definer
set search_path = finanzas
as $function$
  select categoria::text, sum(monto) as total, count(*) as count
    from finanzas.transacciones
   where user_id = p_user_id
     and p_user_id is not null
     and (
       auth.uid() = p_user_id
       or auth.role() = 'service_role'
     )
     and p_year between 2000 and 2200
     and p_month between 1 and 12
     and extract(year from fecha) = p_year
     and extract(month from fecha) = p_month
   group by categoria
   order by total desc;
$function$;

revoke all on function public.monthly_category_summary(uuid, integer, integer)
  from public, anon, authenticated, service_role;
grant execute on function public.monthly_category_summary(uuid, integer, integer)
  to authenticated, service_role;
