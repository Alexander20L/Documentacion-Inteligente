from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import json

from configuracion.gemini_cliente import cliente_gemini
from configuracion.rutas_repositorios import resolver_ruta_graphify_out
from utils.generador_word import generar_word
from configuracion.url_base import construir_url_publica

router = APIRouter(prefix="/documentacion", tags=["Documentación"])


@router.post("/{id_repositorio}/generar")
def generar_documentacion(id_repositorio: str):
    carpeta_graphify = resolver_ruta_graphify_out(id_repositorio)

    ruta_graph_json = carpeta_graphify / "graph.json"
    ruta_reporte = carpeta_graphify / "GRAPH_REPORT.md"

    if not ruta_graph_json.exists():
        raise HTTPException(
            status_code=404,
            detail="No se encontró graph.json"
        )

    if not ruta_reporte.exists():
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

        ruta_markdown = carpeta_graphify / "DOCUMENTACION_TECNICA.md"

        with open(ruta_markdown, "w", encoding="utf-8") as archivo_salida:
            archivo_salida.write(documentacion)

        ruta_word = carpeta_graphify / "DOCUMENTACION_TECNICA.docx"

        generar_word(documentacion, str(ruta_word))

        return {
            "mensaje": "Documentación generada correctamente",
            "id_repositorio": id_repositorio,
            "documentacion": documentacion,
            "url_word": construir_url_publica(f"documentacion/{id_repositorio}/word")
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@router.get("/{id_repositorio}/ver")
def ver_documentacion(id_repositorio: str):
    ruta_documentacion = resolver_ruta_graphify_out(id_repositorio) / "DOCUMENTACION_TECNICA.md"

    if not ruta_documentacion.exists():
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
    ruta_word = resolver_ruta_graphify_out(id_repositorio) / "DOCUMENTACION_TECNICA.docx"

    if not ruta_word.exists():
        raise HTTPException(
            status_code=404,
            detail="El documento Word no existe"
        )

    return FileResponse(
        str(ruta_word),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="DOCUMENTACION_TECNICA.docx"
    )
