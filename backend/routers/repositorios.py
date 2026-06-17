import logging
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from configuracion.rutas_repositorios import (
    REPOS_DIR,
    resolver_ruta_graphify_out,
)
from configuracion.url_base import construir_url_publica
from modelos.estados_proyecto import EstadoDocumentacion, EstadoProyecto
from modelos.proyecto import AnalisisRepositorioRequest
from seguridad import (
    UsuarioAutenticado,
    obtener_cliente_usuario,
    obtener_proyecto_del_usuario,
    obtener_usuario_actual,
)
from servicios.servicio_graphify import (
    ARCHIVOS_GRAPHIFY,
    construir_estado_archivos_graphify,
)
from servicios.servicio_zip import (
    UPLOADS_DIR,
    extraer_zip_seguro,
    guardar_upload_en_disco,
    validar_nombre_zip,
)
from servicios.tareas import (
    actualizar_proyecto_admin,
    encolar_tarea_proyecto,
    obtener_estado_proyecto,
)


router = APIRouter(prefix="/repositorios", tags=["Repositorios"])
logger = logging.getLogger(__name__)

NOMBRE_DOCUMENTACION_WORD = "DOCUMENTACION_TECNICA.docx"

MEDIA_TYPES_GRAPHIFY = {
    "graph.json": "application/json",
    "manifest.json": "application/json",
    ".graphify_analysis.json": "application/json",
    "graph.html": "text/html; charset=utf-8",
    "GRAPH_REPORT.md": "text/markdown; charset=utf-8",
}


def normalizar_nombre_archivo(nombre_archivo: str | None) -> str:
    nombre = nombre_archivo or "repositorio.zip"
    return nombre.replace("\\", "/").split("/")[-1]


def resolver_graphify_out_opcional(id_repositorio: str):
    try:
        return resolver_ruta_graphify_out(id_repositorio)
    except HTTPException:
        return None


def construir_url_word(id_repositorio: str, ruta_graphify_out) -> str | None:
    if not ruta_graphify_out:
        return None

    ruta_word = ruta_graphify_out / NOMBRE_DOCUMENTACION_WORD

    if not ruta_word.is_file():
        return None

    return construir_url_publica(f"documentacion/{id_repositorio}/word")


def enriquecer_proyecto_con_archivos(proyecto: dict) -> dict:
    proyecto_normalizado = dict(proyecto)
    id_repositorio = proyecto_normalizado.get("id_repositorio")

    if not id_repositorio:
        return proyecto_normalizado

    ruta_graphify_out = resolver_graphify_out_opcional(id_repositorio)

    estado_archivos = construir_estado_archivos_graphify(
        f"repositorios/{id_repositorio}",
        ruta_graphify_out,
    )

    proyecto_normalizado.update(estado_archivos)

    proyecto_normalizado["url_graph_html"] = estado_archivos["archivos"]["html"]
    proyecto_normalizado["url_graph_json"] = estado_archivos["archivos"]["json"]
    proyecto_normalizado["url_reporte"] = estado_archivos["archivos"]["reporte"]
    proyecto_normalizado["url_word"] = construir_url_word(
        id_repositorio,
        ruta_graphify_out,
    )

    return proyecto_normalizado


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
    ruta_destino = REPOS_DIR / id_repositorio

    ruta_destino.mkdir(parents=True, exist_ok=True)

    try:
        await guardar_upload_en_disco(archivo, ruta_zip)
        extraer_zip_seguro(ruta_zip, ruta_destino)

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
        shutil.rmtree(ruta_destino, ignore_errors=True)
        ruta_zip.unlink(missing_ok=True)
        raise

    except Exception as error:
        logger.exception("No se pudo registrar el proyecto subido")
        shutil.rmtree(ruta_destino, ignore_errors=True)
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


@router.post("/{id_repositorio}/analizar")
def analizar_repositorio(
    id_repositorio: str,
    payload: AnalisisRepositorioRequest,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    proyecto = obtener_proyecto_del_usuario(id_repositorio, usuario)

    tarea = encolar_tarea_proyecto(
        id_repositorio,
        "analisis",
        usuario,
        payload={
            "nombre_archivo": payload.nombre_archivo
            or proyecto.get("nombre_archivo"),
        },
    )

    actualizar_proyecto_admin(
        id_repositorio,
        {
            "estado": EstadoProyecto.PENDIENTE_ANALISIS.value,
            "error_ultimo": None,
        },
    )

    return {
        "mensaje": "Análisis encolado correctamente",
        "id_repositorio": id_repositorio,
        "tarea": tarea,
        "estado": EstadoProyecto.PENDIENTE_ANALISIS.value,
        "siguiente_accion": "CONSULTAR_ESTADO",
    }


@router.get("/historial")
def obtener_historial(
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    resultado = (
        obtener_cliente_usuario(usuario)
        .table("proyectos")
        .select("*")
        .execute()
    )

    proyectos_ordenados = sorted(
        resultado.data or [],
        key=lambda proyecto: proyecto.get("creado_en")
        or proyecto.get("created_at")
        or "",
        reverse=True,
    )

    proyectos = [
        enriquecer_proyecto_con_archivos(proyecto)
        for proyecto in proyectos_ordenados
    ]

    return {
        "mensaje": "Historial obtenido correctamente",
        "proyectos": proyectos,
    }


@router.get("/{id_repositorio}/estado")
def consultar_estado_repositorio(
    id_repositorio: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    estado = obtener_estado_proyecto(id_repositorio, usuario)
    proyecto = enriquecer_proyecto_con_archivos(estado["proyecto"])

    return {
        "mensaje": "Estado del proyecto obtenido correctamente",
        "proyecto": proyecto,
        "tareas": estado["tareas"],
    }


@router.get("/{id_repositorio}/{nombre_archivo}")
def obtener_archivo_graphify(
    id_repositorio: str,
    nombre_archivo: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    archivos_permitidos = set(ARCHIVOS_GRAPHIFY.values())

    if nombre_archivo not in archivos_permitidos:
        raise HTTPException(
            status_code=400,
            detail="Archivo no permitido",
        )

    obtener_proyecto_del_usuario(id_repositorio, usuario)

    ruta_graphify_out = resolver_ruta_graphify_out(id_repositorio)
    ruta_archivo = ruta_graphify_out / nombre_archivo

    if not ruta_archivo.is_file():
        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado",
        )

    media_type = MEDIA_TYPES_GRAPHIFY.get(nombre_archivo)

    if nombre_archivo == "graph.html":
        return FileResponse(
            str(ruta_archivo),
            media_type=media_type,
        )

    return FileResponse(
        str(ruta_archivo),
        media_type=media_type,
        filename=nombre_archivo,
    )