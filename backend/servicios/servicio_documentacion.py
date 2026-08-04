import json
import logging
import os
import re
import shutil
import subprocess
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

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

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
Actúa como un arquitecto de software experto en documentación técnica, modelo C4 y análisis de arquitectura basado en código.

Vas a recibir información generada por Graphify sobre un proyecto de software. Esta información puede incluir estructura de carpetas, archivos, dependencias, nodos, aristas, comunidades, módulos detectados, reportes Markdown, JSON y HTML.

Tu tarea es generar documentación técnica clara, modular y mantenible siguiendo estas reglas:

REGLAS GENERALES

1. No inventes información.

   * Usa únicamente la información entregada por Graphify y los metadatos proporcionados.
   * Si algo no está explícito o no puede inferirse con seguridad, marca la sección como “Pendiente de confirmar”.
   * Diferencia claramente entre “Detectado” e “Inferido”.

2. Documenta como una guía del sistema.

   * La documentación debe servir para que un nuevo desarrollador entienda rápidamente el proyecto.
   * Evita texto genérico, repetitivo o decorativo.
   * Prioriza claridad, utilidad y trazabilidad.

3. Usa el enfoque C4.
   Organiza la arquitectura en niveles:

   * Nivel 1: Contexto del sistema.
   * Nivel 2: Contenedores principales, como frontend, backend, base de datos, APIs, servicios externos o procesos.
   * Nivel 3: Componentes internos por contenedor o módulo.
   * Nivel 4: Código relevante solo si aporta valor para entender una parte compleja.

4. Documenta por módulos.

   * Si el proyecto es grande, no generes una sola explicación general.
   * Divide la documentación por módulos, dominios funcionales, carpetas principales o comunidades detectadas por Graphify.
   * Cada módulo debe tener propósito, responsabilidades, archivos principales, dependencias y relaciones.

5. Cada elemento debe tener responsabilidad.

   * No listes archivos o clases sin explicar su función.
   * Para cada módulo, componente, servicio o archivo importante, explica brevemente qué responsabilidad cumple.

6. Cada relación debe tener propósito.

   * No describas relaciones solo como “A se conecta con B”.
   * Explica el motivo de la relación: consume, llama, importa, usa, persiste, consulta, expone, transforma, valida, renderiza, etc.

7. Incluye tecnologías reales.

   * Si Graphify o la estructura del proyecto permite detectar frameworks, lenguajes, librerías o plataformas, inclúyelos.
   * Ejemplos: Angular, React, FastAPI, Django, Flask, Spring Boot, Supabase, PostgreSQL, SQL Server, Docker, etc.
   * No asumas tecnologías no detectadas.

8. No mezcles niveles de abstracción.

   * No combines sistemas externos, módulos, clases, funciones y archivos pequeños en una misma explicación sin separar niveles.
   * Mantén orden jerárquico: sistema → contenedores → módulos/componentes → archivos/código.

9. Los diagramas deben reflejar la realidad del código.

   * Genera diagramas solo con elementos detectados o inferidos razonablemente.
   * No agregues servicios, bases de datos o APIs que no aparezcan en la información de entrada.
   * Si un diagrama puede ser incorrecto por falta de información, indícalo antes del diagrama.

10. La documentación debe ser mantenible.

* Usa Markdown limpio.
* Usa tablas solo cuando mejoren la lectura.
* Usa listas cortas y directas.
* Evita párrafos excesivamente largos.
* No generes documentación innecesariamente extensa.

ESTRUCTURA DE SALIDA REQUERIDA

Genera la documentación con esta estructura:

# Documentación técnica del proyecto

## 1. Resumen general

* Nombre del proyecto, si está disponible.
* Propósito general detectado o inferido.
* Tipo de sistema.
* Tecnologías principales detectadas.
* Nivel de confianza del análisis: Alto, Medio o Bajo.

## 2. Contexto del sistema

* Qué problema parece resolver el sistema.
* Usuarios o actores detectados, si existen.
* Sistemas externos detectados, si existen.
* Límites del sistema.

## 3. Vista C4 - Nivel 1: Contexto

Incluye explicación textual y un diagrama Mermaid válido si existe evidencia suficiente en Graphify. Si no existe evidencia suficiente, marca la sección como “Diagrama pendiente de confirmar por falta de evidencia suficiente en Graphify”.

## 4. Vista C4 - Nivel 2: Contenedores

Identifica los contenedores principales del sistema:

* Frontend.
* Backend.
* Base de datos.
* Servicios externos.
* Procesos batch.
* APIs.
* Otros contenedores detectados.

Para cada contenedor indica:

* Nombre.
* Tecnología.
* Responsabilidad.
* Archivos o carpetas asociadas.
* Relaciones principales.

Incluye obligatoriamente un diagrama Mermaid válido si existe evidencia suficiente en Graphify. Si no existe evidencia suficiente, no inventes el diagrama y marca la sección como “Diagrama pendiente de confirmar”.

## 5. Documentación modular

Para cada módulo detectado, genera:

### Módulo: [Nombre del módulo]

* Propósito.
* Responsabilidades principales.
* Archivos/carpetas relevantes.
* Componentes internos.
* Dependencias entrantes.
* Dependencias salientes.
* Relaciones con otros módulos.
* Riesgos o acoplamientos detectados.
* Observaciones.

## 6. Vista C4 - Nivel 3: Componentes por módulo

Para cada módulo importante:

* Lista sus componentes internos.
* Explica la responsabilidad de cada componente.
* Explica cómo interactúan entre sí.
* Incluye diagramas Mermaid separados por módulo cuando sea útil.

## 7. Datos y persistencia

* Bases de datos detectadas.
* Modelos, entidades, tablas o esquemas detectados.
* Archivos de configuración relacionados con datos.
* Flujo general de lectura/escritura de datos.
* Información pendiente de confirmar.

## 8. APIs, rutas o endpoints

Si se detectan rutas, controladores o servicios:

* Método o tipo de acceso, si está disponible.
* Ruta o nombre.
* Responsabilidad.
* Módulo relacionado.
* Dependencias utilizadas.

## 9. Infraestructura y despliegue

* Archivos Docker, CI/CD, variables de entorno o configuración detectada.
* Posible estrategia de despliegue.
* Dependencias externas.
* Información pendiente de confirmar.

## 10. Entorno de desarrollo

* Requisitos detectados.
* Comandos probables solo si están presentes en el proyecto.
* Configuraciones necesarias.
* Variables de entorno detectadas sin exponer secretos.

## 11. Decisiones técnicas detectadas

Documenta decisiones visibles en el código:

* Frameworks usados.
* Patrones arquitectónicos.
* Separación por capas o módulos.
* Uso de servicios externos.
* Estrategia de autenticación, si se detecta.
* Estrategia de persistencia, si se detecta.

No inventes justificaciones. Si no se conoce el motivo, escribe “Motivo no documentado en la entrada”.

## 12. Riesgos técnicos y recomendaciones

Basándote solo en la estructura detectada:

* Acoplamiento alto.
* Módulos demasiado grandes.
* Dependencias circulares.
* Archivos con demasiadas conexiones.
* Falta de separación aparente.
* Falta de documentación.
* Posibles mejoras.

Cada recomendación debe indicar:

* Problema observado.
* Evidencia en la información recibida.
* Recomendación concreta.

## 13. Glosario

Incluye términos técnicos importantes detectados en el proyecto.

## 14. Pendientes de confirmar

Lista todo lo que no se pudo confirmar con la información recibida.

FORMATO OBLIGATORIO DE DIAGRAMAS MERMAID

Cuando generes diagramas, usa exclusivamente Mermaid válido y renderizable.

Está prohibido usar:

* PlantUML.
* C4-PlantUML.
* Pseudocódigo de diagramas.
* Sintaxis como C4Container, C4Context, C4Component, Person(...), Container(...), System_Boundary(...), Rel(...), @startuml o @enduml.
* Diagramas como texto plano fuera de bloques Markdown.

Todo diagrama debe entregarse obligatoriamente dentro de un bloque Markdown fenced con la palabra `mermaid`.
No envuelvas los diagramas dentro de bloques `markdown`; el bloque debe iniciar directamente con ```mermaid y terminar con ```.

Formato obligatorio:

```mermaid
flowchart TD
    nodo_a["Nombre visible del elemento A"]
    nodo_b["Nombre visible del elemento B"]
    nodo_a -->|"Relación explicativa"| nodo_b
```

REGLAS DE SINTAXIS

1. Todo diagrama debe iniciar con `flowchart TD`.
2. Cada nodo debe tener un identificador simple, sin espacios, tildes ni caracteres especiales.

   * Correcto: `frontend`, `backend_api`, `db_principal`, `modulo_auth`.
   * Incorrecto: `API Backend`, `Base de Datos PostgreSQL`, `módulo-autenticación()`.
3. El texto visible del nodo debe ir entre corchetes y comillas.

   * Ejemplo: `backend_api["API Backend<br/>FastAPI"]`.
4. Cada relación debe tener una etiqueta descriptiva.

   * Ejemplo: `frontend -->|"Consume API REST mediante HTTP/JSON"| backend_api`.
5. No generes relaciones sin evidencia en Graphify.
6. Si una relación es inferida, indícalo en la etiqueta.

   * Ejemplo: `backend_api -->|"Lee/escribe datos (inferido)"| db_principal`.
7. No uses indentación de 4 espacios para representar diagramas.
8. No omitas la línea inicial ```mermaid ni la línea final ```.
9. No uses más de 10 a 15 nodos por diagrama.
10. Si el sistema es grande, divide los diagramas por módulo.
11. No mezcles niveles de abstracción en un mismo diagrama:

    * Diagrama de contexto: usuarios, sistema principal y sistemas externos.
    * Diagrama de contenedores: frontend, backend, base de datos, APIs, servicios externos o procesos.
    * Diagrama de componentes: componentes internos de un módulo o contenedor.

12. Cuando uses `subgraph` en Mermaid, utiliza siempre un identificador simple y un título visible entre corchetes y comillas.
    * Correcto: `subgraph sistema_simulacion["Sistema de Simulación de Resistencia Bacteriana"]`.
    * Incorrecto: `subgraph Sistema de Simulación de Resistencia Bacteriana`.

TIPOS DE DIAGRAMAS A GENERAR

Genera los siguientes diagramas solo si la información de Graphify lo permite:

1. Diagrama de Contexto del Sistema.

   * Debe mostrar usuarios, sistema principal y sistemas externos detectados.

2. Diagrama de Contenedores.

   * Debe mostrar frontend, backend, base de datos, APIs, servicios externos, procesos batch u otros contenedores detectados.

3. Diagrama Modular.

   * Debe mostrar los módulos principales detectados y sus dependencias.

4. Diagramas de Componentes por Módulo.

   * Deben generarse solo para módulos importantes o con suficiente información.
   * Cada diagrama debe enfocarse en un solo módulo.

5. Diagrama de Dependencias Críticas.

   * Debe generarse solo si Graphify detecta acoplamientos fuertes, dependencias circulares o nodos muy conectados.

FORMATO DE ENTREGA DE CADA DIAGRAMA

Cada diagrama debe entregarse con esta estructura:

### [Nombre del diagrama]

Breve explicación del objetivo del diagrama.

```mermaid
flowchart TD
    ...
```

Interpretación:

* Explica brevemente qué representa el diagrama.
* Indica qué elementos fueron detectados.
* Indica qué elementos fueron inferidos, si existen.

SI NO HAY EVIDENCIA SUFICIENTE

Si no hay información suficiente para generar un diagrama confiable, escribe exactamente:

“Diagrama pendiente de confirmar por falta de evidencia suficiente en Graphify”.

VALIDACIÓN FINAL

Antes de entregar la documentación final, verifica que:

* Todos los diagramas estén dentro de bloques ```mermaid.
* No exista sintaxis PlantUML ni C4-PlantUML.
* No existan diagramas como texto plano.
* Todas las relaciones tengan etiqueta descriptiva.
* Los nodos tengan nombres claros.
* Los diagramas no estén saturados.
* Los diagramas reflejen la información entregada por Graphify.

Si un diagrama no puede cumplir estas reglas, no lo generes.

A continuación recibirás la información del proyecto generada por Graphify:

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


def preparar_markdown_para_word_con_diagramas(ruta_markdown: Path) -> Path:
    """
    Convierte los bloques ```mermaid del Markdown en imágenes PNG
    y genera un Markdown temporal preparado para Pandoc.
    """
    contenido = ruta_markdown.read_text(encoding="utf-8")

    carpeta_base = ruta_markdown.parent
    carpeta_diagramas = carpeta_base / "diagramas_mermaid"
    carpeta_diagramas.mkdir(parents=True, exist_ok=True)

    ejecutable_mmdc = shutil.which("mmdc")
    if not ejecutable_mmdc:
        logger.warning(
            "No se encontró mmdc en el PATH. El Word se generará con los diagramas Mermaid como código."
        )
        return ruta_markdown

    patron_mermaid = re.compile(
        r"```mermaid\s*\n?([\s\S]*?)```",
        re.MULTILINE,
    )

    contador = 0

    def reemplazar_diagrama(match: re.Match) -> str:
        nonlocal contador
        contador += 1

        codigo_mermaid = match.group(1).strip()

        if not codigo_mermaid:
            return ""

        ruta_mmd = carpeta_diagramas / f"diagrama_{contador}.mmd"
        ruta_png = carpeta_diagramas / f"diagrama_{contador}.png"

        ruta_mmd.write_text(codigo_mermaid, encoding="utf-8")

        try:
            ruta_config_puppeteer = Path(__file__).resolve().parents[1] / "puppeteer-config.json"

            comando_mmdc = [
                ejecutable_mmdc,
                "-i",
                str(ruta_mmd),
                "-o",
                str(ruta_png),
                "-b",
                "transparent",
                "--scale",
                "2",
            ]

            if ruta_config_puppeteer.is_file():
                comando_mmdc.extend(["-p", str(ruta_config_puppeteer)])

            resultado = subprocess.run(
                comando_mmdc,
                check=True,
                timeout=60,
                capture_output=True,
                text=True,
            )

            if resultado.stderr:
                logger.debug("Salida de mmdc: %s", resultado.stderr)

        except subprocess.CalledProcessError as error:
            logger.exception(
                "Error al renderizar diagrama Mermaid con mmdc. stderr=%s",
                error.stderr,
            )
            return (
                "\n\n"
                "**No se pudo renderizar este diagrama Mermaid. Código original:**\n\n"
                "```mermaid\n"
                f"{codigo_mermaid}\n"
                "```\n\n"
            )

        except Exception:
            logger.exception("Error inesperado al renderizar diagrama Mermaid")
            return (
                "\n\n"
                "**No se pudo renderizar este diagrama Mermaid. Código original:**\n\n"
                "```mermaid\n"
                f"{codigo_mermaid}\n"
                "```\n\n"
            )

        if not ruta_png.is_file():
            logger.warning("mmdc no generó la imagen esperada: %s", ruta_png)
            return (
                "\n\n"
                "**No se pudo generar la imagen del diagrama Mermaid. Código original:**\n\n"
                "```mermaid\n"
                f"{codigo_mermaid}\n"
                "```\n\n"
            )

        ruta_relativa = f"diagramas_mermaid/{ruta_png.name}"
        return f"\n\n![Diagrama Mermaid {contador}]({ruta_relativa})\n\n"

    contenido_procesado = patron_mermaid.sub(reemplazar_diagrama, contenido)

    ruta_markdown_word = carpeta_base / "DOCUMENTACION_TECNICA_WORD.md"
    ruta_markdown_word.write_text(contenido_procesado, encoding="utf-8")

    return ruta_markdown_word


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

        ruta_markdown_word = preparar_markdown_para_word_con_diagramas(ruta_markdown)

        pypandoc.convert_file(
            source_file=str(ruta_markdown_word),
            to="docx",
            outputfile=str(ruta_word),
            extra_args=[
                "--standalone",
                f"--resource-path={ruta_markdown.parent}",
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
