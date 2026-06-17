from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from configuracion.supabase_cliente import crear_cliente_supabase_usuario, supabase_admin
from seguridad import UsuarioAutenticado

ESTADOS_TAREA_ACTIVOS = {"pendiente", "procesando"}
TIPOS_TAREA_VALIDOS = {"analisis", "documentacion"}


def _timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cliente_usuario(usuario: UsuarioAutenticado):
    return crear_cliente_supabase_usuario(usuario.token)


def _normalizar_tarea(tarea: dict[str, Any]) -> dict[str, Any]:
    payload = tarea.get("payload")

    if payload is None:
        tarea["payload"] = {}

    return tarea


def obtener_tarea_activa(
    id_repositorio: str,
    tipo: str,
    usuario: UsuarioAutenticado,
) -> dict[str, Any] | None:
    resultado = (
        _cliente_usuario(usuario)
        .table("tareas_proyecto")
        .select("*")
        .eq("id_repositorio", id_repositorio)
        .eq("tipo", tipo)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    for tarea in resultado.data or []:
        if tarea.get("estado") in ESTADOS_TAREA_ACTIVOS:
            return _normalizar_tarea(dict(tarea))

    return None


def encolar_tarea_proyecto(
    id_repositorio: str,
    tipo: str,
    usuario: UsuarioAutenticado,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tipo not in TIPOS_TAREA_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de tarea no soportado",
        )

    tarea_existente = obtener_tarea_activa(id_repositorio, tipo, usuario)

    if tarea_existente is not None:
        return tarea_existente

    resultado = (
        _cliente_usuario(usuario)
        .table("tareas_proyecto")
        .insert(
            {
                "usuario_id": usuario.id,
                "id_repositorio": id_repositorio,
                "tipo": tipo,
                "estado": "pendiente",
                "payload": payload or {},
            }
        )
        .execute()
    )

    if not resultado.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo registrar la tarea solicitada",
        )

    return _normalizar_tarea(dict(resultado.data[0]))


def obtener_estado_proyecto(
    id_repositorio: str,
    usuario: UsuarioAutenticado,
) -> dict[str, Any]:
    proyecto_resultado = (
        _cliente_usuario(usuario)
        .table("proyectos")
        .select("*")
        .eq("id_repositorio", id_repositorio)
        .limit(1)
        .execute()
    )

    if not proyecto_resultado.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El proyecto no existe o no te pertenece",
        )

    tareas_resultado = (
        _cliente_usuario(usuario)
        .table("tareas_proyecto")
        .select("*")
        .eq("id_repositorio", id_repositorio)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    proyecto = dict(proyecto_resultado.data[0])
    tareas = [_normalizar_tarea(dict(tarea)) for tarea in tareas_resultado.data or []]
    return {"proyecto": proyecto, "tareas": tareas}


def listar_tareas_pendientes(limit: int = 5) -> list[dict[str, Any]]:
    resultado = (
        supabase_admin.table("tareas_proyecto")
        .select("*")
        .eq("estado", "pendiente")
        .order("created_at")
        .limit(limit)
        .execute()
    )

    return [_normalizar_tarea(dict(tarea)) for tarea in resultado.data or []]


def reclamar_tarea_pendiente(id_tarea: str) -> dict[str, Any] | None:
    resultado = (
        supabase_admin.table("tareas_proyecto")
        .update(
            {
                "estado": "procesando",
                "started_at": _timestamp_iso(),
                "error_ultimo": None,
            }
        )
        .eq("id", id_tarea)
        .eq("estado", "pendiente")
        .execute()
    )

    if not resultado.data:
        return None

    return _normalizar_tarea(dict(resultado.data[0]))


def marcar_tarea_completada(id_tarea: str):
    (
        supabase_admin.table("tareas_proyecto")
        .update(
            {
                "estado": "completado",
                "finished_at": _timestamp_iso(),
                "error_ultimo": None,
            }
        )
        .eq("id", id_tarea)
        .execute()
    )


def marcar_tarea_fallida(id_tarea: str, error: str):
    (
        supabase_admin.table("tareas_proyecto")
        .update(
            {
                "estado": "fallido",
                "finished_at": _timestamp_iso(),
                "error_ultimo": error,
            }
        )
        .eq("id", id_tarea)
        .execute()
    )


def actualizar_proyecto_admin(id_repositorio: str, cambios: dict[str, Any]):
    (
        supabase_admin.table("proyectos")
        .update(cambios)
        .eq("id_repositorio", id_repositorio)
        .execute()
    )
