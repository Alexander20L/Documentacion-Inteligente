from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

import os
import shutil
import zipfile
import subprocess
from pathlib import Path
from uuid import uuid4

from configuracion.supabase_cliente import supabase
from configuracion.url_base import construir_url_publica


router = APIRouter(
    prefix="/repositorios",
    tags=["Repositorios"]
)

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
REPOS_DIR = BASE_DIR / "repos"

GRAPHIFY_BIN = BASE_DIR / ".venv" / "bin" / "graphify"

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(REPOS_DIR, exist_ok=True)


def ejecutar_comando(comando: list[str], cwd: Path, descripcion: str):
    env = os.environ.copy()
    env["PATH"] = f"{BASE_DIR / '.venv' / 'bin'}:{env.get('PATH', '')}"

    resultado = subprocess.run(
        comando,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env
    )

    if resultado.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{descripcion} falló:\n"
                f"STDOUT:\n{resultado.stdout}\n"
                f"STDERR:\n{resultado.stderr}"
            )
        )

    return resultado


def extraer_zip_seguro(ruta_zip: Path, ruta_destino: Path):
    destino_resuelto = ruta_destino.resolve()

    try:
        with zipfile.ZipFile(ruta_zip, "r") as zip_ref:
            for miembro in zip_ref.infolist():
                ruta_miembro = (destino_resuelto / miembro.filename).resolve()

                if not str(ruta_miembro).startswith(str(destino_resuelto)):
                    raise HTTPException(
                        status_code=400,
                        detail="El archivo ZIP contiene rutas no permitidas"
                    )

            zip_ref.extractall(destino_resuelto)

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="El archivo ZIP no es válido"
        )


def obtener_ruta_base_repositorio(id_repositorio: str) -> Path:
    ruta_repositorio = REPOS_DIR / id_repositorio

    if not ruta_repositorio.exists():
        raise HTTPException(
            status_code=404,
            detail="El repositorio no existe"
        )

    elementos = os.listdir(ruta_repositorio)

    carpetas = [
        elemento for elemento in elementos
        if (ruta_repositorio / elemento).is_dir()
        and elemento not in ["graphify-out", ".git"]
    ]

    if len(carpetas) == 1:
        return ruta_repositorio / carpetas[0]

    return ruta_repositorio


@router.get("/")
def listar_repositorios():
    return {"mensaje": "Ruta repositorios funcionando"}


@router.post("/subir")
async def subir_repositorio(archivo: UploadFile = File(...)):
    if not archivo.filename or not archivo.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Solo se permiten archivos .zip"
        )

    id_repositorio = str(uuid4())

    nombre_zip = f"{id_repositorio}.zip"
    ruta_zip = UPLOADS_DIR / nombre_zip
    ruta_destino = REPOS_DIR / id_repositorio

    with open(ruta_zip, "wb") as buffer:
        shutil.copyfileobj(archivo.file, buffer)

    os.makedirs(ruta_destino, exist_ok=True)

    extraer_zip_seguro(ruta_zip, ruta_destino)

    return {
        "mensaje": "Repositorio subido y descomprimido correctamente",
        "id_repositorio": id_repositorio,
        "nombre_archivo": archivo.filename,
        "ruta": str(ruta_destino)
    }


@router.post("/{id_repositorio}/analizar")
def analizar_repositorio(id_repositorio: str, usuario_id: str, nombre_archivo: str):
    ruta_analisis = obtener_ruta_base_repositorio(id_repositorio)

    try:
        if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            raise HTTPException(
                status_code=500,
                detail="Falta configurar GEMINI_API_KEY o GOOGLE_API_KEY en el .env del backend"
            )

        if not GRAPHIFY_BIN.exists():
            raise HTTPException(
                status_code=500,
                detail=f"No se encontró Graphify en: {GRAPHIFY_BIN}"
            )

        shutil.rmtree(ruta_analisis / ".git", ignore_errors=True)
        shutil.rmtree(ruta_analisis / "graphify-out", ignore_errors=True)

        ejecutar_comando(
            ["git", "init"],
            cwd=ruta_analisis,
            descripcion="Inicialización de Git"
        )

        ejecutar_comando(
            ["git", "add", "-A", "-f"],
            cwd=ruta_analisis,
            descripcion="Registro de archivos en Git"
        )

        resultado = ejecutar_comando(
            [
                str(GRAPHIFY_BIN),
                "extract",
                ".",
                "--force"
            ],
            cwd=ruta_analisis,
            descripcion="Ejecución de Graphify"
        )

        ruta_graph_json = ruta_analisis / "graphify-out" / "graph.json"

        if not ruta_graph_json.exists():
            raise HTTPException(
                status_code=500,
                detail="Graphify terminó, pero no generó graphify-out/graph.json"
            )

        supabase.table("proyectos").insert({
            "usuario_id": usuario_id,
            "id_repositorio": id_repositorio,
            "nombre_archivo": nombre_archivo,
            "url_graph_html": construir_url_publica(f"repositorios/{id_repositorio}/graph.html"),
            "url_graph_json": construir_url_publica(f"repositorios/{id_repositorio}/graph.json"),
            "url_reporte": construir_url_publica(f"repositorios/{id_repositorio}/GRAPH_REPORT.md"),
            "estado": "analizado"
        }).execute()

        return {
            "mensaje": "Repositorio analizado correctamente con Graphify",
            "id_repositorio": id_repositorio,
            "salida": resultado.stdout,
            "archivos": {
                "json": construir_url_publica(f"repositorios/{id_repositorio}/graph.json"),
                "manifest": construir_url_publica(f"repositorios/{id_repositorio}/manifest.json"),
                "analysis": construir_url_publica(f"repositorios/{id_repositorio}/.graphify_analysis.json"),
                "html": construir_url_publica(f"repositorios/{id_repositorio}/graph.html"),
                "reporte": construir_url_publica(f"repositorios/{id_repositorio}/GRAPH_REPORT.md")
            }
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@router.get("/historial")
def obtener_historial():
    resultado = (
        supabase.table("proyectos")
        .select("*")
        .order("creado_en", desc=True)
        .execute()
    )

    return {
        "mensaje": "Historial obtenido correctamente",
        "proyectos": resultado.data
    }


@router.get("/{id_repositorio}/{nombre_archivo}")
def obtener_archivo_graphify(id_repositorio: str, nombre_archivo: str):
    archivos_permitidos = [
        "graph.html",
        "graph.json",
        "GRAPH_REPORT.md",
        "manifest.json",
        ".graphify_analysis.json"
    ]

    if nombre_archivo not in archivos_permitidos:
        raise HTTPException(
            status_code=400,
            detail="Archivo no permitido"
        )

    ruta_base = obtener_ruta_base_repositorio(id_repositorio)

    ruta_archivo = ruta_base / "graphify-out" / nombre_archivo

    if not ruta_archivo.exists():
        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado"
        )

    return FileResponse(str(ruta_archivo))