import json
import logging
import os
from pathlib import Path
from typing import Any

import pypandoc
from fastapi import HTTPException

from configuracion.gemini_cliente import cliente_gemini
from configuracion.rutas_repositorios import resolver_ruta_graphify_out
from configuracion.url_base import construir_url_publica


logger = logging.getLogger(__name__)

NOMBRE_DOCUMENTACION_MARKDOWN = "DOCUMENTACION_TECNICA.md"
NOMBRE_DOCUMENTACION_WORD = "DOCUMENTACION_TECNICA.docx"

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

MAX_NODOS_PROMPT = int(os.getenv("MAX_NODOS_PROMPT", "120"))
MAX_RELACIONES_PROMPT = int(os.getenv("MAX_RELACIONES_PROMPT", "180"))


def obtener_ruta_markdown_documentacion(id_repositorio: str) -> Path:
    return resolver_ruta_graphify_out(id_repositorio) / NOMBRE_DOCUMENTACION_MARKDOWN


def obtener_ruta_word_documentacion(id_repositorio: str) -> Path:
    return resolver_ruta_graphify_out(id_repositorio) / NOMBRE_DOCUMENTACION_WORD


def leer_archivo_texto(ruta: Path, mensaje_error: str) -> str:
    if not ruta.is_file():
        raise HTTPException(
            status_code=404,
            detail=mensaje_error,
        )

    return ruta.read_text(encoding="utf-8")


def cargar_graph_json(ruta_graph_json: Path) -> dict[str, Any]:
    if not ruta_graph_json.is_file():
        raise HTTPException(
            status_code=404,
            detail="No se encontró graph.json",
        )

    try:
        with open(ruta_graph_json, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=500,
            detail="graph.json existe, pero no tiene formato JSON válido",
        ) from error


def obtener_nodos_y_relaciones(graph_json: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    nodos = graph_json.get("nodes", [])
    relaciones = graph_json.get("links", graph_json.get("edges", []))

    if not isinstance(nodos, list):
        nodos = []

    if not isinstance(relaciones, list):
        relaciones = []

    return nodos, relaciones


def resumir_graph_json_para_prompt(graph_json: dict[str, Any]) -> dict[str, Any]:
    """
    Evita enviar todo graph.json a Gemini cuando el repositorio es grande.
    El LLM recibe una versión útil y controlada del grafo.
    """
    nodos, relaciones = obtener_nodos_y_relaciones(graph_json)

    tipos_nodos: dict[str, int] = {}
    comunidades: dict[str, int] = {}

    for nodo in nodos:
        tipo = nodo.get("type") or nodo.get("kind") or "Sin tipo"
        tipos_nodos[tipo] = tipos_nodos.get(tipo, 0) + 1

        comunidad = nodo.get("community") or nodo.get("group")
        if comunidad is not None:
            clave_comunidad = str(comunidad)
            comunidades[clave_comunidad] = comunidades.get(clave_comunidad, 0) + 1

    muestra_nodos = []
    for nodo in nodos[:MAX_NODOS_PROMPT]:
        muestra_nodos.append(
            {
                "id": nodo.get("id"),
                "name": nodo.get("name"),
                "label": nodo.get("label"),
                "type": nodo.get("type") or nodo.get("kind"),
                "path": nodo.get("path"),
                "community": nodo.get("community") or nodo.get("group"),
            }
        )

    muestra_relaciones = []
    for relacion in relaciones[:MAX_RELACIONES_PROMPT]:
        muestra_relaciones.append(
            {
                "source": relacion.get("source")
                or relacion.get("from")
                or relacion.get("start")
                or relacion.get("source_id"),
                "target": relacion.get("target")
                or relacion.get("to")
                or relacion.get("end")
                or relacion.get("target_id"),
                "type": relacion.get("type")
                or relacion.get("label")
                or relacion.get("relation"),
            }
        )

    return {
        "total_nodos": len(nodos),
        "total_relaciones": len(relaciones),
        "tipos_nodos": tipos_nodos,
        "comunidades_detectadas": comunidades,
        "muestra_nodos": muestra_nodos,
        "muestra_relaciones": muestra_relaciones,
    }


def construir_prompt_documentacion(
    reporte_md: str,
    graph_json_resumido: dict[str, Any],
) -> str:
    return f"""
Eres un especialista en documentación técnica de software.

A partir de la información estructural extraída por Graphify, genera una documentación técnica clara, profesional y útil para desarrolladores.

Reglas obligatorias:
- Usa únicamente la información proporcionada.
- No inventes tecnologías, módulos, endpoints, clases, funciones ni reglas de negocio que no estén presentes en los datos.
- Si algo no se puede determinar con certeza, indícalo como limitación.
- Escribe en español.
- Usa Markdown limpio.
- Mantén un tono técnico, claro y ordenado.

Estructura obligatoria:

# Documentación técnica del proyecto

## 1. Resumen general
Describe el propósito técnico general del proyecto según la información disponible.

## 2. Estructura del sistema
Explica carpetas, archivos o módulos principales identificados.

## 3. Componentes principales
Lista y explica los componentes, clases, funciones o módulos más relevantes.

## 4. Dependencias y relaciones internas
Describe relaciones entre archivos, módulos o funciones según el grafo.

## 5. Flujo técnico general
Explica cómo parecen interactuar las partes principales del sistema.

## 6. Consideraciones técnicas
Incluye observaciones útiles para futuros desarrolladores.

## 7. Limitaciones del análisis
Aclara qué aspectos no pueden determinarse con certeza a partir de la información disponible.

Información del reporte Graphify:
{reporte_md}

Información estructural resumida de graph.json:
{json.dumps(graph_json_resumido, ensure_ascii=False, indent=2)}
""".strip()


def generar_markdown_con_gemini(prompt: str) -> str:
    try:
        respuesta = cliente_gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
    except Exception as error:
        logger.exception("Error al generar documentación con Gemini")
        raise HTTPException(
            status_code=502,
            detail="No se pudo generar la documentación con Gemini",
        ) from error

    documentacion = getattr(respuesta, "text", None)

    if not documentacion or not documentacion.strip():
        raise HTTPException(
            status_code=502,
            detail="Gemini no devolvió contenido de documentación",
        )

    return documentacion.strip()

def generar_docx_desde_markdown(ruta_markdown: Path, ruta_word: Path) -> None:
    if not ruta_markdown.is_file():
        raise HTTPException(
            status_code=404,
            detail="No se encontró el archivo Markdown para generar el Word",
        )

    try:
        ruta_word.parent.mkdir(parents=True, exist_ok=True)

        if ruta_word.exists():
            ruta_word.unlink()

        pypandoc.convert_file(
            source_file=str(ruta_markdown),
            to="docx",
            outputfile=str(ruta_word),
            extra_args=[
                "--standalone",
                "--metadata=title:Documentación técnica del proyecto",
            ],
        )
    except Exception as error:
        logger.exception("Error al convertir Markdown a Word con Pandoc")
        raise HTTPException(
            status_code=500,
            detail="No se pudo convertir la documentación Markdown a Word",
        ) from error

    if not ruta_word.is_file():
        raise HTTPException(
            status_code=500,
            detail="Pandoc no generó el archivo Word",
        )

def generar_documentacion_tecnica(id_repositorio: str) -> dict[str, str]:
    carpeta_graphify = resolver_ruta_graphify_out(id_repositorio)

    ruta_graph_json = carpeta_graphify / "graph.json"
    ruta_reporte = carpeta_graphify / "GRAPH_REPORT.md"
    ruta_markdown = carpeta_graphify / NOMBRE_DOCUMENTACION_MARKDOWN
    ruta_word = carpeta_graphify / NOMBRE_DOCUMENTACION_WORD

    graph_json = cargar_graph_json(ruta_graph_json)
    reporte_md = leer_archivo_texto(
        ruta_reporte,
        "No se encontró GRAPH_REPORT.md",
    )

    graph_json_resumido = resumir_graph_json_para_prompt(graph_json)
    prompt = construir_prompt_documentacion(reporte_md, graph_json_resumido)

    documentacion = generar_markdown_con_gemini(prompt)

    ruta_markdown.write_text(documentacion, encoding="utf-8")
    generar_docx_desde_markdown(ruta_markdown, ruta_word)

    return {
        "mensaje": "Documentación generada correctamente",
        "id_repositorio": id_repositorio,
        "documentacion": documentacion,
        "url_markdown": construir_url_publica(
            f"documentacion/{id_repositorio}/markdown"
        ),
        "url_word": construir_url_publica(
            f"documentacion/{id_repositorio}/word"
        ),
    }


def obtener_documentacion_markdown(id_repositorio: str) -> str:
    ruta_documentacion = obtener_ruta_markdown_documentacion(id_repositorio)

    return leer_archivo_texto(
        ruta_documentacion,
        "La documentación todavía no ha sido generada",
    )