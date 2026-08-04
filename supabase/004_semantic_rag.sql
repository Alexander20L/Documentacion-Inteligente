-- Semantic content remains in the canonical local run directory. This schema
-- stores only manifests, identifiers, counts, hashes, and operational audit data.
create table if not exists public.indices_conocimiento (
  id uuid primary key default gen_random_uuid(),
  ejecucion_c4_id uuid not null references public.ejecuciones_c4(id) on delete cascade,
  tipo text not null,
  estado text not null default 'pendiente',
  manifiesto_sha256 text not null,
  cantidad_chunks integer not null default 0,
  dataset_externo_id text,
  metadata jsonb not null default '{}'::jsonb,
  error_ultimo text,
  sincronizado_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint indices_conocimiento_tipo_check
    check (tipo in ('local_canonico', 'dify')),
  constraint indices_conocimiento_estado_check
    check (estado in ('pendiente', 'procesando', 'disponible', 'fallido', 'obsoleto')),
  constraint indices_conocimiento_hash_check
    check (manifiesto_sha256 ~ '^[0-9a-f]{64}$'),
  constraint indices_conocimiento_chunks_check
    check (cantidad_chunks >= 0),
  constraint indices_conocimiento_dataset_check
    check (
      (tipo = 'local_canonico' and dataset_externo_id is null)
      or (tipo = 'dify' and nullif(btrim(dataset_externo_id), '') is not null)
    ),
  constraint indices_conocimiento_metadata_check
    check (
      jsonb_typeof(metadata) = 'object'
      and not (metadata ?| array['api_key', 'dify_api_key'])
      and metadata::text !~* '"(dify_)?api[_-]?key"[[:space:]]*:'
    ),
  constraint indices_conocimiento_sincronizacion_check
    check (
      (estado in ('disponible', 'obsoleto') and sincronizado_at is not null)
      or (estado not in ('disponible', 'obsoleto') and sincronizado_at is null)
    ),
  constraint uq_indices_conocimiento_id_ejecucion unique (id, ejecucion_c4_id),
  constraint uq_indices_conocimiento_manifest unique (
    ejecucion_c4_id, tipo, manifiesto_sha256
  )
);

create table if not exists public.ejecuciones_agente (
  id uuid primary key default gen_random_uuid(),
  ejecucion_c4_id uuid not null references public.ejecuciones_c4(id) on delete cascade,
  indice_conocimiento_id uuid,
  tipo text not null,
  estado text not null default 'pendiente',
  entrada_sha256 text,
  salida_sha256 text,
  modelo text,
  version_prompt text,
  metadata jsonb not null default '{}'::jsonb,
  error_ultimo text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ejecuciones_agente_tipo_check
    check (tipo in ('indexador', 'recuperador', 'analista', 'fusionador', 'juez')),
  constraint ejecuciones_agente_estado_check
    check (estado in ('pendiente', 'procesando', 'completado', 'fallido', 'cancelado')),
  constraint ejecuciones_agente_entrada_hash_check
    check (entrada_sha256 is null or entrada_sha256 ~ '^[0-9a-f]{64}$'),
  constraint ejecuciones_agente_salida_hash_check
    check (salida_sha256 is null or salida_sha256 ~ '^[0-9a-f]{64}$'),
  constraint ejecuciones_agente_metadata_check
    check (
      jsonb_typeof(metadata) = 'object'
      and not (metadata ?| array['api_key', 'dify_api_key'])
      and metadata::text !~* '"(dify_)?api[_-]?key"[[:space:]]*:'
    ),
  constraint ejecuciones_agente_fechas_check
    check (finished_at is null or started_at is null or finished_at >= started_at),
  constraint ejecuciones_agente_final_check
    check (estado not in ('completado', 'fallido', 'cancelado') or finished_at is not null),
  constraint ejecuciones_agente_completada_check
    check (estado <> 'completado' or salida_sha256 is not null),
  constraint uq_ejecuciones_agente_id_ejecucion unique (id, ejecucion_c4_id),
  constraint fk_ejecuciones_agente_indice
    foreign key (indice_conocimiento_id, ejecucion_c4_id)
    references public.indices_conocimiento(id, ejecucion_c4_id)
);

create table if not exists public.consultas_rag (
  id uuid primary key default gen_random_uuid(),
  ejecucion_c4_id uuid not null references public.ejecuciones_c4(id) on delete cascade,
  ejecucion_agente_id uuid,
  indice_conocimiento_id uuid not null,
  tipo text not null default 'semantica',
  estado text not null default 'pendiente',
  consulta_sha256 text not null,
  resultados_sha256 text,
  top_k integer not null,
  cantidad_resultados integer not null default 0,
  duracion_ms integer,
  metadata jsonb not null default '{}'::jsonb,
  error_ultimo text,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint consultas_rag_tipo_check
    check (tipo in ('semantica', 'hibrida')),
  constraint consultas_rag_estado_check
    check (estado in ('pendiente', 'procesando', 'completado', 'fallido', 'cancelado')),
  constraint consultas_rag_consulta_hash_check
    check (consulta_sha256 ~ '^[0-9a-f]{64}$'),
  constraint consultas_rag_resultados_hash_check
    check (resultados_sha256 is null or resultados_sha256 ~ '^[0-9a-f]{64}$'),
  constraint consultas_rag_limites_check
    check (
      top_k between 1 and 1000
      and cantidad_resultados between 0 and top_k
      and (duracion_ms is null or duracion_ms >= 0)
    ),
  constraint consultas_rag_metadata_check
    check (
      jsonb_typeof(metadata) = 'object'
      and not (metadata ?| array['api_key', 'dify_api_key'])
      and metadata::text !~* '"(dify_)?api[_-]?key"[[:space:]]*:'
    ),
  constraint consultas_rag_final_check
    check (
      estado not in ('completado', 'fallido', 'cancelado')
      or finished_at is not null
    ),
  constraint consultas_rag_completada_check
    check (estado <> 'completado' or resultados_sha256 is not null),
  constraint fk_consultas_rag_agente
    foreign key (ejecucion_agente_id, ejecucion_c4_id)
    references public.ejecuciones_agente(id, ejecucion_c4_id),
  constraint fk_consultas_rag_indice
    foreign key (indice_conocimiento_id, ejecucion_c4_id)
    references public.indices_conocimiento(id, ejecucion_c4_id)
);

create table if not exists public.evaluaciones_c4 (
  id uuid primary key default gen_random_uuid(),
  ejecucion_c4_id uuid not null references public.ejecuciones_c4(id) on delete cascade,
  ejecucion_agente_id uuid,
  tipo text not null,
  estado text not null default 'pendiente',
  entrada_sha256 text not null,
  reporte_sha256 text,
  veredicto text,
  puntuacion numeric(5,4),
  metadata jsonb not null default '{}'::jsonb,
  error_ultimo text,
  finished_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint evaluaciones_c4_tipo_check
    check (tipo in ('fusion', 'juez')),
  constraint evaluaciones_c4_estado_check
    check (estado in ('pendiente', 'procesando', 'completado', 'fallido', 'cancelado')),
  constraint evaluaciones_c4_entrada_hash_check
    check (entrada_sha256 ~ '^[0-9a-f]{64}$'),
  constraint evaluaciones_c4_reporte_hash_check
    check (reporte_sha256 is null or reporte_sha256 ~ '^[0-9a-f]{64}$'),
  constraint evaluaciones_c4_veredicto_check
    check (
      veredicto is null
      or (
        tipo = 'juez'
        and veredicto in ('aprobado', 'rechazado', 'requiere_revision')
      )
    ),
  constraint evaluaciones_c4_puntuacion_check
    check (puntuacion is null or puntuacion between 0 and 1),
  constraint evaluaciones_c4_metadata_check
    check (
      jsonb_typeof(metadata) = 'object'
      and not (metadata ?| array['api_key', 'dify_api_key'])
      and metadata::text !~* '"(dify_)?api[_-]?key"[[:space:]]*:'
    ),
  constraint evaluaciones_c4_final_check
    check (
      estado not in ('completado', 'fallido', 'cancelado')
      or finished_at is not null
    ),
  constraint evaluaciones_c4_completada_check
    check (
      estado <> 'completado'
      or (
        reporte_sha256 is not null
        and (tipo <> 'juez' or veredicto is not null)
      )
    ),
  constraint fk_evaluaciones_c4_agente
    foreign key (ejecucion_agente_id, ejecucion_c4_id)
    references public.ejecuciones_agente(id, ejecucion_c4_id)
);

comment on column public.indices_conocimiento.dataset_externo_id is
  'External Dify dataset identifier; Dify credentials must never be persisted.';
comment on column public.indices_conocimiento.metadata is
  'Audit metadata only; never store source chunks, retrieved text, or credentials.';
comment on column public.consultas_rag.metadata is
  'Retrieval audit metadata and result IDs only; never store retrieved source text.';
comment on column public.evaluaciones_c4.metadata is
  'Merge/judge audit metadata only; report bodies remain in canonical local artifacts.';

create index if not exists idx_indices_conocimiento_ejecucion_estado
  on public.indices_conocimiento(ejecucion_c4_id, estado, created_at desc);
create index if not exists idx_indices_conocimiento_dataset_externo
  on public.indices_conocimiento(dataset_externo_id)
  where dataset_externo_id is not null;
create index if not exists idx_ejecuciones_agente_ejecucion_tipo
  on public.ejecuciones_agente(ejecucion_c4_id, tipo, created_at desc);
create index if not exists idx_ejecuciones_agente_estado
  on public.ejecuciones_agente(estado, created_at)
  where estado in ('pendiente', 'procesando');
create index if not exists idx_consultas_rag_ejecucion_created_at
  on public.consultas_rag(ejecucion_c4_id, created_at desc);
create index if not exists idx_consultas_rag_indice
  on public.consultas_rag(indice_conocimiento_id, created_at desc);
create index if not exists idx_evaluaciones_c4_ejecucion_tipo
  on public.evaluaciones_c4(ejecucion_c4_id, tipo, created_at desc);

drop trigger if exists set_indices_conocimiento_updated_at on public.indices_conocimiento;
create trigger set_indices_conocimiento_updated_at
before update on public.indices_conocimiento
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_ejecuciones_agente_updated_at on public.ejecuciones_agente;
create trigger set_ejecuciones_agente_updated_at
before update on public.ejecuciones_agente
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_consultas_rag_updated_at on public.consultas_rag;
create trigger set_consultas_rag_updated_at
before update on public.consultas_rag
for each row execute function public.set_current_timestamp_updated_at();

drop trigger if exists set_evaluaciones_c4_updated_at on public.evaluaciones_c4;
create trigger set_evaluaciones_c4_updated_at
before update on public.evaluaciones_c4
for each row execute function public.set_current_timestamp_updated_at();

alter table public.indices_conocimiento enable row level security;
alter table public.ejecuciones_agente enable row level security;
alter table public.consultas_rag enable row level security;
alter table public.evaluaciones_c4 enable row level security;

drop policy if exists "indices_conocimiento_select_own" on public.indices_conocimiento;
create policy "indices_conocimiento_select_own"
on public.indices_conocimiento for select
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = indices_conocimiento.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "ejecuciones_agente_select_own" on public.ejecuciones_agente;
create policy "ejecuciones_agente_select_own"
on public.ejecuciones_agente for select
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = ejecuciones_agente.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "consultas_rag_select_own" on public.consultas_rag;
create policy "consultas_rag_select_own"
on public.consultas_rag for select
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = consultas_rag.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

drop policy if exists "evaluaciones_c4_select_own" on public.evaluaciones_c4;
create policy "evaluaciones_c4_select_own"
on public.evaluaciones_c4 for select
using (exists (
  select 1
  from public.ejecuciones_c4 as ejecucion
  join public.proyectos as proyecto
    on proyecto.id_repositorio = ejecucion.id_repositorio
  where ejecucion.id = evaluaciones_c4.ejecucion_c4_id
    and proyecto.usuario_id = auth.uid()
));

-- Browser clients can only read owned rows. The API/worker service role owns
-- every insert, update, and delete, including agent and retrieval audit writes.
revoke all privileges on table
  public.indices_conocimiento,
  public.ejecuciones_agente,
  public.consultas_rag,
  public.evaluaciones_c4
from public, anon, authenticated;

grant select on table
  public.indices_conocimiento,
  public.ejecuciones_agente,
  public.consultas_rag,
  public.evaluaciones_c4
to authenticated;

grant all privileges on table
  public.indices_conocimiento,
  public.ejecuciones_agente,
  public.consultas_rag,
  public.evaluaciones_c4
to service_role;
