// v383 — EL AVISO DE MERCADO PAGO (webhook). Mercado Pago llama aquí cuando
// una suscripción cambia o se cobra un mes. No se confía en lo que llega:
// con el id se le PREGUNTA a Mercado Pago (con nuestro token) cómo está, y con
// eso se activa o se deja vencer el VIP. Autorizada → plan «pro» hasta el
// próximo cobro + 3 días de gracia; cancelada o en pausa → vence sola.
import { createClient } from 'npm:@supabase/supabase-js@2.45.4';

const ok = () => new Response('ok', { status: 200 });

Deno.serve(async (req) => {
  try {
    const MP = Deno.env.get('MP_ACCESS_TOKEN');
    if (!MP) return ok();
    const url = new URL(req.url);
    const body = await req.json().catch(() => ({} as Record<string, any>));
    const tipo = String(body.type || body.topic || url.searchParams.get('type') || url.searchParams.get('topic') || '');
    const id = String(body?.data?.id || url.searchParams.get('data.id') || url.searchParams.get('id') || '');
    if (!id) return ok();
    const mp = async (ruta: string) => {
      const r = await fetch('https://api.mercadopago.com' + ruta, { headers: { Authorization: 'Bearer ' + MP } });
      return r.ok ? await r.json() : null;
    };
    let pre: string | null = null;
    if (tipo.includes('authorized_payment')) pre = (await mp('/authorized_payments/' + id))?.preapproval_id ?? null;
    else if (tipo.includes('preapproval')) pre = id;
    if (!pre) return ok();
    const s = await mp('/preapproval/' + pre);
    if (!s || !s.external_reference) return ok();
    const admin = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
    const meses = Number(s.auto_recurring?.frequency ?? 1);
    await admin.from('suscripciones').upsert({
      id: s.id, usuario: s.external_reference, tipo: meses >= 6 ? 'semestral' : 'mensual',
      precio: Number(s.auto_recurring?.transaction_amount ?? 0), fundador: String(s.reason || '').includes('fundador'),
      estado: s.status, proximo_cobro: s.next_payment_date ?? null, actualizado: new Date().toISOString() });
    if (s.status === 'authorized') {
      const base = s.next_payment_date ? new Date(s.next_payment_date) : new Date(Date.now() + meses * 31 * 864e5);
      const hasta = new Date(base.getTime() + 3 * 864e5);
      const { data: p } = await admin.from('perfiles').select('plan_hasta').eq('id', s.external_reference).maybeSingle();
      const actual = p?.plan_hasta ? new Date(p.plan_hasta) : null;
      await admin.from('perfiles').update({ plan: 'pro', plan_hasta: (actual && actual > hasta ? actual : hasta).toISOString() })
        .eq('id', s.external_reference);
    }
    return ok();
  } catch (_e) {
    return ok();     // a Mercado Pago siempre se le contesta 200 (si no, reintenta sin fin)
  }
});
