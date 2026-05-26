from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

import os
import shutil
import zipfile
import subprocess
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from configuracion.rutas_repositorios import (
    BASE_DIR,
    REPOS_DIR,
    obtener_ruta_repositorio,
    obtener_ruta_codigo_repositorio,
    iterar_candidatos_graphify_out,
    resolver_ruta_graphify_out,
)
from configuracion.supabase_cliente import supabase
from configuracion.url_base import construir_url_publica


router = APIRouter(prefix="/repositorios", tags=["Repositorios"])

UPLOADS_DIR = BASE_DIR / "uploads"
ARCHIVOS_GRAPHIFY = {
    "json": "graph.json",
    "manifest": "manifest.json",
    "analysis": ".graphify_analysis.json",
    "html": "graph.html",
    "reporte": "GRAPH_REPORT.md",
}
MAX_NODES_GRAPH_HTML = 5000

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(REPOS_DIR, exist_ok=True)


def ejecutar_comando(comando: list[str], cwd: Path, descripcion: str):
    env = os.environ.copy()

    rutas_venv = [
        str(ruta)
        for ruta in (BASE_DIR / ".venv" / "Scripts", BASE_DIR / ".venv" / "bin")
        if ruta.exists()
    ]

    if rutas_venv:
        env["PATH"] = os.pathsep.join(rutas_venv + [env.get("PATH", "")])

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


def obtener_graphify_bin() -> Path | None:
    ruta_env = os.getenv("GRAPHIFY_BIN")
    candidatos = []

    if ruta_env:
        candidatos.append(Path(ruta_env))

    candidatos.extend(
        [
            BASE_DIR / ".venv" / "Scripts" / "graphify.exe",
            BASE_DIR / ".venv" / "bin" / "graphify",
        ]
    )

    for candidato in candidatos:
        if candidato.exists():
            return candidato

    ruta_path = shutil.which("graphify")
    return Path(ruta_path) if ruta_path else None


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


def buscar_ruta_graphify_out(
    ruta_repositorio: Path,
    ruta_analisis: Path,
) -> Path | None:
    for candidato in iterar_candidatos_graphify_out(ruta_repositorio, ruta_analisis):
        if candidato.is_dir():
            return candidato

    return None


def construir_estado_archivos_graphify(
    ruta_base_publica: str,
    ruta_graphify_out: Path | None,
    mensajes: dict[str, str] | None = None,
) -> dict[str, Any]:
    archivos: dict[str, str | None] = {}
    disponibles: dict[str, bool] = {}
    mensajes = dict(mensajes or {})

    for clave, nombre_archivo in ARCHIVOS_GRAPHIFY.items():
        disponible = bool(
            ruta_graphify_out
            and (ruta_graphify_out / nombre_archivo).is_file()
        )
        disponibles[clave] = disponible
        archivos[clave] = (
            construir_url_publica(f"{ruta_base_publica}/{nombre_archivo}")
            if disponible
            else None
        )

    if not disponibles["html"]:
        mensajes.setdefault(
            "html",
            "El grafo HTML no está disponible para este análisis.",
        )

    if not disponibles["reporte"]:
        mensajes.setdefault(
            "reporte",
            "El reporte Markdown no está disponible para este análisis.",
        )

    return {
        "archivos": archivos,
        "disponibles": disponibles,
        "mensajes": mensajes,
    }


def grafo_permite_html(ruta_graphify_out: Path) -> bool:
    ruta_graph_json = ruta_graphify_out / ARCHIVOS_GRAPHIFY["json"]

    with open(ruta_graph_json, "r", encoding="utf-8") as archivo:
        graph = json.load(archivo)

    return len(graph.get("nodes", [])) <= MAX_NODES_GRAPH_HTML


def asegurar_outputs_graphify(ruta_graphify_out: Path) -> dict[str, str]:
    ruta_graph_json = ruta_graphify_out / ARCHIVOS_GRAPHIFY["json"]
    ruta_reporte = ruta_graphify_out / ARCHIVOS_GRAPHIFY["reporte"]
    ruta_html = ruta_graphify_out / ARCHIVOS_GRAPHIFY["html"]
    mensajes: dict[str, str] = {}

    if not ruta_graph_json.exists():
        raise HTTPException(
            status_code=500,
            detail="Graphify terminó, pero no generó graphify-out/graph.json",
        )

    if not ruta_reporte.exists():
        generar_graph_report_md(ruta_graphify_out)

        if not ruta_reporte.exists():
            mensajes["reporte"] = "No se pudo generar el reporte Markdown del análisis."

    if not ruta_html.exists():
        if grafo_permite_html(ruta_graphify_out):
            generar_graph_html(ruta_graphify_out)

            if not ruta_html.exists():
                mensajes["html"] = "No se pudo generar el grafo HTML del análisis."
        else:
            mensajes["html"] = (
                "El grafo es demasiado grande para generar una visualización HTML. "
                "Puedes revisar el JSON y el reporte Markdown."
            )

    return mensajes


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
    ruta_repositorio = obtener_ruta_repositorio(id_repositorio)
    ruta_analisis = obtener_ruta_codigo_repositorio(id_repositorio)

    try:
        if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            raise HTTPException(
                status_code=500,
                detail="Falta configurar GEMINI_API_KEY o GOOGLE_API_KEY en el .env del backend"
            )

        graphify_bin = obtener_graphify_bin()

        if graphify_bin is None:
            raise HTTPException(
                status_code=500,
                detail="No se encontró Graphify. Configura GRAPHIFY_BIN o instala la CLI en el entorno del backend."
            )

        shutil.rmtree(ruta_analisis / ".git", ignore_errors=True)

        for candidato in iterar_candidatos_graphify_out(ruta_repositorio, ruta_analisis):
            shutil.rmtree(candidato, ignore_errors=True)

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
                str(graphify_bin),
                "extract",
                ".",
                "--force"
            ],
            cwd=ruta_analisis,
            descripcion="Ejecución de Graphify"
        )

        ruta_graphify_out = buscar_ruta_graphify_out(ruta_repositorio, ruta_analisis)

        if ruta_graphify_out is None:
            raise HTTPException(
                status_code=500,
                detail="Graphify terminó, pero no generó la carpeta graphify-out"
            )

        estado_archivos = construir_estado_archivos_graphify(
            f"repositorios/{id_repositorio}",
            ruta_graphify_out,
            asegurar_outputs_graphify(ruta_graphify_out),
        )

        supabase.table("proyectos").insert({
            "usuario_id": usuario_id,
            "id_repositorio": id_repositorio,
            "nombre_archivo": nombre_archivo,
            "url_graph_html": estado_archivos["archivos"]["html"],
            "url_graph_json": estado_archivos["archivos"]["json"],
            "url_reporte": estado_archivos["archivos"]["reporte"],
            "estado": "analizado"
        }).execute()

        return {
            "mensaje": "Repositorio analizado correctamente con Graphify",
            "id_repositorio": id_repositorio,
            "salida": resultado.stdout,
            **estado_archivos,
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

    proyectos = []

    for proyecto in resultado.data:
        proyecto_normalizado = dict(proyecto)
        ruta_word = None

        try:
            ruta_graphify_out = resolver_ruta_graphify_out(proyecto_normalizado["id_repositorio"])
            candidato_word = ruta_graphify_out / "DOCUMENTACION_TECNICA.docx"
            ruta_word = candidato_word if candidato_word.is_file() else None
        except HTTPException:
            ruta_graphify_out = None

        estado_archivos = construir_estado_archivos_graphify(
            f"repositorios/{proyecto_normalizado['id_repositorio']}",
            ruta_graphify_out,
        )

        proyecto_normalizado.update(estado_archivos)
        proyecto_normalizado["url_graph_html"] = estado_archivos["archivos"]["html"]
        proyecto_normalizado["url_graph_json"] = estado_archivos["archivos"]["json"]
        proyecto_normalizado["url_reporte"] = estado_archivos["archivos"]["reporte"]
        proyecto_normalizado["url_word"] = (
            construir_url_publica(
                f"documentacion/{proyecto_normalizado['id_repositorio']}/word"
            )
            if ruta_word is not None
            else None
        )
        proyectos.append(proyecto_normalizado)

    return {
        "mensaje": "Historial obtenido correctamente",
        "proyectos": proyectos
    }


@router.get("/{id_repositorio}/{nombre_archivo}")
def obtener_archivo_graphify(id_repositorio: str, nombre_archivo: str):
    archivos_permitidos = set(ARCHIVOS_GRAPHIFY.values())

    if nombre_archivo not in archivos_permitidos:
        raise HTTPException(
            status_code=400,
            detail="Archivo no permitido"
        )

    ruta_graphify_out = resolver_ruta_graphify_out(id_repositorio)
    ruta_archivo = ruta_graphify_out / nombre_archivo

    if not ruta_archivo.exists():
        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado"
        )

    return FileResponse(str(ruta_archivo))
