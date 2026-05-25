from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

import os
import shutil
import zipfile
import subprocess
import json
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

def obtener_nodos_y_enlaces(graph: dict):
    nodos = graph.get("nodes", [])
    enlaces = graph.get("links", graph.get("edges", []))
    return nodos, enlaces


def generar_graph_html(ruta_graphify_out: Path):
    ruta_html = ruta_graphify_out / "graph.html"

    contenido_html = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Grafo Graphify</title>
    <script src="https://unpkg.com/force-graph"></script>
    <style>
        html, body {
            margin: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            font-family: Arial, sans-serif;
            background: #111827;
            color: #ffffff;
        }

        #cabecera {
            position: fixed;
            top: 16px;
            left: 16px;
            z-index: 10;
            background: rgba(17, 24, 39, 0.88);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 10px;
            padding: 12px 16px;
            max-width: 420px;
        }

        #cabecera h1 {
            margin: 0 0 4px 0;
            font-size: 16px;
        }

        #cabecera p {
            margin: 0;
            font-size: 13px;
            color: #d1d5db;
        }

        #graph {
            width: 100vw;
            height: 100vh;
        }

        #error {
            padding: 24px;
            color: #fecaca;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div id="cabecera">
        <h1>Grafo generado por Graphify</h1>
        <p>Visualización basada en graph.json</p>
    </div>

    <div id="graph"></div>

    <script>
        fetch("graph.json")
            .then(response => {
                if (!response.ok) {
                    throw new Error("No se pudo cargar graph.json. Código HTTP: " + response.status);
                }
                return response.json();
            })
            .then(data => {
                const nodes = data.nodes || [];
                const rawLinks = data.links || data.edges || [];

                const links = rawLinks
                    .map(edge => ({
                        ...edge,
                        source: edge.source || edge.from || edge.start || edge.source_id,
                        target: edge.target || edge.to || edge.end || edge.target_id
                    }))
                    .filter(edge => edge.source && edge.target);

                ForceGraph()(document.getElementById("graph"))
                    .graphData({
                        nodes: nodes,
                        links: links
                    })
                    .nodeId(node => node.id || node.name || node.label)
                    .nodeLabel(node => {
                        return node.name || node.label || node.id || "Nodo sin nombre";
                    })
                    .nodeAutoColorBy(node => node.community || node.group || node.type || "default")
                    .linkDirectionalParticles(1)
                    .linkDirectionalParticleSpeed(0.004)
                    .backgroundColor("#111827");
            })
            .catch(error => {
                document.body.innerHTML = "<div id='error'>Error cargando el grafo:\\n" + error + "</div>";
            });
    </script>
</body>
</html>
"""

    with open(ruta_html, "w", encoding="utf-8") as archivo:
        archivo.write(contenido_html)


def generar_graph_report_md(ruta_graphify_out: Path):
    ruta_graph_json = ruta_graphify_out / "graph.json"
    ruta_analysis_json = ruta_graphify_out / ".graphify_analysis.json"
    ruta_reporte = ruta_graphify_out / "GRAPH_REPORT.md"

    with open(ruta_graph_json, "r", encoding="utf-8") as archivo:
        graph = json.load(archivo)

    analysis = {}

    if ruta_analysis_json.exists():
        with open(ruta_analysis_json, "r", encoding="utf-8") as archivo:
            analysis = json.load(archivo)

    nodos, enlaces = obtener_nodos_y_enlaces(graph)

    tipos_nodos = {}
    comunidades = set()

    for nodo in nodos:
        tipo = nodo.get("type") or nodo.get("kind") or "Sin tipo"
        tipos_nodos[tipo] = tipos_nodos.get(tipo, 0) + 1

        comunidad = nodo.get("community") or nodo.get("group")
        if comunidad is not None:
            comunidades.add(str(comunidad))

    contenido = "# Reporte de análisis Graphify\n\n"

    contenido += "## 1. Resumen general\n\n"
    contenido += f"- Total de nodos: {len(nodos)}\n"
    contenido += f"- Total de relaciones: {len(enlaces)}\n"
    contenido += f"- Total de comunidades detectadas: {len(comunidades)}\n\n"

    contenido += "## 2. Tipos de nodos detectados\n\n"

    if tipos_nodos:
        for tipo, cantidad in sorted(tipos_nodos.items(), key=lambda item: item[1], reverse=True):
            contenido += f"- {tipo}: {cantidad}\n"
    else:
        contenido += "- No se detectaron tipos específicos de nodos.\n"

    contenido += "\n## 3. Muestra de nodos principales\n\n"

    if nodos:
        for nodo in nodos[:25]:
            nombre = nodo.get("name") or nodo.get("label") or nodo.get("id") or "Nodo sin nombre"
            tipo = nodo.get("type") or nodo.get("kind") or "Sin tipo"
            contenido += f"- **{nombre}** — {tipo}\n"
    else:
        contenido += "- No se encontraron nodos.\n"

    contenido += "\n## 4. Muestra de relaciones principales\n\n"

    if enlaces:
        for enlace in enlaces[:25]:
            origen = enlace.get("source") or enlace.get("from") or enlace.get("start") or enlace.get("source_id")
            destino = enlace.get("target") or enlace.get("to") or enlace.get("end") or enlace.get("target_id")
            tipo = enlace.get("type") or enlace.get("label") or enlace.get("relation") or "relacionado con"
            contenido += f"- `{origen}` -- {tipo} --> `{destino}`\n"
    else:
        contenido += "- No se encontraron relaciones.\n"

    contenido += "\n## 5. Información adicional del análisis\n\n"

    if analysis:
        contenido += "```json\n"
        contenido += json.dumps(analysis, ensure_ascii=False, indent=2)
        contenido += "\n```\n"
    else:
        contenido += "- No se encontró información adicional en .graphify_analysis.json.\n"

    contenido += "\n## 6. Archivos generados\n\n"
    contenido += "- graph.json\n"
    contenido += "- graph.html\n"
    contenido += "- GRAPH_REPORT.md\n"
    contenido += "- manifest.json\n"
    contenido += "- .graphify_analysis.json\n"

    with open(ruta_reporte, "w", encoding="utf-8") as archivo:
        archivo.write(contenido)

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