-- v400 — lo mandado por Telegram con su texto (para avisar si se retira)
alter table public.telegram_enviados add column if not exists texto text;
alter table public.telegram_enviados add column if not exists partido text;
alter table public.telegram_enviados add column if not exists inicio timestamptz;
notify pgrst, 'reload schema';
