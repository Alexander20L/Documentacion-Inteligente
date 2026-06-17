alter table public.proyectos
  add column if not exists nombre_archivo text,
  add column if not exists estado text not null default 'subido',
  add column if not exists url_graph_html text,
  add column if not exists url_graph_json text,
  add column if not exists url_reporte text,
  add column if not exists created_at timestamptz default now();

alter table public.tareas_proyecto
  add column if not exists started_at timestamptz,
  add column if not exists finished_at timestamptz;

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'proyectos'
      and column_name = 'creado_en'
  ) then
    execute '
      update public.proyectos
      set created_at = coalesce(created_at, creado_en)
      where created_at is null
    ';
  end if;
end;
$$;

create index if not exists idx_proyectos_usuario_repositorio
  on public.proyectos(usuario_id, id_repositorio);

create index if not exists idx_tareas_proyecto_estado_created_at
  on public.tareas_proyecto(estado, created_at);

create index if not exists idx_tareas_proyecto_repo_tipo
  on public.tareas_proyecto(id_repositorio, tipo);

create unique index if not exists uq_tareas_proyecto_activas
  on public.tareas_proyecto(id_repositorio, tipo)
  where estado in ('pendiente', 'procesando');
