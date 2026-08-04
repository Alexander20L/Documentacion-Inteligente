-- Normalize the legacy default from 001 without constraining unknown historical states.
update public.proyectos
set estado_documentacion = 'PENDIENTE'
where lower(estado_documentacion) = 'pendiente';

alter table public.proyectos
  alter column estado_documentacion set default 'PENDIENTE';

create table if not exists public.ejecuciones_c4 (
  id uuid primary key default gen_random_uuid(),
  id_repositorio text not null,
  estado text not null default 'pendiente',
  configuracion jsonb not null default '{}'::jsonb,
  resultado jsonb not null default '{}'::jsonb,
  error_ultimo text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ejecuciones_c4_estado_check
    check (estado in ('pendiente', 'procesando', 'completado', 'fallido', 'cancelado')),
  constraint ejecuciones_c4_fechas_check
    check (finished_at is null or started_at is null or finished_at >= started_at)
);

create table if not exists public.revisiones_c4 (
  id uuid primary key default gen_random_uuid(),
  ejecucion_c4_id uuid not null references public.ejecuciones_c4(id) on delete cascade,
  estado text not null default 'pendiente',
  observaciones text,
  contenido jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint revisiones_c4_estado_check
    check (estado in ('pendiente', 'aprobada', 'rechazada', 'cancelada'))
);

create table if not exists public.artefactos_c4 (
  id uuid primary key default gen_random_uuid(),
  ejecucion_c4_id uuid not null references public.ejecuciones_c4(id) on delete cascade,
  tipo text not null,
  nombre text not null,
  ruta text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint artefactos_c4_tipo_check check (btrim(tipo) <> ''),
  constraint artefactos_c4_nombre_check check (btrim(nombre) <> ''),
  constraint artefactos_c4_ruta_check check (btrim(ruta) <> '')
);

create index if not exists idx_ejecuciones_c4_repositorio_created_at
  on public.ejecuciones_c4(id_repositorio, created_at desc);

create unique index if not exists uq_ejecuciones_c4_activas
  on public.ejecuciones_c4(id_repositorio)
  where estado in ('pendiente', 'procesando');

create index if not exists idx_revisiones_c4_ejecucion
  on public.revisiones_c4(ejecucion_c4_id);

create unique index if not exists uq_revisiones_c4_ejecucion
  on public.revisiones_c4(ejecucion_c4_id);

create index if not exists idx_artefactos_c4_ejecucion
  on public.artefactos_c4(ejecucion_c4_id);

drop index if exists public.uq_artefactos_c4_ejecucion_nombre;
create unique index if not exists uq_artefactos_c4_ejecucion_ruta
  on public.artefactos_c4(ejecucion_c4_id, ruta);

alter table public.tareas_proyecto
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists lease_owner text,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists heartbeat_at timestamptz,
  add column if not exists progreso integer not null default 0,
  add column if not exists fase text,
  add column if not exists intentos integer not null default 0,
  add column if not exists max_intentos integer not null default 3,
  add column if not exists ejecucion_c4_id uuid references public.ejecuciones_c4(id) on delete set null;

update public.tareas_proyecto
set updated_at = coalesce(updated_at, created_at, now()),
    progreso = coalesce(progreso, 0),
    intentos = coalesce(intentos, 0),
    max_intentos = coalesce(max_intentos, 3);

alter table public.tareas_proyecto
  alter column updated_at set default now(),
  alter column updated_at set not null,
  alter column progreso set default 0,
  alter column progreso set not null,
  alter column intentos set default 0,
  alter column intentos set not null,
  alter column max_intentos set default 3,
  alter column max_intentos set not null;

-- Tasks that were already processing under 002 had no lease. Expire a synthetic
-- lease so the atomic claimant can recover them instead of leaving them stuck.
update public.tareas_proyecto
set lease_owner = coalesce(lease_owner, 'legacy-worker'),
    lease_expires_at = coalesce(lease_expires_at, now() - interval '1 second'),
    heartbeat_at = coalesce(heartbeat_at, updated_at, now())
where estado = 'procesando'
  and (lease_owner is null or lease_expires_at is null);

alter table public.tareas_proyecto
  drop constraint if exists tareas_proyecto_tipo_check,
  drop constraint if exists tareas_proyecto_estado_check,
  drop constraint if exists tareas_proyecto_progreso_check,
  drop constraint if exists tareas_proyecto_intentos_check,
  drop constraint if exists tareas_proyecto_max_intentos_check,
  drop constraint if exists tareas_proyecto_lease_check;

alter table public.tareas_proyecto
  add constraint tareas_proyecto_tipo_check
    check (tipo in ('analisis', 'documentacion', 'analisis_c4', 'publicacion_c4')),
  add constraint tareas_proyecto_estado_check
    check (estado in ('pendiente', 'procesando', 'completado', 'fallido', 'cancelado')),
  add constraint tareas_proyecto_progreso_check
    check (progreso between 0 and 100),
  add constraint tareas_proyecto_intentos_check
    check (intentos >= 0),
  add constraint tareas_proyecto_max_intentos_check
    check (max_intentos > 0),
  add constraint tareas_proyecto_lease_check
    check (
      (estado = 'procesando' and lease_owner is not null and lease_expires_at is not null)
      or estado <> 'procesando'
    );

create index if not exists idx_tareas_proyecto_lease
  on public.tareas_proyecto(lease_expires_at)
  where estado = 'procesando';

-- The C4 pipeline replaces the legacy workflow. Preserve historical rows but do
-- not let pending legacy work run against the new immutable repository layout.
update public.tareas_proyecto
set estado = 'cancelado',
    error_ultimo = coalesce(error_ultimo, 'Cancelada al reemplazar el pipeline por C4'),
    finished_at = coalesce(finished_at, now()),
    lease_owner = null,
    lease_expires_at = null,
    heartbeat_at = null
where tipo in ('analisis', 'documentacion')
  and estado in ('pendiente', 'procesando');

-- The old index allowed one active task per repository and type. Preserve all
-- remaining rows, but cancel newer duplicates before repository-wide exclusion.
drop index if exists public.uq_tareas_proyecto_activas;

with activas_duplicadas as (
  select id,
         row_number() over (
           partition by id_repositorio
           order by (estado = 'procesando') desc, created_at, id
         ) as posicion
  from public.tareas_proyecto
  where estado in ('pendiente', 'procesando')
)
update public.tareas_proyecto as tarea
set estado = 'cancelado',
    error_ultimo = coalesce(
      tarea.error_ultimo,
      'Cancelada al aplicar exclusividad de tarea activa por repositorio'
    ),
    finished_at = coalesce(tarea.finished_at, now()),
    lease_owner = null,
    lease_expires_at = null,
    heartbeat_at = null
from activas_duplicadas
where tarea.id = activas_duplicadas.id
  and activas_duplicadas.posicion > 1;

create unique index uq_tareas_proyecto_activas
  on public.tareas_proyecto(id_repositorio)
  where estado in ('pendiente', 'procesando');

drop trigger if exists set_ejecuciones_c4_updated_at on public.ejecuciones_c4;
create trigger set_ejecuciones_c4_updated_at
before update on public.ejecuciones_c4
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_revisiones_c4_updated_at on public.revisiones_c4;
create trigger set_revisiones_c4_updated_at
before update on public.revisiones_c4
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_artefactos_c4_updated_at on public.artefactos_c4;
create trigger set_artefactos_c4_updated_at
before update on public.artefactos_c4
for each row execute function public.set_current_timestamp_updated_at();

alter table public.ejecuciones_c4 enable row level security;
alter table public.revisiones_c4 enable row level security;
alter table public.artefactos_c4 enable row level security;

-- Task ownership follows the repository, not the caller-controlled task usuario_id.
drop policy if exists "tareas_select_own" on public.tareas_proyecto;
create policy "tareas_select_own"
on public.tareas_proyecto
for select
using (
  usuario_id = auth.uid()
  and exists (
    select 1
    from public.proyectos as proyecto
    where proyecto.id_repositorio = tareas_proyecto.id_repositorio
      and proyecto.usuario_id = auth.uid()
  )
);

drop policy if exists "tareas_insert_own" on public.tareas_proyecto;
create policy "tareas_insert_own"
on public.tareas_proyecto
for insert
with check (
  usuario_id = auth.uid()
  and exists (
    select 1
    from public.proyectos as proyecto
    where proyecto.id_repositorio = tareas_proyecto.id_repositorio
      and proyecto.usuario_id = auth.uid()
  )
);

drop policy if exists "tareas_update_own" on public.tareas_proyecto;
create policy "tareas_update_own"
on public.tareas_proyecto
for update
using (
  usuario_id = auth.uid()
  and exists (
    select 1
    from public.proyectos as proyecto
    where proyecto.id_repositorio = tareas_proyecto.id_repositorio
      and proyecto.usuario_id = auth.uid()
  )
)
with check (
  usuario_id = auth.uid()
  and exists (
    select 1
    from public.proyectos as proyecto
    where proyecto.id_repositorio = tareas_proyecto.id_repositorio
      and proyecto.usuario_id = auth.uid()
  )
);

drop policy if exists "tareas_delete_own" on public.tareas_proyecto;
create policy "tareas_delete_own"
on public.tareas_proyecto
for delete
using (
  usuario_id = auth.uid()
  and exists (
    select 1
    from public.proyectos as proyecto
    where proyecto.id_repositorio = tareas_proyecto.id_repositorio
      and proyecto.usuario_id = auth.uid()
  )
);

drop policy if exists "ejecuciones_c4_select_own" on public.ejecuciones_c4;
create policy "ejecuciones_c4_select_own"
on public.ejecuciones_c4 for select
using (exists (
  select 1 from public.proyectos as proyecto
  where proyecto.id_repositorio = ejecuciones_c4.id_repositorio
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "ejecuciones_c4_insert_own" on public.ejecuciones_c4;
create policy "ejecuciones_c4_insert_own"
on public.ejecuciones_c4 for insert
with check (exists (
  select 1 from public.proyectos as proyecto
  where proyecto.id_repositorio = ejecuciones_c4.id_repositorio
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "ejecuciones_c4_update_own" on public.ejecuciones_c4;
create policy "ejecuciones_c4_update_own"
on public.ejecuciones_c4 for update
using (exists (
  select 1 from public.proyectos as proyecto
  where proyecto.id_repositorio = ejecuciones_c4.id_repositorio
    and proyecto.usuario_id = auth.uid()
))
with check (exists (
  select 1 from public.proyectos as proyecto
  where proyecto.id_repositorio = ejecuciones_c4.id_repositorio
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "ejecuciones_c4_delete_own" on public.ejecuciones_c4;
create policy "ejecuciones_c4_delete_own"
on public.ejecuciones_c4 for delete
using (exists (
  select 1 from public.proyectos as proyecto
  where proyecto.id_repositorio = ejecuciones_c4.id_repositorio
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "revisiones_c4_select_own" on public.revisiones_c4;
create policy "revisiones_c4_select_own"
on public.revisiones_c4 for select
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = revisiones_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "revisiones_c4_insert_own" on public.revisiones_c4;
create policy "revisiones_c4_insert_own"
on public.revisiones_c4 for insert
with check (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = revisiones_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "revisiones_c4_update_own" on public.revisiones_c4;
create policy "revisiones_c4_update_own"
on public.revisiones_c4 for update
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = revisiones_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
))
with check (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = revisiones_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "revisiones_c4_delete_own" on public.revisiones_c4;
create policy "revisiones_c4_delete_own"
on public.revisiones_c4 for delete
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = revisiones_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "artefactos_c4_select_own" on public.artefactos_c4;
create policy "artefactos_c4_select_own"
on public.artefactos_c4 for select
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = artefactos_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "artefactos_c4_insert_own" on public.artefactos_c4;
create policy "artefactos_c4_insert_own"
on public.artefactos_c4 for insert
with check (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = artefactos_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "artefactos_c4_update_own" on public.artefactos_c4;
create policy "artefactos_c4_update_own"
on public.artefactos_c4 for update
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = artefactos_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
))
with check (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = artefactos_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "artefactos_c4_delete_own" on public.artefactos_c4;
create policy "artefactos_c4_delete_own"
on public.artefactos_c4 for delete
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = artefactos_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

create or replace function public.reclamar_tarea_proyecto(
  p_lease_owner text,
  p_lease_seconds integer default 300
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  if nullif(btrim(p_lease_owner), '') is null then
    raise exception 'lease owner is required' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds <= 0 then
    raise exception 'lease seconds must be greater than zero' using errcode = '22023';
  end if;

  update public.ejecuciones_c4 as ejecucion
  set estado = 'fallido',
      error_ultimo = 'La tarea agotó sus intentos tras expirar el lease',
      finished_at = clock_timestamp()
  where exists (
    select 1 from public.tareas_proyecto as agotada
    where agotada.ejecucion_c4_id = ejecucion.id
      and agotada.estado = 'procesando'
      and agotada.lease_expires_at < clock_timestamp()
      and agotada.intentos >= agotada.max_intentos
  );

  update public.tareas_proyecto as agotada
  set estado = 'fallido',
      finished_at = clock_timestamp(),
      error_ultimo = coalesce(agotada.error_ultimo, 'La tarea agotó sus intentos tras expirar el lease'),
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where agotada.estado = 'procesando'
    and agotada.lease_expires_at < clock_timestamp()
    and agotada.intentos >= agotada.max_intentos;

  with candidata as (
    select tarea.id
    from public.tareas_proyecto as tarea
    where (
        tarea.estado = 'pendiente'
        or (
          tarea.estado = 'procesando'
          and tarea.lease_expires_at < clock_timestamp()
        )
      )
      and tarea.intentos < tarea.max_intentos
    order by tarea.created_at, tarea.id
    for update skip locked
    limit 1
  )
  update public.tareas_proyecto as tarea
  set estado = 'procesando',
      lease_owner = p_lease_owner,
      lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
      heartbeat_at = clock_timestamp(),
      started_at = coalesce(tarea.started_at, clock_timestamp()),
      finished_at = null,
      error_ultimo = null,
      intentos = tarea.intentos + 1
  from candidata
  where tarea.id = candidata.id
  returning tarea.* into v_tarea;

  return v_tarea;
end;
$$;

drop function if exists public.heartbeat_tarea_proyecto(uuid, text, integer, integer, text);
create or replace function public.heartbeat_tarea_proyecto(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_lease_seconds integer default 300,
  p_progreso integer default null,
  p_fase text default null
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  if p_lease_seconds is null or p_lease_seconds <= 0 then
    raise exception 'lease seconds must be greater than zero' using errcode = '22023';
  end if;
  if p_progreso is not null and (p_progreso < 0 or p_progreso > 100) then
    raise exception 'progress must be between zero and one hundred' using errcode = '22023';
  end if;

  update public.tareas_proyecto as tarea
  set heartbeat_at = clock_timestamp(),
      lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
      progreso = coalesce(p_progreso, tarea.progreso),
      fase = coalesce(p_fase, tarea.fase)
  where tarea.id = p_tarea_id
    and tarea.estado = 'procesando'
    and tarea.lease_owner = p_lease_owner
    and tarea.intentos = p_intento
    and tarea.lease_expires_at >= clock_timestamp()
  returning tarea.* into v_tarea;

  if not found then
    raise exception 'task lease is missing, expired, or owned by another worker'
      using errcode = '55000';
  end if;
  return v_tarea;
end;
$$;

drop function if exists public.completar_tarea_proyecto(uuid, text, uuid);
create or replace function public.completar_tarea_proyecto(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_ejecucion_c4_id uuid default null
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  update public.tareas_proyecto as tarea
  set estado = 'completado',
      progreso = 100,
      finished_at = clock_timestamp(),
      error_ultimo = null,
      ejecucion_c4_id = coalesce(p_ejecucion_c4_id, tarea.ejecucion_c4_id),
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where tarea.id = p_tarea_id
    and tarea.estado = 'procesando'
    and tarea.lease_owner = p_lease_owner
    and tarea.intentos = p_intento
    and tarea.lease_expires_at >= clock_timestamp()
  returning tarea.* into v_tarea;

  if not found then
    raise exception 'task lease is missing, expired, or owned by another worker'
      using errcode = '55000';
  end if;
  return v_tarea;
end;
$$;

drop function if exists public.fallar_tarea_proyecto(uuid, text, text, boolean);
create or replace function public.fallar_tarea_proyecto(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_error text,
  p_reintentable boolean default true
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  update public.tareas_proyecto as tarea
  set estado = case
        when p_reintentable and tarea.intentos < tarea.max_intentos then 'pendiente'
        else 'fallido'
      end,
      finished_at = case
        when p_reintentable and tarea.intentos < tarea.max_intentos then null
        else clock_timestamp()
      end,
      error_ultimo = p_error,
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where tarea.id = p_tarea_id
    and tarea.estado = 'procesando'
    and tarea.lease_owner = p_lease_owner
    and tarea.intentos = p_intento
    and tarea.lease_expires_at >= clock_timestamp()
  returning tarea.* into v_tarea;

  if not found then
    raise exception 'task lease is missing, expired, or owned by another worker'
      using errcode = '55000';
  end if;
  return v_tarea;
end;
$$;

drop function if exists public.completar_analisis_c4(uuid, text, uuid, jsonb);
create or replace function public.completar_analisis_c4(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_ejecucion_c4_id uuid,
  p_resultado jsonb
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  update public.ejecuciones_c4
  set estado = 'procesando',
      resultado = p_resultado,
      error_ultimo = null,
      finished_at = null
  where id = p_ejecucion_c4_id
    and exists (
      select 1 from public.tareas_proyecto as tarea
      where tarea.id = p_tarea_id
        and tarea.ejecucion_c4_id = p_ejecucion_c4_id
        and tarea.tipo = 'analisis_c4'
        and tarea.estado = 'procesando'
        and tarea.lease_owner = p_lease_owner
        and tarea.intentos = p_intento
        and tarea.lease_expires_at >= clock_timestamp()
    );

  if not found then
    raise exception 'analysis lease or execution is invalid' using errcode = '55000';
  end if;

  update public.tareas_proyecto as tarea
  set estado = 'completado',
      progreso = 100,
      fase = 'revision',
      finished_at = clock_timestamp(),
      error_ultimo = null,
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where tarea.id = p_tarea_id
    and tarea.estado = 'procesando'
    and tarea.lease_owner = p_lease_owner
    and tarea.intentos = p_intento
    and tarea.lease_expires_at >= clock_timestamp()
  returning tarea.* into v_tarea;

  if not found then
    raise exception 'analysis lease is missing or expired' using errcode = '55000';
  end if;
  return v_tarea;
end;
$$;

drop function if exists public.completar_publicacion_c4(uuid, text, uuid, jsonb);
create or replace function public.completar_publicacion_c4(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_ejecucion_c4_id uuid,
  p_resultado jsonb
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  update public.ejecuciones_c4
  set estado = 'completado',
      resultado = p_resultado,
      error_ultimo = null,
      finished_at = clock_timestamp()
  where id = p_ejecucion_c4_id
    and exists (
      select 1 from public.tareas_proyecto as tarea
      where tarea.id = p_tarea_id
        and tarea.ejecucion_c4_id = p_ejecucion_c4_id
        and tarea.tipo = 'publicacion_c4'
        and tarea.estado = 'procesando'
        and tarea.lease_owner = p_lease_owner
        and tarea.intentos = p_intento
        and tarea.lease_expires_at >= clock_timestamp()
    );

  if not found then
    raise exception 'publication lease or execution is invalid' using errcode = '55000';
  end if;

  update public.tareas_proyecto as tarea
  set estado = 'completado',
      progreso = 100,
      fase = 'completado',
      finished_at = clock_timestamp(),
      error_ultimo = null,
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where tarea.id = p_tarea_id
    and tarea.estado = 'procesando'
    and tarea.lease_owner = p_lease_owner
    and tarea.intentos = p_intento
    and tarea.lease_expires_at >= clock_timestamp()
  returning tarea.* into v_tarea;

  if not found then
    raise exception 'publication lease is missing or expired' using errcode = '55000';
  end if;
  return v_tarea;
end;
$$;

create or replace function public.encolar_publicacion_c4(
  p_revision_id uuid,
  p_ejecucion_c4_id uuid,
  p_usuario_id uuid,
  p_id_repositorio text,
  p_contenido jsonb,
  p_resultado jsonb
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  if not exists (
    select 1 from public.proyectos
    where id_repositorio = p_id_repositorio
      and usuario_id = p_usuario_id
  ) then
    raise exception 'project ownership does not match publication request' using errcode = '42501';
  end if;

  update public.revisiones_c4
  set estado = 'aprobada',
      contenido = p_contenido
  where id = p_revision_id
    and ejecucion_c4_id = p_ejecucion_c4_id
    and estado = 'pendiente'
    and contenido #>> '{revision,hash}' = p_contenido #>> '{revision,hash}'
    and contenido #>> '{revision,version}' = p_contenido #>> '{revision,version}';
  if not found then
    raise exception 'review is not pending or does not belong to execution' using errcode = '55000';
  end if;

  update public.ejecuciones_c4
  set estado = 'pendiente',
      resultado = p_resultado,
      error_ultimo = null,
      finished_at = null
  where id = p_ejecucion_c4_id
    and id_repositorio = p_id_repositorio
    and estado = 'procesando';
  if not found then
    raise exception 'execution is not awaiting review' using errcode = '55000';
  end if;

  insert into public.tareas_proyecto (
    usuario_id, id_repositorio, tipo, estado, payload,
    ejecucion_c4_id, fase
  ) values (
    p_usuario_id, p_id_repositorio, 'publicacion_c4', 'pendiente',
    jsonb_build_object('id_ejecucion', p_ejecucion_c4_id),
    p_ejecucion_c4_id, 'generacion'
  ) returning * into v_tarea;

  return v_tarea;
end;
$$;

create or replace function public.reemplazar_artefactos_c4(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_ejecucion_c4_id uuid,
  p_artefactos jsonb
)
returns setof public.artefactos_c4
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if jsonb_typeof(p_artefactos) <> 'array' then
    raise exception 'artifacts must be a JSON array' using errcode = '22023';
  end if;
  if not exists (
    select 1 from public.tareas_proyecto as tarea
    where tarea.id = p_tarea_id
      and tarea.ejecucion_c4_id = p_ejecucion_c4_id
      and tarea.tipo = 'publicacion_c4'
      and tarea.estado = 'procesando'
      and tarea.lease_owner = p_lease_owner
      and tarea.intentos = p_intento
      and tarea.lease_expires_at >= clock_timestamp()
  ) then
    raise exception 'publication lease or execution is invalid' using errcode = '55000';
  end if;

  delete from public.artefactos_c4
  where ejecucion_c4_id = p_ejecucion_c4_id;

  return query
  insert into public.artefactos_c4 (ejecucion_c4_id, tipo, nombre, ruta, metadata)
  select
    p_ejecucion_c4_id,
    elemento->>'tipo',
    elemento->>'nombre',
    elemento->>'ruta',
    coalesce(elemento->'metadata', '{}'::jsonb)
  from jsonb_array_elements(p_artefactos) as elemento
  returning *;
end;
$$;

drop function if exists public.fallar_tarea_c4(uuid, text, text);
create or replace function public.fallar_tarea_c4(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_error text
)
returns public.tareas_proyecto
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_tarea public.tareas_proyecto;
begin
  update public.ejecuciones_c4 as ejecucion
  set estado = 'fallido',
      error_ultimo = left(p_error, 2000),
      finished_at = clock_timestamp()
  where ejecucion.id = (
    select tarea.ejecucion_c4_id
    from public.tareas_proyecto as tarea
    where tarea.id = p_tarea_id
      and tarea.tipo in ('analisis_c4', 'publicacion_c4')
      and tarea.estado = 'procesando'
      and tarea.lease_owner = p_lease_owner
      and tarea.intentos = p_intento
      and tarea.lease_expires_at >= clock_timestamp()
  );
  if not found then
    raise exception 'C4 task lease is missing, expired, or owned by another worker'
      using errcode = '55000';
  end if;

  update public.tareas_proyecto as tarea
  set estado = 'fallido',
      finished_at = clock_timestamp(),
      error_ultimo = left(p_error, 2000),
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where tarea.id = p_tarea_id
    and tarea.estado = 'procesando'
    and tarea.lease_owner = p_lease_owner
    and tarea.intentos = p_intento
    and tarea.lease_expires_at >= clock_timestamp()
  returning tarea.* into v_tarea;
  if not found then
    raise exception 'C4 task lease is missing or expired' using errcode = '55000';
  end if;
  return v_tarea;
end;
$$;

revoke all on function public.reclamar_tarea_proyecto(text, integer)
  from public, anon, authenticated;
revoke all on function public.heartbeat_tarea_proyecto(uuid, text, integer, integer, integer, text)
  from public, anon, authenticated;
revoke all on function public.completar_tarea_proyecto(uuid, text, integer, uuid)
  from public, anon, authenticated;
revoke all on function public.fallar_tarea_proyecto(uuid, text, integer, text, boolean)
  from public, anon, authenticated;
revoke all on function public.completar_analisis_c4(uuid, text, integer, uuid, jsonb)
  from public, anon, authenticated;
revoke all on function public.completar_publicacion_c4(uuid, text, integer, uuid, jsonb)
  from public, anon, authenticated;
revoke all on function public.encolar_publicacion_c4(uuid, uuid, uuid, text, jsonb, jsonb)
  from public, anon, authenticated;
revoke all on function public.reemplazar_artefactos_c4(uuid, text, integer, uuid, jsonb)
  from public, anon, authenticated;
revoke all on function public.fallar_tarea_c4(uuid, text, integer, text)
  from public, anon, authenticated;

grant execute on function public.reclamar_tarea_proyecto(text, integer) to service_role;
grant execute on function public.heartbeat_tarea_proyecto(uuid, text, integer, integer, integer, text) to service_role;
grant execute on function public.completar_tarea_proyecto(uuid, text, integer, uuid) to service_role;
grant execute on function public.fallar_tarea_proyecto(uuid, text, integer, text, boolean) to service_role;
grant execute on function public.completar_analisis_c4(uuid, text, integer, uuid, jsonb) to service_role;
grant execute on function public.completar_publicacion_c4(uuid, text, integer, uuid, jsonb) to service_role;
grant execute on function public.encolar_publicacion_c4(uuid, uuid, uuid, text, jsonb, jsonb) to service_role;
grant execute on function public.reemplazar_artefactos_c4(uuid, text, integer, uuid, jsonb) to service_role;
grant execute on function public.fallar_tarea_c4(uuid, text, integer, text) to service_role;

-- Browser clients only read pipeline state. All mutations are performed by the
-- authenticated API after ownership validation, using the service-role client.
drop policy if exists "tareas_insert_own" on public.tareas_proyecto;
drop policy if exists "tareas_update_own" on public.tareas_proyecto;
drop policy if exists "tareas_delete_own" on public.tareas_proyecto;
drop policy if exists "ejecuciones_c4_insert_own" on public.ejecuciones_c4;
drop policy if exists "ejecuciones_c4_update_own" on public.ejecuciones_c4;
drop policy if exists "ejecuciones_c4_delete_own" on public.ejecuciones_c4;
drop policy if exists "revisiones_c4_insert_own" on public.revisiones_c4;
drop policy if exists "revisiones_c4_update_own" on public.revisiones_c4;
drop policy if exists "revisiones_c4_delete_own" on public.revisiones_c4;
drop policy if exists "artefactos_c4_insert_own" on public.artefactos_c4;
drop policy if exists "artefactos_c4_update_own" on public.artefactos_c4;
drop policy if exists "artefactos_c4_delete_own" on public.artefactos_c4;
