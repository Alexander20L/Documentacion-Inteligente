-- Detailed task progress and ownership-safe C4 controls.
alter table public.tareas_proyecto
  add column if not exists paso text,
  add column if not exists mensaje text,
  add column if not exists unidades_completadas integer,
  add column if not exists unidades_totales integer;

alter table public.tareas_proyecto
  drop constraint if exists tareas_proyecto_unidades_check;

alter table public.tareas_proyecto
  add constraint tareas_proyecto_unidades_check check (
    (unidades_completadas is null or unidades_completadas >= 0)
    and (unidades_totales is null or unidades_totales >= 0)
    and (
      unidades_completadas is null
      or unidades_totales is null
      or unidades_completadas <= unidades_totales
    )
  );

-- Keep the original named arguments valid while extending heartbeat details.
drop function if exists public.heartbeat_tarea_proyecto(uuid, text, integer, integer, integer, text);
create or replace function public.heartbeat_tarea_proyecto(
  p_tarea_id uuid,
  p_lease_owner text,
  p_intento integer,
  p_lease_seconds integer default 300,
  p_progreso integer default null,
  p_fase text default null,
  p_paso text default null,
  p_mensaje text default null,
  p_unidades_completadas integer default null,
  p_unidades_totales integer default null
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
  if p_unidades_completadas is not null and p_unidades_completadas < 0 then
    raise exception 'completed units must not be negative' using errcode = '22023';
  end if;
  if p_unidades_totales is not null and p_unidades_totales < 0 then
    raise exception 'total units must not be negative' using errcode = '22023';
  end if;
  if p_unidades_completadas is not null
     and p_unidades_totales is not null
     and p_unidades_completadas > p_unidades_totales then
    raise exception 'completed units must not exceed total units' using errcode = '22023';
  end if;

  update public.tareas_proyecto as tarea
  set heartbeat_at = clock_timestamp(),
      lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
      progreso = coalesce(p_progreso, tarea.progreso),
      fase = coalesce(p_fase, tarea.fase),
      paso = coalesce(p_paso, tarea.paso),
      mensaje = case
        when p_paso is not null or p_mensaje is not null
          or p_unidades_completadas is not null or p_unidades_totales is not null
        then p_mensaje else tarea.mensaje
      end,
      unidades_completadas = case
        when p_paso is not null or p_mensaje is not null
          or p_unidades_completadas is not null or p_unidades_totales is not null
        then p_unidades_completadas else tarea.unidades_completadas
      end,
      unidades_totales = case
        when p_paso is not null or p_mensaje is not null
          or p_unidades_completadas is not null or p_unidades_totales is not null
        then p_unidades_totales else tarea.unidades_totales
      end
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

create or replace function public.cancelar_ejecucion_c4(
  p_ejecucion_c4_id uuid,
  p_id_repositorio text,
  p_usuario_id uuid
)
returns public.ejecuciones_c4
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_ejecucion public.ejecuciones_c4;
begin
  select ejecucion.* into v_ejecucion
  from public.ejecuciones_c4 as ejecucion
  where ejecucion.id = p_ejecucion_c4_id
    and ejecucion.id_repositorio = p_id_repositorio
    and exists (
      select 1 from public.proyectos as proyecto
      where proyecto.id_repositorio = ejecucion.id_repositorio
        and proyecto.usuario_id = p_usuario_id
    )
  for update;

  if not found then
    raise exception 'execution does not exist or is not owned by user' using errcode = '42501';
  end if;
  if v_ejecucion.estado not in ('pendiente', 'procesando') then
    raise exception 'only an active execution can be canceled' using errcode = '55000';
  end if;

  update public.tareas_proyecto
  set estado = 'cancelado',
      paso = 'cancelado',
      mensaje = 'Ejecución cancelada por el usuario',
      error_ultimo = null,
      finished_at = clock_timestamp(),
      lease_owner = null,
      lease_expires_at = null,
      heartbeat_at = clock_timestamp()
  where ejecucion_c4_id = p_ejecucion_c4_id
    and estado in ('pendiente', 'procesando');

  update public.revisiones_c4
  set estado = 'cancelada'
  where ejecucion_c4_id = p_ejecucion_c4_id
    and estado = 'pendiente';

  update public.ejecuciones_c4
  set estado = 'cancelado',
      error_ultimo = null,
      finished_at = clock_timestamp()
  where id = p_ejecucion_c4_id
  returning * into v_ejecucion;

  return v_ejecucion;
end;
$$;

create or replace function public.reintentar_ejecucion_c4(
  p_ejecucion_c4_id uuid,
  p_id_repositorio text,
  p_usuario_id uuid
)
returns public.ejecuciones_c4
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_ejecucion public.ejecuciones_c4;
  v_tarea_anterior public.tareas_proyecto;
  v_tipo text;
  v_fase text;
begin
  select ejecucion.* into v_ejecucion
  from public.ejecuciones_c4 as ejecucion
  where ejecucion.id = p_ejecucion_c4_id
    and ejecucion.id_repositorio = p_id_repositorio
    and exists (
      select 1 from public.proyectos as proyecto
      where proyecto.id_repositorio = ejecucion.id_repositorio
        and proyecto.usuario_id = p_usuario_id
    )
  for update;

  if not found then
    raise exception 'execution does not exist or is not owned by user' using errcode = '42501';
  end if;
  if v_ejecucion.estado not in ('fallido', 'cancelado') then
    raise exception 'only a failed or canceled execution can be retried' using errcode = '55000';
  end if;
  if exists (
    select 1 from public.tareas_proyecto
    where id_repositorio = p_id_repositorio
      and estado in ('pendiente', 'procesando')
  ) then
    raise exception 'repository already has an active task' using errcode = '55000';
  end if;

  select tarea.* into v_tarea_anterior
  from public.tareas_proyecto as tarea
  where tarea.ejecucion_c4_id = p_ejecucion_c4_id
    and tarea.tipo in ('analisis_c4', 'publicacion_c4')
  order by tarea.created_at desc, tarea.id desc
  limit 1;

  v_fase := coalesce(v_ejecucion.resultado->>'fase', 'ingesta');
  v_tipo := case
    when v_fase in ('generacion', 'validacion', 'completado') then 'publicacion_c4'
    else 'analisis_c4'
  end;
  if v_tarea_anterior.id is not null and v_fase <> 'revision' then
    v_tipo := v_tarea_anterior.tipo;
  end if;

  update public.ejecuciones_c4
  set estado = 'pendiente',
      error_ultimo = null,
      started_at = null,
      finished_at = null,
      resultado = case
        when v_tipo = 'analisis_c4' then jsonb_build_object('fase', 'ingesta', 'version', 0, 'hash', '')
        else resultado
      end
  where id = p_ejecucion_c4_id
  returning * into v_ejecucion;

  insert into public.tareas_proyecto (
    usuario_id, id_repositorio, tipo, estado, payload, ejecucion_c4_id,
    fase, progreso, paso, mensaje, unidades_completadas, unidades_totales,
    intentos, max_intentos
  ) values (
    p_usuario_id, p_id_repositorio, v_tipo, 'pendiente',
    jsonb_build_object('id_ejecucion', p_ejecucion_c4_id), p_ejecucion_c4_id,
    case when v_tipo = 'publicacion_c4' then 'generacion' else 'ingesta' end,
    0, 'en_cola', 'Reintento en cola', null, null, 0,
    coalesce(v_tarea_anterior.max_intentos, 3)
  );

  return v_ejecucion;
end;
$$;

revoke all on function public.heartbeat_tarea_proyecto(uuid, text, integer, integer, integer, text, text, text, integer, integer)
  from public, anon, authenticated;
revoke all on function public.cancelar_ejecucion_c4(uuid, text, uuid)
  from public, anon, authenticated;
revoke all on function public.reintentar_ejecucion_c4(uuid, text, uuid)
  from public, anon, authenticated;

grant execute on function public.heartbeat_tarea_proyecto(uuid, text, integer, integer, integer, text, text, text, integer, integer)
  to service_role;
grant execute on function public.cancelar_ejecucion_c4(uuid, text, uuid) to service_role;
grant execute on function public.reintentar_ejecucion_c4(uuid, text, uuid) to service_role;
