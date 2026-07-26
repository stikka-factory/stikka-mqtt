-- Stikka-NG Supabase schema.
--
-- Replaces three things that used to live as retained MQTT topics
-- (see git history of frontend/src/mqtt-client.ts):
--   - /_stikka/fonts/  -> fonts table + `fonts` Storage bucket
--   - /_stikka/stats/  -> print_stats table + record_print() RPC
--   - printer discovery (in-memory + localStorage, from /+/status/#) -> printers table
--
-- Run this once in the Supabase SQL editor for a new project. Safe to
-- re-run (uses IF NOT EXISTS / CREATE OR REPLACE throughout).
--
-- Trust model matches the rest of the app: none of this is password-gated
-- (see CLAUDE.md "Config management" -- fonts/stats were never gated
-- either), so RLS policies below intentionally allow the anon role to
-- read/write. The anon key is not a secret -- it ends up in the publicly
-- served config.json same as mqtt.password already does.

-- ── Print statistics ─────────────────────────────────────────────────────
-- Single row (id = 1). record_print() increments atomically, so concurrent
-- prints from different browsers can no longer race and undercount the way
-- the old client-side read-modify-publish-retained approach could.

create table if not exists print_stats (
  id                       int primary key default 1,
  printed_total            int not null default 0,
  printed_cats             int not null default 0,
  printed_dogs             int not null default 0,
  printed_dinos            int not null default 0,
  printed_uploaded_images  int not null default 0,
  printed_webcam_images    int not null default 0,
  printed_without_image    int not null default 0,
  updated_at               timestamptz not null default now(),
  constraint print_stats_singleton check (id = 1)
);

insert into print_stats (id) values (1) on conflict (id) do nothing;

alter table print_stats enable row level security;

drop policy if exists "print_stats select anon" on print_stats;
create policy "print_stats select anon" on print_stats for select using (true);

-- No insert/update/delete policy for anon on the table itself -- all writes
-- go through record_print() below, which runs as the (elevated) function
-- owner so a stray direct UPDATE from the client can't corrupt the row.

create or replace function record_print(kind text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update print_stats set
    printed_total           = printed_total + 1,
    printed_cats            = printed_cats + (case when kind = 'cat' then 1 else 0 end),
    printed_dogs            = printed_dogs + (case when kind = 'dog' then 1 else 0 end),
    printed_dinos           = printed_dinos + (case when kind = 'dino' then 1 else 0 end),
    printed_uploaded_images = printed_uploaded_images + (case when kind = 'upload' then 1 else 0 end),
    printed_webcam_images   = printed_webcam_images + (case when kind = 'webcam' then 1 else 0 end),
    printed_without_image   = printed_without_image + (case when kind = 'none' then 1 else 0 end),
    updated_at              = now()
  where id = 1;
end;
$$;

grant execute on function record_print(text) to anon;

alter publication supabase_realtime add table print_stats;

-- ── Fonts ────────────────────────────────────────────────────────────────
-- font_url points at a public object in the `fonts` Storage bucket, not an
-- embedded base64 blob -- the old retained-topic approach republished every
-- uploaded font's full base64 data on every single upload.

create table if not exists fonts (
  name         text primary key,
  font_url     text not null,
  uploaded_at  timestamptz not null default now()
);

alter table fonts enable row level security;

drop policy if exists "fonts select anon" on fonts;
create policy "fonts select anon" on fonts for select using (true);

drop policy if exists "fonts upsert anon" on fonts;
create policy "fonts upsert anon" on fonts for insert with check (true);

drop policy if exists "fonts update anon" on fonts;
create policy "fonts update anon" on fonts for update using (true) with check (true);

alter publication supabase_realtime add table fonts;

-- Run once via the dashboard (Storage -> New bucket) or here if the
-- storage schema is reachable from the SQL editor on your project:
insert into storage.buckets (id, name, public)
values ('fonts', 'fonts', true)
on conflict (id) do nothing;

drop policy if exists "fonts bucket read anon" on storage.objects;
create policy "fonts bucket read anon" on storage.objects for select
  using (bucket_id = 'fonts');

drop policy if exists "fonts bucket write anon" on storage.objects;
create policy "fonts bucket write anon" on storage.objects for insert
  with check (bucket_id = 'fonts');

drop policy if exists "fonts bucket update anon" on storage.objects;
create policy "fonts bucket update anon" on storage.objects for update
  using (bucket_id = 'fonts') with check (bucket_id = 'fonts');

-- ── Discovered printer nodes ─────────────────────────────────────────────
-- Upserted by whichever browser happens to be connected to the MQTT broker
-- and receives a full status snapshot from an ESP32 bridge (see
-- upsertSupabasePrinter() in frontend/src/supabase-client.ts). last_seen is
-- a real server-side wall-clock column, so "forget a node that's been dead
-- for N minutes" is a plain `last_seen > now() - interval` filter shared by
-- every browser -- no per-browser timer that a page reload used to reset.

create table if not exists printers (
  name                       text primary key,
  type                       text not null default 'zpl',
  dpi                        int not null default 203,
  serial                     text not null default '',
  label_width                int not null default 80,
  label_length               int not null default 80,
  label_is_round             boolean not null default false,
  label_vertical_offset      int not null default 0,
  label_cut                  boolean not null default false,
  zpl_compression_supported  boolean not null default false,
  online                     boolean not null default true,
  busy                       boolean not null default false,
  last_error                 text,
  last_seen                  timestamptz not null default now()
);

alter table printers enable row level security;

drop policy if exists "printers select anon" on printers;
create policy "printers select anon" on printers for select using (true);

drop policy if exists "printers upsert anon" on printers;
create policy "printers upsert anon" on printers for insert with check (true);

drop policy if exists "printers update anon" on printers;
create policy "printers update anon" on printers for update using (true) with check (true);

alter publication supabase_realtime add table printers;
