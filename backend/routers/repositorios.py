import hashlib
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from configuracion.rutas_repositorios import REPOS_DIR, obtener_raiz_repositorio, obtener_ruta_fuente
from modelos.estados_proyecto import EstadoDocumentacion, EstadoProyecto
from modelos.c4 import HistorialC4
from routers.c4 import esquema_progreso_pendiente, serializar_progreso_tarea
from seguridad import (
    UsuarioAutenticado,
    obtener_cliente_usuario,
    obtener_usuario_actual,
)
from servicios.servicio_almacenamiento import eliminar_directorio_seguro, publicar_fuente_inmutable
from servicios.servicio_zip import (
    UPLOADS_DIR,
    extraer_zip_seguro,
    guardar_upload_en_disco,
    validar_nombre_zip,
)


router = APIRouter(prefix="/repositorios", tags=["Repositorios"])
logger = logging.getLogger(__name__)

def normalizar_nombre_archivo(nombre_archivo: str | None) -> str:
    nombre = nombre_archivo or "repositorio.zip"
    return nombre.replace("\\", "/").split("/")[-1]


@router.get("/")
def listar_repositorios():
    return {
        "mensaje": "Ruta repositorios funcionando",
        "modulo": "repositorios",
    }


@router.post("/subir", status_code=status.HTTP_201_CREATED)
async def subir_repositorio(
    archivo: UploadFile = File(...),
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    validar_nombre_zip(archivo.filename)

    id_repositorio = str(uuid4())
    nombre_archivo_original = normalizar_nombre_archivo(archivo.filename)

    ruta_zip = UPLOADS_DIR / f"{id_repositorio}.zip"
    # The extracted upload is immutable input. Every analysis works on a copy.
    ruta_destino = obtener_ruta_fuente(id_repositorio)

    ruta_destino.mkdir(parents=True, exist_ok=True)

    try:
        await guardar_upload_en_disco(archivo, ruta_zip)
        extraer_zip_seguro(ruta_zip, ruta_destino)
        digest = hashlib.sha256()
        with ruta_zip.open("rb") as entrada:
            for bloque in iter(lambda: entrada.read(1024 * 1024), b""):
                digest.update(bloque)
        source_hash, _ruta_compartida = publicar_fuente_inmutable(ruta_destino)
        (ruta_destino.parent / "upload.json").write_text(
            json.dumps(
                {
                    "nombre_archivo": nombre_archivo_original,
                    "sha256": digest.hexdigest(),
                    "tamano_bytes": ruta_zip.stat().st_size,
                    "source_hash": source_hash,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        (ruta_destino.parent / "source.json").write_text(
            json.dumps({"source_hash": source_hash}, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        ruta_zip.unlink(missing_ok=True)

        obtener_cliente_usuario(usuario).table("proyectos").insert(
            {
                "usuario_id": usuario.id,
                "id_repositorio": id_repositorio,
                "nombre_archivo": nombre_archivo_original,
                "estado": EstadoProyecto.SUBIDO.value,
                "estado_documentacion": EstadoDocumentacion.PENDIENTE.value,
                "error_ultimo": None,
            }
        ).execute()

    except HTTPException:
        eliminar_directorio_seguro(obtener_raiz_repositorio(id_repositorio), REPOS_DIR)
        ruta_zip.unlink(missing_ok=True)
        raise

    except Exception as error:
        logger.exception("No se pudo registrar el proyecto subido")
        eliminar_directorio_seguro(obtener_raiz_repositorio(id_repositorio), REPOS_DIR)
        ruta_zip.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail="No se pudo registrar el proyecto subido",
        ) from error

    return {
        "mensaje": "Repositorio subido y descomprimido correctamente",
        "id_repositorio": id_repositorio,
        "nombre_archivo": nombre_archivo_original,
        "estado": EstadoProyecto.SUBIDO.value,
        "estado_documentacion": EstadoDocumentacion.PENDIENTE.value,
        "siguiente_accion": "ANALIZAR",
    }


@router.get("/historial", response_model=HistorialC4)
def obtener_historial(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    cliente = obtener_cliente_usuario(usuario)
    proyectos = cliente.table("proyectos").select("id_repositorio,nombre_archivo").execute().data or []
    nombres = {
        item["id_repositorio"]: item.get("nombre_archivo") or item["id_repositorio"]
        for item in proyectos
    }
    resultado = cliente.table("ejecuciones_c4").select("*").order("created_at", desc=True).execute()
    ids_ejecuciones = [str(fila["id"]) for fila in resultado.data or []]
    tareas_por_ejecucion = {}
    if ids_ejecuciones:
        try:
            tareas = (
                cliente.table("tareas_proyecto")
                .select("id,tipo,estado,fase,progreso,paso,mensaje,unidades_completadas,unidades_totales,intentos,max_intentos,started_at,heartbeat_at,updated_at,created_at,ejecucion_c4_id")
                .in_("ejecucion_c4_id", ids_ejecuciones).order("created_at", desc=True).execute().data or []
            )
        except Exception as error:
            if not esquema_progreso_pendiente(error):
                raise
            tareas = (
                cliente.table("tareas_proyecto")
                .select("id,tipo,estado,fase,progreso,intentos,max_intentos,started_at,heartbeat_at,updated_at,created_at,ejecucion_c4_id")
                .in_("ejecucion_c4_id", ids_ejecuciones).order("created_at", desc=True).execute().data or []
            )
        for tarea in tareas:
            tareas_por_ejecucion.setdefault(str(tarea["ejecucion_c4_id"]), dict(tarea))
    ejecuciones = []
    for fila in resultado.data or []:
        configuracion = fila.get("configuracion") or {}
        contexto = configuracion.get("contexto") or {}
        resultado_c4 = fila.get("resultado") or {}
        ejecuciones.append({
            "id": str(fila["id"]),
            "id_repositorio": fila["id_repositorio"],
            "nombre_repositorio": nombres.get(fila["id_repositorio"], fila["id_repositorio"]),
            "nombre_sistema": contexto.get("nombre_sistema", fila["id_repositorio"]),
            "estado": fila["estado"],
            "fase": resultado_c4.get("fase", "ingesta"),
            "creado_en": fila.get("created_at"),
            "actualizado_en": fila.get("updated_at"),
            "error": fila.get("error_ultimo"),
            "tarea_actual": serializar_progreso_tarea(
                tareas_por_ejecucion.get(str(fila["id"])),
                resultado_c4.get("fase", "ingesta"),
            ),
        })
    return {"mensaje": "Historial C4 obtenido correctamente", "ejecuciones": ejecuciones}
