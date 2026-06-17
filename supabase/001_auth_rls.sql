create extension if not exists pgcrypto;

create or replace function public.set_current_timestamp_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.perfiles (
  id uuid primary key references auth.users(id) on delete cascade,
  nombre text,
  correo text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.proyectos
  add column if not exists usuario_id uuid references auth.users(id) on delete cascade,
  add column if not exists estado_documentacion text not null default 'pendiente',
  add column if not exists ruta_artifacts text,
  add column if not exists error_ultimo text,
  add column if not exists updated_at timestamptz not null default now();

create table if not exists public.tareas_proyecto (
  id uuid primary key default gen_random_uuid(),
  usuario_id uuid not null references auth.users(id) on delete cascade,
  id_repositorio text not null,
  tipo text not null check (tipo in ('analisis', 'documentacion')),
  estado text not null default 'pendiente' check (estado in ('pendiente', 'procesando', 'completado', 'fallido')),
  error_ultimo text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.perfiles (id, nombre, correo)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'nombre', new.raw_user_meta_data ->> 'full_name'),
    new.email
  )
  on conflict (id) do update
  set nombre = excluded.nombre,
      correo = excluded.correo,
      updated_at = now();

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

drop trigger if exists set_perfiles_updated_at on public.perfiles;
create trigger set_perfiles_updated_at
before update on public.perfiles
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_proyectos_updated_at on public.proyectos;
create trigger set_proyectos_updated_at
before update on public.proyectos
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_tareas_proyecto_updated_at on public.tareas_proyecto;
create trigger set_tareas_proyecto_updated_at
before update on public.tareas_proyecto
for each row execute function public.set_current_timestamp_updated_at();

alter table public.perfiles enable row level security;
alter table public.proyectos enable row level security;
alter table public.tareas_proyecto enable row level security;

drop policy if exists "perfiles_select_own" on public.perfiles;
create policy "perfiles_select_own"
on public.perfiles
for select
using (auth.uid() = id);

drop policy if exists "perfiles_insert_own" on public.perfiles;
create policy "perfiles_insert_own"
on public.perfiles
for insert
with check (auth.uid() = id);

drop policy if exists "perfiles_update_own" on public.perfiles;
create policy "perfiles_update_own"
on public.perfiles
for update
using (auth.uid() = id)
with check (auth.uid() = id);

drop policy if exists "proyectos_select_own" on public.proyectos;
create policy "proyectos_select_own"
on public.proyectos
for select
using (auth.uid() = usuario_id);

drop policy if exists "proyectos_insert_own" on public.proyectos;
create policy "proyectos_insert_own"
on public.proyectos
for insert
with check (auth.uid() = usuario_id);

drop policy if exists "proyectos_update_own" on public.proyectos;
create policy "proyectos_update_own"
on public.proyectos
for update
using (auth.uid() = usuario_id)
with check (auth.uid() = usuario_id);

drop policy if exists "proyectos_delete_own" on public.proyectos;
create policy "proyectos_delete_own"
on public.proyectos
for delete
using (auth.uid() = usuario_id);

drop policy if exists "tareas_select_own" on public.tareas_proyecto;
create policy "tareas_select_own"
on public.tareas_proyecto
for select
using (auth.uid() = usuario_id);

drop policy if exists "tareas_insert_own" on public.tareas_proyecto;
create policy "tareas_insert_own"
on public.tareas_proyecto
for insert
with check (auth.uid() = usuario_id);

drop policy if exists "tareas_update_own" on public.tareas_proyecto;
create policy "tareas_update_own"
on public.tareas_proyecto
for update
using (auth.uid() = usuario_id)
with check (auth.uid() = usuario_id);
