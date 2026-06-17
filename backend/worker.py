import logging
import os
import signal
import time
from typing import Any

from fastapi import HTTPException

from modelos.estados_proyecto import EstadoDocumentacion, EstadoProyecto
from servicios.servicio_documentacion import generar_documentacion_tecnica
from servicios.servicio_graphify import ejecutar_analisis_repositorio
from servicios.tareas import (
    actualizar_proyecto_admin,
    listar_tareas_pendientes,
    marcar_tarea_completada,
    marcar_tarea_fallida,
    reclamar_tarea_pendiente,
)


logger = logging.getLogger("documentacion.worker")

logging.basicConfig(
    level=os.getenv("WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

RUNNING = True
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "5"))


def detener_worker(_signal_number, _frame) -> None:
    global RUNNING
    RUNNING = False


def obtener_detalle_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        return str(error.detail)

    return str(error)


def actualizar_proyecto_en_error(id_repositorio: str, tipo: str, detalle: str) -> None:
    if tipo == "analisis":
        actualizar_proyecto_admin(
            id_repositorio,
            {
                "estado": EstadoProyecto.ERROR_ANALISIS.value,
                "error_ultimo": detalle,
            },
        )
        return

    if tipo == "documentacion":
        actualizar_proyecto_admin(
            id_repositorio,
            {
                "estado_documentacion": EstadoDocumentacion.ERROR_DOCUMENTACION.value,
                "error_ultimo": detalle,
            },
        )
        return

    actualizar_proyecto_admin(
        id_repositorio,
        {
            "error_ultimo": detalle,
        },
    )


def procesar_tarea_analisis(
    id_repositorio: str,
    payload: dict[str, Any],
) -> None:
    actualizar_proyecto_admin(
        id_repositorio,
        {
            "estado": EstadoProyecto.ANALIZANDO_GRAPHIFY.value,
            "estado_documentacion": EstadoDocumentacion.PENDIENTE.value,
            "error_ultimo": None,
        },
    )

    estado_archivos = ejecutar_analisis_repositorio(id_repositorio)

    cambios_proyecto = {
        "url_graph_html": estado_archivos["archivos"]["html"],
        "url_graph_json": estado_archivos["archivos"]["json"],
        "url_reporte": estado_archivos["archivos"]["reporte"],
        "estado": EstadoProyecto.GRAPHIFY_COMPLETADO.value,
        "estado_documentacion": EstadoDocumentacion.PENDIENTE.value,
        "error_ultimo": None,
    }

    if payload.get("nombre_archivo"):
        cambios_proyecto["nombre_archivo"] = payload["nombre_archivo"]

    actualizar_proyecto_admin(
        id_repositorio,
        cambios_proyecto,
    )


def procesar_tarea_documentacion(id_repositorio: str) -> None:
    actualizar_proyecto_admin(
        id_repositorio,
        {
            "estado_documentacion": EstadoDocumentacion.GENERANDO_DOCUMENTACION.value,
            "error_ultimo": None,
        },
    )

    generar_documentacion_tecnica(id_repositorio)

    actualizar_proyecto_admin(
        id_repositorio,
        {
            "estado_documentacion": EstadoDocumentacion.DOCUMENTACION_COMPLETADA.value,
            "error_ultimo": None,
        },
    )


def procesar_tarea(tarea: dict[str, Any]) -> None:
    tarea_id = tarea["id"]
    tipo = tarea["tipo"]
    id_repositorio = tarea["id_repositorio"]
    payload = tarea.get("payload") or {}

    try:
        if tipo == "analisis":
            procesar_tarea_analisis(id_repositorio, payload)

        elif tipo == "documentacion":
            procesar_tarea_documentacion(id_repositorio)

        else:
            raise RuntimeError(f"Tipo de tarea no soportado: {tipo}")

        marcar_tarea_completada(tarea_id)
        logger.info("Tarea completada: tipo=%s repositorio=%s", tipo, id_repositorio)

    except Exception as error:
        detalle = obtener_detalle_error(error)

        logger.exception(
            "Tarea fallida: tipo=%s repositorio=%s",
            tipo,
            id_repositorio,
        )

        marcar_tarea_fallida(tarea_id, detalle)
        actualizar_proyecto_en_error(id_repositorio, tipo, detalle)


def main() -> None:
    signal.signal(signal.SIGINT, detener_worker)
    signal.signal(signal.SIGTERM, detener_worker)

    logger.info(
        "Worker iniciado. poll_interval=%ss batch_size=%s",
        POLL_INTERVAL,
        BATCH_SIZE,
    )

    while RUNNING:
        tareas = listar_tareas_pendientes(BATCH_SIZE)

        if not tareas:
            time.sleep(POLL_INTERVAL)
            continue

        for tarea in tareas:
            if not RUNNING:
                break

            reclamada = reclamar_tarea_pendiente(tarea["id"])

            if reclamada is None:
                continue

            procesar_tarea(reclamada)

    logger.info("Worker detenido")


if __name__ == "__main__":
    main()