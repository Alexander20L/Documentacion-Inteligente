from fastapi import APIRouter, HTTPException
from pathlib import Path

from routers.repositorios import (
    asegurar_outputs_graphify,
    construir_estado_archivos_graphify,
    ejecutar_comando,
    obtener_graphify_bin,
)

router = APIRouter(prefix="/analisis-graphify", tags=["Graphify"])

RUTA_BACKEND = Path(__file__).resolve().parent.parent
RUTA_GRAPHIFY_OUT = RUTA_BACKEND / "graphify-out"


@router.post("/analizar")
def analizar_proyecto():
    try:
        graphify_bin = obtener_graphify_bin()

        if graphify_bin is None:
            raise HTTPException(
                status_code=500,
                detail="No se encontró Graphify. Configura GRAPHIFY_BIN o instala la CLI en el entorno del backend.",
            )

        resultado = ejecutar_comando(
            [str(graphify_bin), "update", "."],
            cwd=RUTA_BACKEND,
            descripcion="Actualización de Graphify",
        )

        if not (RUTA_GRAPHIFY_OUT / "graph.json").exists():
            raise HTTPException(
                status_code=500,
                detail="Graphify terminó, pero no generó graphify-out/graph.json",
            )

        estado_archivos = construir_estado_archivos_graphify(
            "graphify",
            RUTA_GRAPHIFY_OUT,
            asegurar_outputs_graphify(RUTA_GRAPHIFY_OUT),
        )

        return {
            "mensaje": "Análisis con Graphify ejecutado correctamente",
            "salida": resultado.stdout,
            **estado_archivos,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
