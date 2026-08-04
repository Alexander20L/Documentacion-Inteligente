import logging
import os
import signal
import socket
import threading
import time
from typing import Any

import httpx

from fastapi import HTTPException

from servicios.c4_pipeline import (
    ejecutar_analisis_c4,
    ejecutar_publicacion_c4,
    preparar_resultado_revision_c4,
)
from configuracion.supabase_cliente import supabase_admin
from configuracion.rutas_c4 import (
    C4_ANALYSIS_ATTEMPTS_DIR,
    C4_PUBLICATION_ATTEMPTS_DIR,
    obtener_raiz_intento_analisis,
    obtener_raiz_intento_publicacion,
)
from servicios.servicio_almacenamiento import eliminar_directorio_seguro
from servicios.tareas import (
    completar_analisis_c4_rpc,
    completar_publicacion_c4_rpc,
    fallar_tarea_c4_rpc,
    reclamar_tarea_rpc,
)


logger = logging.getLogger("documentacion.worker")

logging.basicConfig(
    level=os.getenv("WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

RUNNING = True
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
LEASE_SECONDS = int(os.getenv("WORKER_LEASE_SECONDS", "1800"))
WORKER_ID = os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"


def detener_worker(_signal_number, _frame) -> None:
    global RUNNING
    RUNNING = False


def obtener_detalle_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        return str(error.detail)

    return str(error)


def _heartbeat_rpc_reintentable(func, tarea_id: str, intento: int, sleep=time.sleep):
    """Renovar el lease tolerando caídas transitorias del transporte hacia Supabase.

    "Server disconnected" de httpx es una interrupción transitoria de la conexión
    reutilizada; reintentarlo impide que una única caída derribe toda la ejecución.
    """
    attempts = max(1, int(os.getenv("WORKER_HEARTBEAT_RETRY_ATTEMPTS", "3")))
    base_seconds = max(0.1, float(os.getenv("WORKER_HEARTBEAT_RETRY_BASE_SECONDS", "1")))
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except httpx.TransportError as error:
            if attempt == attempts:
                raise
            logger.warning(
                "Heartbeat transitorio (%s) para la tarea %s intento %s; reintentando en %.1fs",
                type(error).__name__,
                tarea_id,
                intento,
                base_seconds * attempt,
            )
            sleep(base_seconds * attempt)
    raise RuntimeError(f"El heartbeat de la tarea {tarea_id} falló tras {attempts} reintentos")


def procesar_tarea(tarea: dict[str, Any]) -> None:
    tarea_id = tarea["id"]
    tipo = tarea["tipo"]
    id_repositorio = tarea["id_repositorio"]
    intento = int(tarea["intentos"])

    propietario = (
        supabase_admin.table("proyectos").select("usuario_id")
        .eq("id_repositorio", id_repositorio).eq("usuario_id", tarea.get("usuario_id"))
        .limit(1).execute()
    )
    if not propietario.data:
        detalle = "La tarea no pertenece al propietario actual del proyecto"
        fallar_tarea_c4_rpc(tarea_id, WORKER_ID, intento, detalle)
        return

    estado_lock = threading.Lock()
    heartbeat_detallado_disponible = True

    def enviar_heartbeat() -> None:
        nonlocal heartbeat_detallado_disponible
        with estado_lock:
            fila = dict(estado_lease)
        parametros_base = {
            "p_tarea_id": tarea_id,
            "p_lease_owner": WORKER_ID,
            "p_intento": intento,
            "p_lease_seconds": LEASE_SECONDS,
            "p_progreso": fila["progreso"],
            "p_fase": fila["fase"],
        }
        if heartbeat_detallado_disponible:
            try:
                resultado = _heartbeat_rpc_reintentable(
                    lambda: supabase_admin.rpc("heartbeat_tarea_proyecto", {
                        **parametros_base,
                        "p_paso": fila["paso"],
                        "p_mensaje": fila["mensaje"],
                        "p_unidades_completadas": fila["unidades_completadas"],
                        "p_unidades_totales": fila["unidades_totales"],
                    }).execute(),
                    tarea_id,
                    intento,
                )
            except Exception as error:
                if getattr(error, "code", None) != "PGRST202":
                    raise
                heartbeat_detallado_disponible = False
                logger.info(
                    "Heartbeat detallado no disponible; usando el contrato anterior para la tarea %s",
                    tarea_id,
                )
                resultado = _heartbeat_rpc_reintentable(
                    lambda: supabase_admin.rpc("heartbeat_tarea_proyecto", parametros_base).execute(),
                    tarea_id,
                    intento,
                )
        else:
            resultado = _heartbeat_rpc_reintentable(
                lambda: supabase_admin.rpc("heartbeat_tarea_proyecto", parametros_base).execute(),
                tarea_id,
                intento,
            )
        if not resultado.data:
            raise RuntimeError("El heartbeat no devolvió la tarea")

    def heartbeat(
        progreso: int,
        fase: str,
        paso: str | None = None,
        mensaje: str | None = None,
        unidades_completadas: int | None = None,
        unidades_totales: int | None = None,
    ) -> None:
        if errores_lease:
            raise RuntimeError("Se perdió el lease durante el procesamiento") from errores_lease[0]
        with estado_lock:
            cambios = {
                "progreso": progreso,
                "fase": fase,
            }
            # Lease-only checkpoints keep the last meaningful progress detail.
            if any(valor is not None for valor in (paso, mensaje, unidades_completadas, unidades_totales)):
                cambios.update({
                    "paso": paso,
                    "mensaje": mensaje,
                    "unidades_completadas": unidades_completadas,
                    "unidades_totales": unidades_totales,
                })
            estado_lease.update(cambios)
        try:
            enviar_heartbeat()
        except httpx.TransportError as error:
            logger.warning(
                "Heartbeat de progreso falló por transporte (%s) para la tarea %s; el lease se mantiene por el hilo de renovación",
                type(error).__name__,
                tarea_id,
            )

    estado_lease = {
        "progreso": int(tarea.get("progreso") or 0),
        "fase": tarea.get("fase") or "ingesta",
        "paso": tarea.get("paso"),
        "mensaje": tarea.get("mensaje"),
        "unidades_completadas": tarea.get("unidades_completadas"),
        "unidades_totales": tarea.get("unidades_totales"),
    }
    detener_heartbeat = threading.Event()
    errores_lease: list[Exception] = []

    def renovar_lease() -> None:
        intervalo_reintento = max(int(os.getenv("WORKER_LEASE_RENEW_FLOOR_SECONDS", "5")), LEASE_SECONDS // 3)
        while not detener_heartbeat.wait(intervalo_reintento):
            try:
                enviar_heartbeat()
            except httpx.TransportError as error:
                logger.warning(
                    "Renovación de lease transitoria (%s) para la tarea %s; se reintentará en el siguiente ciclo",
                    type(error).__name__,
                    tarea_id,
                )
            except Exception as error:
                errores_lease.append(error)
                logger.exception("No se pudo renovar el lease de la tarea %s", tarea_id)
                return

    hilo_heartbeat = threading.Thread(target=renovar_lease, name=f"lease-{tarea_id}", daemon=True)
    hilo_heartbeat.start()

    try:
        resultado_publicacion = None
        if tipo == "analisis_c4":
            ejecutar_analisis_c4(tarea, heartbeat)

        elif tipo == "publicacion_c4":
            resultado_publicacion = ejecutar_publicacion_c4(tarea, heartbeat)

        else:
            raise RuntimeError(f"Tipo de tarea no soportado: {tipo}")

        detener_heartbeat.set()
        hilo_heartbeat.join(timeout=2)
        if errores_lease:
            raise RuntimeError("Se perdió el lease durante el procesamiento") from errores_lease[0]
        id_ejecucion = tarea.get("ejecucion_c4_id")
        if not id_ejecucion:
            raise RuntimeError("La tarea C4 no referencia una ejecución")
        if tipo == "analisis_c4":
            completar_analisis_c4_rpc(
                tarea_id,
                WORKER_ID,
                intento,
                id_ejecucion,
                preparar_resultado_revision_c4(tarea),
            )
        else:
            completar_publicacion_c4_rpc(
                tarea_id,
                WORKER_ID,
                intento,
                id_ejecucion,
                resultado_publicacion or {},
            )
        logger.info("Tarea completada: tipo=%s repositorio=%s", tipo, id_repositorio)

    except Exception as error:
        detener_heartbeat.set()
        hilo_heartbeat.join(timeout=2)
        detalle = obtener_detalle_error(error)

        logger.exception(
            "Tarea fallida: tipo=%s repositorio=%s",
            tipo,
            id_repositorio,
        )

        try:
            if tipo == "analisis_c4":
                eliminar_directorio_seguro(
                    obtener_raiz_intento_analisis(str(tarea_id), intento),
                    C4_ANALYSIS_ATTEMPTS_DIR,
                )
            elif tipo == "publicacion_c4":
                eliminar_directorio_seguro(
                    obtener_raiz_intento_publicacion(str(tarea_id), intento),
                    C4_PUBLICATION_ATTEMPTS_DIR,
                )
        except Exception:
            logger.exception("No se pudo limpiar el espacio del intento fallido %s", tarea_id)

        try:
            fallar_tarea_c4_rpc(tarea_id, WORKER_ID, intento, detalle)
        except Exception:
            logger.warning(
                "La tarea %s perdió el lease; el intento actual se abandona sin mutar la ejecución",
                tarea_id,
            )


def main() -> None:
    signal.signal(signal.SIGINT, detener_worker)
    signal.signal(signal.SIGTERM, detener_worker)

    logger.info(
        "Worker iniciado. poll_interval=%ss lease=%ss worker_id=%s",
        POLL_INTERVAL,
        LEASE_SECONDS,
        WORKER_ID,
    )

    while RUNNING:
        tarea = reclamar_tarea_rpc(WORKER_ID, LEASE_SECONDS)

        if not tarea:
            time.sleep(POLL_INTERVAL)
            continue
        procesar_tarea(tarea)

    logger.info("Worker detenido")


if __name__ == "__main__":
    main()
