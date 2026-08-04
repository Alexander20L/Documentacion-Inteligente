from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EstadoEjecucionC4 = Literal["pendiente", "procesando", "completado", "fallido", "cancelado"]
FaseEjecucionC4 = Literal["ingesta", "descubrimiento", "revision", "generacion", "validacion", "completado"]
DecisionCandidatoC4 = Literal["PENDIENTE", "APROBADO", "RECHAZADO"]


class ModeloC4(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActorC4(ModeloC4):
    nombre: str = Field(min_length=1)
    descripcion: str


class SistemaExternoC4(ModeloC4):
    nombre: str = Field(min_length=1)
    descripcion: str


class ContextoC4(ModeloC4):
    nombre_sistema: str = Field(min_length=1)
    descripcion: str
    proposito: str
    actores: list[ActorC4]
    sistemas_externos: list[SistemaExternoC4]


class CrearEjecucionC4(ModeloC4):
    contexto: ContextoC4


class ElementoC4(ModeloC4):
    id: str
    nombre: str = Field(min_length=1)
    descripcion: str
    inferido: bool
    decision: DecisionCandidatoC4
    tipo: str
    padre_id: str | None = None
    procedencia: str | None = None
    agente: str | None = None
    modulo: str | None = None
    marcado: str | None = None
    evidencias: list[dict[str, Any]] | None = None


class RelacionC4(ModeloC4):
    id: str
    nombre: str = Field(min_length=1)
    descripcion: str
    inferido: bool
    decision: DecisionCandidatoC4
    origen_id: str
    destino_id: str
    tecnologia: str | None = None
    derivacion: str | None = None
    procedencia: str | None = None
    agente: str | None = None
    modulo: str | None = None
    marcado: str | None = None
    evidencias: list[dict[str, Any]] | None = None


class RevisionC4(ModeloC4):
    hash: str
    version: int = Field(ge=1)
    elementos: list[ElementoC4]
    relaciones: list[RelacionC4]
    resumen_evidencia: list[dict[str, Any]] | None = None
    agentes: list[dict[str, Any]] | None = None
    conflictos: list[dict[str, Any]] | None = None
    huerfanos: list[dict[str, Any]] | None = None
    hallazgos_juez: list[dict[str, Any]] | None = None
    resumen_semantico: dict[str, Any] | None = None
    consolidacion_capacidades: list[dict[str, Any]] | None = None
    reparacion_capacidades: dict[str, Any] | None = None


class ValidacionC4(ModeloC4):
    valida: bool
    errores: list[str]
    advertencias: list[str]


class ArtefactoC4(ModeloC4):
    id: str
    nombre: str
    etiqueta: str | None = None
    tipo: str | None = None


class DiagramaC4(ModeloC4):
    id: str
    nombre: str
    nivel: str
    formato: str | None = None


class ProgresoTareaC4(ModeloC4):
    id: str
    tipo: str
    estado: EstadoEjecucionC4
    fase: FaseEjecucionC4
    progreso: int = Field(ge=0, le=100)
    paso: str
    mensaje: str | None = None
    iniciado_en: str | None = None
    ultima_actividad_en: str | None = None
    unidades_completadas: int | None = Field(default=None, ge=0)
    unidades_totales: int | None = Field(default=None, ge=0)
    eta_segundos: int | None = Field(default=None, ge=0)
    intentos: int = Field(ge=0)
    max_intentos: int = Field(gt=0)


class EjecucionC4(ModeloC4):
    id: str
    id_repositorio: str
    estado: EstadoEjecucionC4
    fase: FaseEjecucionC4
    mensaje: str | None = None
    error: str | None = None
    version: int
    hash: str
    creado_en: str | None = None
    actualizado_en: str | None = None
    validacion: ValidacionC4 | None = None
    artefactos: list[ArtefactoC4]
    diagramas: list[DiagramaC4]
    tarea_actual: ProgresoTareaC4 | None = None


class ResumenEjecucionC4(ModeloC4):
    id: str
    id_repositorio: str
    nombre_repositorio: str
    nombre_sistema: str
    estado: EstadoEjecucionC4
    fase: FaseEjecucionC4
    creado_en: str | None = None
    actualizado_en: str | None = None
    error: str | None = None
    tarea_actual: ProgresoTareaC4 | None = None


class HistorialC4(ModeloC4):
    mensaje: str | None = None
    ejecuciones: list[ResumenEjecucionC4]
