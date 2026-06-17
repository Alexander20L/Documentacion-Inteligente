import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from modelos.estados_proyecto import EstadoDocumentacion, EstadoProyecto
from seguridad import (
    UsuarioAutenticado,
    obtener_proyecto_del_usuario,
    obtener_usuario_actual,
)
from servicios.servicio_documentacion import (
    NOMBRE_DOCUMENTACION_MARKDOWN,
    NOMBRE_DOCUMENTACION_WORD,
    generar_documentacion_tecnica,
    obtener_documentacion_markdown,
    obtener_ruta_markdown_documentacion,
    obtener_ruta_word_documentacion,
)
from servicios.tareas import actualizar_proyecto_admin, encolar_tarea_proyecto


router = APIRouter(prefix="/documentacion", tags=["Documentación"])
logger = logging.getLogger(__name__)


def validar_proyecto_listo_para_documentar(proyecto: dict) -> None:
    estado_actual = proyecto.get("estado")

    if estado_actual != EstadoProyecto.GRAPHIFY_COMPLETADO.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Debes completar el análisis Graphify del repositorio "
                "antes de generar documentación"
            ),
        )


@router.post("/{id_repositorio}/generar")
def generar_documentacion(
    id_repositorio: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    proyecto = obtener_proyecto_del_usuario(id_repositorio, usuario)
    validar_proyecto_listo_para_documentar(proyecto)

    tarea = encolar_tarea_proyecto(
        id_repositorio,
        "documentacion",
        usuario,
    )

    actualizar_proyecto_admin(
        id_repositorio,
        {
            "estado_documentacion": EstadoDocumentacion.PENDIENTE.value,
            "error_ultimo": None,
        },
    )

    return {
        "mensaje": "Generación de documentación encolada correctamente",
        "id_repositorio": id_repositorio,
        "tarea": tarea,
        "estado_documentacion": EstadoDocumentacion.PENDIENTE.value,
        "siguiente_accion": "CONSULTAR_ESTADO",
    }


@router.get("/{id_repositorio}/ver")
def ver_documentacion(
    id_repositorio: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    obtener_proyecto_del_usuario(id_repositorio, usuario)

    contenido = obtener_documentacion_markdown(id_repositorio)

    return {
        "mensaje": "Documentación obtenida correctamente",
        "id_repositorio": id_repositorio,
        "documentacion": contenido,
    }


@router.get("/{id_repositorio}/markdown")
def descargar_markdown(
    id_repositorio: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    obtener_proyecto_del_usuario(id_repositorio, usuario)

    ruta_markdown = obtener_ruta_markdown_documentacion(id_repositorio)

    if not ruta_markdown.is_file():
        raise HTTPException(
            status_code=404,
            detail="El documento Markdown no existe",
        )

    return FileResponse(
        str(ruta_markdown),
        media_type="text/markdown",
        filename=NOMBRE_DOCUMENTACION_MARKDOWN,
    )


@router.get("/{id_repositorio}/word")
def descargar_word(
    id_repositorio: str,
    usuario: UsuarioAutenticado = Depends(obtener_usuario_actual),
):
    obtener_proyecto_del_usuario(id_repositorio, usuario)

    ruta_word = obtener_ruta_word_documentacion(id_repositorio)

    if not ruta_word.is_file():
        raise HTTPException(
            status_code=404,
            detail="El documento Word no existe",
        )

    return FileResponse(
        str(ruta_word),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=NOMBRE_DOCUMENTACION_WORD,
    )