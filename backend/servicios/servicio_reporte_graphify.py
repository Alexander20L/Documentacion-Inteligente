import json
from pathlib import Path


def obtener_nodos_y_enlaces(graph: dict):
    nodos = graph.get("nodes", [])
    enlaces = graph.get("links", graph.get("edges", []))
    return nodos, enlaces


def generar_graph_report_md(ruta_graphify_out: Path) -> None:
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