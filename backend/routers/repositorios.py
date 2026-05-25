from fastapi import APIRouter, UploadFile, File, HTTPException
import os
import shutil
import zipfile
from uuid import uuid4
import subprocess
from fastapi.responses import FileResponse
from configuracion.supabase_cliente import supabase

router = APIRouter(
    prefix="/repositorios",
    tags=["Repositorios"]
)

BASE_DIR = os.getcwd()
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
REPOS_DIR = os.path.join(BASE_DIR, "repos")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(REPOS_DIR, exist_ok=True)


def obtener_ruta_base_repositorio(id_repositorio: str):
    ruta_repositorio = os.path.join(REPOS_DIR, id_repositorio)

    if not os.path.exists(ruta_repositorio):
        raise HTTPException(
            status_code=404,
            detail="El repositorio no existe"
        )

    elementos = os.listdir(ruta_repositorio)

    carpetas = [
        elemento for elemento in elementos
        if os.path.isdir(os.path.join(ruta_repositorio, elemento))
        and elemento != "graphify-out"
    ]

    if len(carpetas) == 1:
        return os.path.join(ruta_repositorio, carpetas[0])

    return ruta_repositorio


@router.get("/")
def listar_repositorios():
    return {"mensaje": "Ruta repositorios funcionando"}


@router.post("/subir")
async def subir_repositorio(archivo: UploadFile = File(...)):
    if not archivo.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Solo se permiten archivos .zip"
        )

    id_repositorio = str(uuid4())

    nombre_zip = f"{id_repositorio}.zip"
    ruta_zip = os.path.join(UPLOADS_DIR, nombre_zip)
    ruta_destino = os.path.join(REPOS_DIR, id_repositorio)

    with open(ruta_zip, "wb") as buffer:
        shutil.copyfileobj(archivo.file, buffer)

    os.makedirs(ruta_destino, exist_ok=True)

    try:
        with zipfile.ZipFile(ruta_zip, "r") as zip_ref:
            zip_ref.extractall(ruta_destino)
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="El archivo ZIP no es válido"
        )

    return {
        "mensaje": "Repositorio subido y descomprimido correctamente",
        "id_repositorio": id_repositorio,
        "nombre_archivo": archivo.filename,
        "ruta": ruta_destino
    }


@router.post("/{id_repositorio}/analizar")
def analizar_repositorio(id_repositorio: str, usuario_id: str, nombre_archivo: str):
    ruta_analisis = obtener_ruta_base_repositorio(id_repositorio)

    try:
        resultado = subprocess.run(
            "graphify update .",
            cwd=ruta_analisis,
            capture_output=True,
            text=True,
            shell=True
        )

        if resultado.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=resultado.stderr
            )

        supabase.table("proyectos").insert({
            "usuario_id": usuario_id,
            "id_repositorio": id_repositorio,
            "nombre_archivo": nombre_archivo,
            "url_graph_html": f"http://127.0.0.1:8000/repositorios/{id_repositorio}/graph.html",
            "url_graph_json": f"http://127.0.0.1:8000/repositorios/{id_repositorio}/graph.json",
            "url_reporte": f"http://127.0.0.1:8000/repositorios/{id_repositorio}/GRAPH_REPORT.md",
            "estado": "analizado"
        }).execute()

        return {
            "mensaje": "Repositorio analizado correctamente con Graphify",
            "id_repositorio": id_repositorio,
            "salida": resultado.stdout,
            "archivos": {
                "html": f"http://127.0.0.1:8000/repositorios/{id_repositorio}/graph.html",
                "json": f"http://127.0.0.1:8000/repositorios/{id_repositorio}/graph.json",
                "reporte": f"http://127.0.0.1:8000/repositorios/{id_repositorio}/GRAPH_REPORT.md"
            }
        }

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
        "manifest.json"
    ]

    if nombre_archivo not in archivos_permitidos:
        raise HTTPException(
            status_code=400,
            detail="Archivo no permitido"
        )

    ruta_base = obtener_ruta_base_repositorio(id_repositorio)

    ruta_archivo = os.path.join(
        ruta_base,
        "graphify-out",
        nombre_archivo
    )

    if not os.path.exists(ruta_archivo):
        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado"
        )

    return FileResponse(ruta_archivo)