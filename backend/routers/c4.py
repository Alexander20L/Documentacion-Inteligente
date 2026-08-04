from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse

from c4core import EvidenceRecord, assemble_canonical_model
from configuracion.rutas_c4 import obtener_ruta_ejecucion
from configuracion.supabase_cliente import supabase_admin
from modelos.c4 import CrearEjecucionC4, EjecucionC4, ProgresoTareaC4, RevisionC4
from seguridad import UsuarioAutenticado, obtener_cliente_usuario, obtener_proyecto_del_usuario, obtener_usuario_actual
from servicios.c4_revision import actualizar_contenido_revision, materializar_revision, revision_publica


router = APIRouter(prefix="/repositorios/{id_repositorio}/c4/ejecuciones", tags=["C4"])


def esquema_progreso_pendiente(error: Exception) -> bool:
    codigo = str(getattr(error, "code", ""))
    detalle = str(error).casefold()
    return codigo in {"42703", "PGRST204"} or any(
        columna in detalle
        for columna in ("tareas_proyecto.paso", "tareas_proyecto.mensaje", "unidades_completadas", "unidades_totales")
    )


def _una_fila(resultado, detalle: str = "Recurso C4 no encontrado") -> dict[str, Any]:
    if not resultado.data:
        raise HTTPException(status_code=404, detail=detalle)
    return dict(resultado.data[0])


def _obtener_ejecucion(cliente, id_repositorio: str, id_ejecucion: str) -> dict[str, Any]:
    return _una_fila(
        cliente.table("ejecuciones_c4").select("*")
        .eq("id", id_ejecucion).eq("id_repositorio", id_repositorio).limit(1).execute()
    )


def _obtener_revision(cliente, id_ejecucion: str) -> dict[str, Any]:
    return _una_fila(
        cliente.table("revisiones_c4").select("*").eq("ejecucion_c4_id", id_ejecucion)
        .order("created_at", desc=True).limit(1).execute(),
        "La revisión C4 todavía no está disponible",
    )


def serializar_progreso_tarea(tarea: dict[str, Any] | None, fase_ejecucion: str) -> dict[str, Any] | None:
    if not tarea:
        return None
    esperando_revision = fase_ejecucion == "revision" and tarea.get("tipo") == "analisis_c4" and tarea.get("estado") == "completado"
    return ProgresoTareaC4(
        id=str(tarea["id"]),
        tipo=tarea["tipo"],
        estado="procesando" if esperando_revision else tarea["estado"],
        fase="revision" if esperando_revision else (tarea.get("fase") or fase_ejecucion),
        progreso=int(tarea.get("progreso") or 0),
        paso="revision_humana" if esperando_revision else (tarea.get("paso") or tarea.get("fase") or fase_ejecucion),
        mensaje="Esperando revisión humana" if esperando_revision else tarea.get("mensaje"),
        iniciado_en=tarea.get("started_at"),
        ultima_actividad_en=tarea.get("heartbeat_at") or tarea.get("updated_at"),
        unidades_completadas=tarea.get("unidades_completadas"),
        unidades_totales=tarea.get("unidades_totales"),
        eta_segundos=None,
        intentos=int(tarea.get("intentos") or 0),
        max_intentos=int(tarea.get("max_intentos") or 3),
    ).model_dump(mode="json")


def _obtener_tarea_actual(cliente, id_ejecucion: str) -> dict[str, Any] | None:
    consulta = cliente.table("tareas_proyecto")
    try:
        resultado = (
            consulta.select("id,tipo,estado,fase,progreso,paso,mensaje,unidades_completadas,unidades_totales,intentos,max_intentos,started_at,heartbeat_at,updated_at,created_at")
            .eq("ejecucion_c4_id", id_ejecucion).order("created_at", desc=True).limit(1).execute()
        )
    except Exception as error:
        if not esquema_progreso_pendiente(error):
            raise
        resultado = (
            cliente.table("tareas_proyecto")
            .select("id,tipo,estado,fase,progreso,intentos,max_intentos,started_at,heartbeat_at,updated_at,created_at")
            .eq("ejecucion_c4_id", id_ejecucion).order("created_at", desc=True).limit(1).execute()
        )
    return dict(resultado.data[0]) if resultado.data else None


def serializar_ejecucion(fila: dict[str, Any], tarea: dict[str, Any] | None = None) -> dict[str, Any]:
    resultado = fila.get("resultado") or {}
    fase = resultado.get("fase", "ingesta")
    return EjecucionC4(
        id=str(fila["id"]),
        id_repositorio=fila["id_repositorio"],
        estado=fila["estado"],
        fase=fase,
        mensaje=resultado.get("mensaje"),
        error=fila.get("error_ultimo"),
        version=resultado.get("version", 0),
        hash=resultado.get("hash", ""),
        creado_en=fila.get("created_at"),
        actualizado_en=fila.get("updated_at"),
        validacion=resultado.get("validacion"),
        artefactos=resultado.get("artefactos", []),
        diagramas=resultado.get("diagramas", []),
        tarea_actual=serializar_progreso_tarea(tarea, fase),
    ).model_dump(mode="json")


def _preparar_contenido_revision(fila: dict[str, Any], solicitud: RevisionC4) -> dict[str, Any]:
    actual = revision_publica(fila.get("contenido") or {})
    if solicitud.hash != actual["hash"] or solicitud.version != actual["version"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La revisión cambió; vuelve a cargarla")
    try:
        return actualizar_contenido_revision(fila["contenido"], solicitud)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _guardar_revision_con_concurrencia(fila: dict[str, Any], solicitud: RevisionC4, contenido: dict[str, Any]) -> dict[str, Any]:
    resultado = (
        supabase_admin.table("revisiones_c4").update({"contenido": contenido})
        .eq("id", fila["id"])
        .contains("contenido", {"revision": {"hash": solicitud.hash, "version": solicitud.version}})
        .execute()
    )
    if not resultado.data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La revisión cambió; vuelve a cargarla")
    return dict(resultado.data[0])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EjecucionC4)
def crear_ejecucion(
    id_repositorio: str,
    solicitud: CrearEjecucionC4,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    activa = (
        cliente.table("ejecuciones_c4").select("id")
        .eq("id_repositorio", id_repositorio)
        .in_("estado", ["pendiente", "procesando"])
        .limit(1).execute()
    )
    if activa.data:
        raise HTTPException(status_code=409, detail="El repositorio ya tiene una ejecución C4 activa")
    try:
        ejecucion = _una_fila(supabase_admin.table("ejecuciones_c4").insert({
            "id_repositorio": id_repositorio,
            "estado": "pendiente",
            "configuracion": solicitud.model_dump(mode="json"),
            "resultado": {"fase": "ingesta", "version": 0, "hash": ""},
        }).execute(), "No se pudo crear la ejecución C4")
    except Exception as error:
        raise HTTPException(status_code=409, detail="El repositorio ya tiene una ejecución C4 activa") from error
    try:
        tarea_payload = {
            "usuario_id": usuario.id,
            "id_repositorio": id_repositorio,
            "tipo": "analisis_c4",
            "estado": "pendiente",
            "payload": {"id_ejecucion": ejecucion["id"]},
            "ejecucion_c4_id": ejecucion["id"],
            "fase": "ingesta",
            "paso": "en_cola",
            "mensaje": "Análisis C4 en cola",
        }
        try:
            tarea = _una_fila(supabase_admin.table("tareas_proyecto").insert(tarea_payload).execute(), "No se pudo encolar analisis_c4")
        except Exception as error:
            if not esquema_progreso_pendiente(error):
                raise
            tarea_payload.pop("paso", None)
            tarea_payload.pop("mensaje", None)
            tarea = _una_fila(supabase_admin.table("tareas_proyecto").insert(tarea_payload).execute(), "No se pudo encolar analisis_c4")
    except Exception as error:
        supabase_admin.table("ejecuciones_c4").update({"estado": "fallido", "error_ultimo": "No se pudo encolar analisis_c4"}).eq("id", ejecucion["id"]).execute()
        raise HTTPException(status_code=409, detail="El repositorio ya tiene una tarea activa") from error
    return serializar_ejecucion(ejecucion, tarea)


@router.get("/{id_ejecucion}", response_model=EjecucionC4)
def obtener_ejecucion(id_repositorio: str, id_ejecucion: str, response: Response, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    response.headers["Cache-Control"] = "no-store"
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    ejecucion = _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    return serializar_ejecucion(ejecucion, _obtener_tarea_actual(cliente, id_ejecucion))


def _controlar_ejecucion(nombre_rpc: str, id_repositorio: str, id_ejecucion: str, usuario: UsuarioAutenticado):
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    try:
        supabase_admin.rpc(nombre_rpc, {
            "p_ejecucion_c4_id": id_ejecucion,
            "p_id_repositorio": id_repositorio,
            "p_usuario_id": usuario.id,
        }).execute()
    except Exception as error:
        raise HTTPException(status_code=409, detail="La ejecución no admite esta operación en su estado actual") from error
    cliente = obtener_cliente_usuario(usuario)
    ejecucion = _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    return serializar_ejecucion(ejecucion, _obtener_tarea_actual(cliente, id_ejecucion))


@router.post("/{id_ejecucion}/cancelar", response_model=EjecucionC4)
def cancelar_ejecucion(id_repositorio: str, id_ejecucion: str, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    return _controlar_ejecucion("cancelar_ejecucion_c4", id_repositorio, id_ejecucion, usuario)


@router.post("/{id_ejecucion}/reintentar", response_model=EjecucionC4)
def reintentar_ejecucion(id_repositorio: str, id_ejecucion: str, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    return _controlar_ejecucion("reintentar_ejecucion_c4", id_repositorio, id_ejecucion, usuario)


@router.get("/{id_ejecucion}/revision", response_model=RevisionC4)
def obtener_revision(id_repositorio: str, id_ejecucion: str, response: Response, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    response.headers["Cache-Control"] = "no-store"
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    return revision_publica(_obtener_revision(cliente, id_ejecucion).get("contenido") or {})


@router.get("/{id_ejecucion}/explorador")
def obtener_explorador(id_repositorio: str, id_ejecucion: str, response: Response, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    response.headers["Cache-Control"] = "no-store"
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    ejecucion = _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    revision = None
    try:
        revision = revision_publica(_obtener_revision(cliente, id_ejecucion).get("contenido") or {})
    except HTTPException:
        revision = None
    return {
        "ejecucion": serializar_ejecucion(ejecucion, _obtener_tarea_actual(cliente, id_ejecucion)),
        "revision": revision,
    }


@router.put("/{id_ejecucion}/revision", response_model=RevisionC4)
def guardar_revision(id_repositorio: str, id_ejecucion: str, solicitud: RevisionC4, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    ejecucion = _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    if (ejecucion.get("resultado") or {}).get("fase") != "revision":
        raise HTTPException(status_code=409, detail="La ejecución no está en fase de revisión")
    fila_revision = _obtener_revision(cliente, id_ejecucion)
    contenido = _preparar_contenido_revision(fila_revision, solicitud)
    guardada = _guardar_revision_con_concurrencia(fila_revision, solicitud, contenido)
    publica = revision_publica(guardada["contenido"])
    supabase_admin.table("ejecuciones_c4").update({"resultado": {**(ejecucion.get("resultado") or {}), "version": publica["version"], "hash": publica["hash"]}}).eq("id", id_ejecucion).execute()
    return publica


@router.post("/{id_ejecucion}/revision/aprobar", response_model=EjecucionC4)
def aprobar_revision(id_repositorio: str, id_ejecucion: str, solicitud: RevisionC4, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    ejecucion = _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    if (ejecucion.get("resultado") or {}).get("fase") != "revision":
        raise HTTPException(status_code=409, detail="La ejecución no está en fase de revisión")
    fila_revision = _obtener_revision(cliente, id_ejecucion)
    contenido = _preparar_contenido_revision(fila_revision, solicitud)
    try:
        elementos, relaciones, decisiones = materializar_revision(contenido, usuario.id)
        evidencia = tuple(EvidenceRecord.model_validate(item) for item in contenido.get("evidencia", []))
        contexto = (ejecucion.get("configuracion") or {}).get("contexto") or {}
        modelo = assemble_canonical_model(
            contexto.get("nombre_sistema", id_repositorio),
            contexto.get("descripcion") or contexto.get("proposito", ""),
            elementos,
            relaciones,
            evidencia,
            decisiones,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    guardada = _guardar_revision_con_concurrencia(fila_revision, solicitud, contenido)
    publica = revision_publica(contenido)
    resultado = {
        **(ejecucion.get("resultado") or {}),
        "fase": "generacion",
        "version": publica["version"],
        "hash": publica["hash"],
        "modelo_aprobado": modelo.model_dump(mode="json"),
    }
    try:
        supabase_admin.rpc("encolar_publicacion_c4", {
            "p_revision_id": guardada["id"],
            "p_ejecucion_c4_id": id_ejecucion,
            "p_usuario_id": usuario.id,
            "p_id_repositorio": id_repositorio,
            "p_contenido": contenido,
            "p_resultado": resultado,
        }).execute()
    except Exception as error:
        raise HTTPException(status_code=409, detail="No se pudo encolar la publicación C4") from error
    tarea = _obtener_tarea_actual(cliente, id_ejecucion)
    return serializar_ejecucion({
        **ejecucion,
        "estado": "pendiente",
        "resultado": resultado,
        "error_ultimo": None,
        "finished_at": None,
    }, tarea)


@router.get("/{id_ejecucion}/artefactos/{id_artefacto}")
def descargar_artefacto(id_repositorio: str, id_ejecucion: str, id_artefacto: str, usuario: UsuarioAutenticado = Depends(obtener_usuario_actual)):
    obtener_proyecto_del_usuario(id_repositorio, usuario)
    cliente = obtener_cliente_usuario(usuario)
    _obtener_ejecucion(cliente, id_repositorio, id_ejecucion)
    artefacto = _una_fila(cliente.table("artefactos_c4").select("*").eq("ejecucion_c4_id", id_ejecucion).eq("id", id_artefacto).limit(1).execute(), "Artefacto no encontrado")
    try:
        ruta = obtener_ruta_ejecucion(id_repositorio, id_ejecucion, artefacto["ruta"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Ruta de artefacto inválida") from error
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail="Artefacto no encontrado en disco")
    metadata = artefacto.get("metadata") or {}
    if metadata.get("sha256") and hashlib.sha256(ruta.read_bytes()).hexdigest() != metadata["sha256"]:
        raise HTTPException(status_code=409, detail="El artefacto no supera la verificación de integridad")
    return FileResponse(str(ruta), filename=artefacto["nombre"], media_type=metadata.get("media_type"))
