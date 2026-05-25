from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
import json

from configuracion.gemini_cliente import cliente_gemini
from utils.generador_word import generar_word

router = APIRouter(
    prefix="/documentacion",
    tags=["Documentación"]
)

BASE_DIR = os.getcwd()
REPOS_DIR = os.path.join(BASE_DIR, "repos")


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


@router.post("/{id_repositorio}/generar")
def generar_documentacion(id_repositorio: str):
    ruta_base = obtener_ruta_base_repositorio(id_repositorio)

    carpeta_graphify = os.path.join(ruta_base, "graphify-out")

    ruta_graph_json = os.path.join(carpeta_graphify, "graph.json")
    ruta_reporte = os.path.join(carpeta_graphify, "GRAPH_REPORT.md")

    if not os.path.exists(ruta_graph_json):
        raise HTTPException(
            status_code=404,
            detail="No se encontró graph.json"
        )

    if not os.path.exists(ruta_reporte):
        raise HTTPException(
            status_code=404,
            detail="No se encontró GRAPH_REPORT.md"
        )

    with open(ruta_graph_json, "r", encoding="utf-8") as archivo_json:
        graph_json = json.load(archivo_json)

    with open(ruta_reporte, "r", encoding="utf-8") as archivo_reporte:
        reporte_md = archivo_reporte.read()

    prompt = f"""
Eres un especialista en documentación técnica de software.

A partir de la información estructural extraída por Graphify, genera una documentación técnica clara, profesional y útil para desarrolladores.

Debes usar únicamente la información proporcionada. No inventes tecnologías, módulos, endpoints ni reglas de negocio que no estén presentes en los datos.

Estructura la documentación en Markdown con estas secciones:

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

Información estructural graph.json:
{json.dumps(graph_json, ensure_ascii=False)}
"""

    try:
        respuesta = cliente_gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        documentacion = respuesta.text

        ruta_markdown = os.path.join(
            carpeta_graphify,
            "DOCUMENTACION_TECNICA.md"
        )

        with open(ruta_markdown, "w", encoding="utf-8") as archivo_salida:
            archivo_salida.write(documentacion)

        ruta_word = os.path.join(
            carpeta_graphify,
            "DOCUMENTACION_TECNICA.docx"
        )

        generar_word(documentacion, ruta_word)

        return {
            "mensaje": "Documentación generada correctamente",
            "id_repositorio": id_repositorio,
            "documentacion": documentacion,
            "url_word": f"http://127.0.0.1:8000/documentacion/{id_repositorio}/word"
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@router.get("/{id_repositorio}/ver")
def ver_documentacion(id_repositorio: str):
    ruta_base = obtener_ruta_base_repositorio(id_repositorio)

    ruta_documentacion = os.path.join(
        ruta_base,
        "graphify-out",
        "DOCUMENTACION_TECNICA.md"
    )

    if not os.path.exists(ruta_documentacion):
        raise HTTPException(
            status_code=404,
            detail="La documentación todavía no ha sido generada"
        )

    with open(ruta_documentacion, "r", encoding="utf-8") as archivo:
        contenido = archivo.read()

    return {
        "mensaje": "Documentación obtenida correctamente",
        "id_repositorio": id_repositorio,
        "documentacion": contenido
    }


@router.get("/{id_repositorio}/word")
def descargar_word(id_repositorio: str):
    ruta_base = obtener_ruta_base_repositorio(id_repositorio)

    ruta_word = os.path.join(
        ruta_base,
        "graphify-out",
        "DOCUMENTACION_TECNICA.docx"
    )

    if not os.path.exists(ruta_word):
        raise HTTPException(
            status_code=404,
            detail="El documento Word no existe"
        )

    return FileResponse(
        ruta_word,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="DOCUMENTACION_TECNICA.docx"
    )