export type EstadoEjecucionC4 = 'pendiente' | 'procesando' | 'completado' | 'fallido' | 'cancelado';

export type FaseEjecucionC4 =
  'ingesta' | 'descubrimiento' | 'revision' | 'generacion' | 'validacion' | 'completado';

export type DecisionCandidatoC4 = 'PENDIENTE' | 'APROBADO' | 'RECHAZADO';

export interface ActorC4 {
  nombre: string;
  descripcion: string;
}

export interface SistemaExternoC4 {
  nombre: string;
  descripcion: string;
}

export interface ContextoC4 {
  nombre_sistema: string;
  descripcion: string;
  proposito: string;
  actores: ActorC4[];
  sistemas_externos: SistemaExternoC4[];
}

export interface CrearEjecucionC4 {
  contexto: ContextoC4;
}

export interface CandidatoC4Base {
  id: string;
  nombre: string;
  descripcion: string;
  inferido: boolean;
  decision: DecisionCandidatoC4;
  procedencia?: 'detected' | 'analyst_provided' | 'inferred' | string;
  agente?: string;
  modulo?: string;
  marcado?: 'sin_evidencia_import' | 'probable_duplicado' | string | null;
  evidencias?: EvidenciaCandidatoC4[];
}

export interface EvidenciaCandidatoC4 {
  id: string;
  ruta: string;
  linea_inicio?: number | null;
  linea_fin?: number | null;
  simbolo?: string | null;
  agente?: string | null;
  modulo?: string | null;
  resumen?: string | null;
}

export interface ResumenSemanticoC4 {
  chunks_totales?: number;
  chunks_indexados?: number;
  lenguajes?: string[];
  backend_indice?: string;
}

export interface ConflictoC4 {
  id: string;
  titulo?: string;
  descripcion?: string;
  identidad?: string;
  tipo?: string;
  razon?: string;
  candidatos_ids?: string[];
  valores?: string[];
  evidencia_ids?: string[];
  evidencias?: EvidenciaCandidatoC4[];
}

export interface HuerfanoC4 {
  id: string;
  descripcion?: string;
  tipo_candidato?: 'elemento' | 'relacion' | 'referencia' | string;
  candidato_id?: string;
  razon?: string;
  referencias_faltantes?: string[];
  evidencia_ids?: string[];
  evidencia?: EvidenciaCandidatoC4;
}

export interface HallazgoJuezC4 {
  id: string;
  titulo?: string;
  descripcion?: string;
  severidad?: 'informativo' | 'advertencia' | 'critico' | string;
  codigo?: string;
  mensaje?: string;
  recomendacion?: string;
  elementos_ids?: string[];
  evidencia_ids?: string[];
}

export interface ElementoC4 extends CandidatoC4Base {
  tipo: string;
  padre_id?: string | null;
}

export interface RelacionC4 extends CandidatoC4Base {
  origen_id: string;
  destino_id: string;
  tecnologia?: string | null;
  derivacion?: string | null;
}

export interface RevisionC4 {
  hash: string;
  version: number;
  elementos: ElementoC4[];
  relaciones: RelacionC4[];
  resumen_semantico?: ResumenSemanticoC4;
  conflictos?: ConflictoC4[];
  huerfanos?: HuerfanoC4[];
  hallazgos_juez?: HallazgoJuezC4[];
  consolidacion_capacidades?: Record<string, unknown>[];
  reparacion_capacidades?: Record<string, unknown>;
}

export interface GuardarRevisionC4 extends RevisionC4 {}

export interface ValidacionC4 {
  valida: boolean;
  errores: string[];
  advertencias: string[];
}

export interface ArtefactoC4 {
  id: string;
  nombre: string;
  etiqueta?: string;
  tipo?: string;
}

export interface DiagramaC4 {
  id: string;
  nombre: string;
  nivel: string;
  formato?: string;
}

export interface TareaActualC4 {
  id: string;
  tipo: string;
  estado: EstadoEjecucionC4;
  fase: FaseEjecucionC4;
  paso: string;
  progreso: number;
  mensaje?: string | null;
  iniciado_en?: string | null;
  ultima_actividad_en?: string | null;
  unidades_completadas?: number | null;
  unidades_totales?: number | null;
  intentos: number;
  max_intentos: number;
  eta_segundos?: number | null;
}

export interface EjecucionC4 {
  id: string;
  id_repositorio: string;
  estado: EstadoEjecucionC4;
  fase: FaseEjecucionC4;
  mensaje?: string | null;
  error?: string | null;
  version: number;
  hash: string;
  creado_en?: string;
  actualizado_en?: string;
  validacion?: ValidacionC4 | null;
  artefactos: ArtefactoC4[];
  diagramas: DiagramaC4[];
  tarea_actual?: TareaActualC4 | null;
}

export interface ResumenEjecucionC4 {
  id: string;
  id_repositorio: string;
  nombre_repositorio: string;
  nombre_sistema: string;
  estado: EstadoEjecucionC4;
  fase: FaseEjecucionC4;
  creado_en?: string;
  actualizado_en?: string;
  error?: string | null;
  tarea_actual?: TareaActualC4 | null;
}

export interface HistorialC4 {
  mensaje?: string;
  ejecuciones: ResumenEjecucionC4[];
}
