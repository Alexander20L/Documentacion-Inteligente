from fastapi import APIRouter, HTTPException
import subprocess
import os

router = APIRouter(
    prefix="/analisis-graphify",
    tags=["Graphify"]
)

RUTA_BACKEND = os.getcwd()


@router.post("/analizar")
def analizar_proyecto():
    try:
        resultado = subprocess.run(
            ["graphify", "update", "."],
            cwd=RUTA_BACKEND,
            capture_output=True,
            text=True,
            shell=True
        )

        if resultado.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=resultado.stderr
            )

        return {
            "mensaje": "Análisis con Graphify ejecutado correctamente",
            "salida": resultado.stdout,
            "archivos": {
                "html": "http://127.0.0.1:8000/graphify/graph.html",
                "json": "http://127.0.0.1:8000/graphify/graph.json",
                "reporte": "http://127.0.0.1:8000/graphify/GRAPH_REPORT.md"
            }
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )