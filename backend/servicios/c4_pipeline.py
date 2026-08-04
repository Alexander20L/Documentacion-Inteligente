from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from c4core import (
    AnalystContext,
    CanonicalC4Model,
    EvidenceSource,
    FilesystemExtractionAdapter,
    assemble_canonical_model,
    assert_valid_c4_model,
    canonical_json,
    normalize_graphify_json,
    render_docx_artifact,
    render_markdown_artifact,
    render_structurizr_artifact,
    validate_candidates,
    validate_c4_model,
)
from configuracion.rutas_c4 import (
    C4_ANALYSIS_ATTEMPTS_DIR,
    C4_PUBLICATION_ATTEMPTS_DIR,
    C4_RUNS_DIR,
    obtener_raiz_ejecucion,
    obtener_raiz_intento_analisis,
    obtener_raiz_intento_publicacion,
    obtener_repositorio_intento_analisis,
)
from configuracion.rutas_repositorios import obtener_ruta_fuente
from configuracion.supabase_cliente import supabase_admin
from servicios.servicio_almacenamiento import eliminar_directorio_seguro
from servicios.c4_revision import candidatos_detectados_contexto, crear_contenido_revision, relaciones_detectadas_contexto
from servicios.c4_archivos import metadata_artefacto
from servicios.servicio_graphify import ejecutar_graphify_en_ruta
from servicios.semantic_agent_pipeline import run_semantic_agent_pipeline, sanitize_semantic_work_copy


Heartbeat = Callable[[int, str, str | None, str | None, int | None, int | None], None]


def filtrar_diagramas_publicados(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devuelve los diagramas SVG del modelo con su origen (plantuml/mermaid).

    Mermaid es una exportación opcional para documentación; el frontend decide
    si mostrarla como diagrama oficial según el origen.
    """
    resultados = []
    for item in registros:
        if item["tipo"] != "diagrama" or item["metadata"]["formato"] != "svg":
            continue
        ruta = item["metadata"].get("ruta_logica", "")
        if "mermaid/" in ruta:
            origen = "mermaid"
        elif "plantuml/" in ruta:
            origen = "plantuml"
        else:
            origen = None
        resultados.append({
            "id": item["id"],
            "nombre": item["nombre"],
            "nivel": item["metadata"].get("nivel") or "c4",
            "formato": item["metadata"]["formato"],
            "origen": origen,
        })
    return resultados


def _sin_heartbeat(
    _progreso: int,
    _fase: str,
    _paso: str | None = None,
    _mensaje: str | None = None,
    _unidades_completadas: int | None = None,
    _unidades_totales: int | None = None,
) -> None:
    return None


def _escribir_atomico(ruta: Path, contenido: str | bytes) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f".{ruta.name}.tmp")
    if isinstance(contenido, bytes):
        temporal.write_bytes(contenido)
    else:
        temporal.write_text(contenido, encoding="utf-8", newline="\n")
    temporal.replace(ruta)


def _error_sanitizado(error: Exception, limite: int = 1500) -> str:
    texto = re.sub(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*\S+", r"\1=[REDACTED]", str(error))
    return texto[:limite] or type(error).__name__


def ejecutar_analisis_c4(tarea: dict[str, Any], heartbeat: Heartbeat = _sin_heartbeat) -> None:
    id_repositorio = tarea["id_repositorio"]
    id_ejecucion = tarea.get("ejecucion_c4_id") or (tarea.get("payload") or {}).get("id_ejecucion")
    if not id_ejecucion:
        raise RuntimeError("La tarea analisis_c4 no referencia una ejecución")
    ejecucion = _obtener_ejecucion(id_ejecucion, id_repositorio)
    if (ejecucion.get("resultado") or {}).get("fase") == "revision":
        return
    contexto = (ejecucion.get("configuracion") or {}).get("contexto")
    if not contexto:
        raise RuntimeError("La ejecución C4 no contiene contexto de analista")
    raiz_canonica = obtener_raiz_ejecucion(id_repositorio, id_ejecucion)
    intento = int(tarea.get("intentos") or 1)
    id_tarea = str(tarea.get("id") or "manual")
    raiz = obtener_raiz_intento_analisis(id_tarea, intento)
    trabajo = obtener_repositorio_intento_analisis(id_tarea, intento)
    fuente = obtener_ruta_fuente(id_repositorio)
    if not fuente.is_dir():
        raise RuntimeError("No existe la fuente inmutable del repositorio")
    heartbeat(1, "ingesta", "preparar_copia", "Preparando una copia de trabajo inmutable", None, None)
    eliminar_directorio_seguro(raiz, C4_ANALYSIS_ATTEMPTS_DIR)
    trabajo.parent.mkdir(parents=True, exist_ok=True)
    hash_fuente_antes = _hash_directorio(fuente)
    shutil.copytree(fuente, trabajo, symlinks=False)
    escaneo_previo = sanitize_semantic_work_copy(trabajo)
    heartbeat(5, "descubrimiento", "sanear_fuentes", "Copia de trabajo preparada y saneada", None, None)
    heartbeat(10, "descubrimiento", "extraer_estructura", "Extrayendo estructura y manifiestos", None, None)

    analista = AnalystContext(
        repository_name=id_repositorio,
        system_name=contexto["nombre_sistema"],
        purpose=contexto.get("proposito") or contexto.get("descripcion"),
        users=tuple(item["nombre"] for item in contexto.get("actores", [])),
        notes=(canonical_json(contexto),),
    )
    extraccion = FilesystemExtractionAdapter().extract(trabajo, analista)
    salida_graphify = ejecutar_graphify_en_ruta(trabajo)
    heartbeat(35, "descubrimiento", "analizar_grafo", "Graphify completó el grafo de evidencia", None, None)
    graph_origen = salida_graphify / "graph.json"
    graph = json.loads(graph_origen.read_text(encoding="utf-8"))
    salida_graphify_preservada = raiz / "extraction" / "graphify"
    shutil.copytree(salida_graphify, salida_graphify_preservada)
    normalizado = normalize_graphify_json(graph)
    evidencia_analista = next(item for item in extraccion.evidence if item.source == EvidenceSource.ANALYST)
    detectados, sistema_id = candidatos_detectados_contexto(contexto, evidencia_analista.id)
    relaciones_contexto = relaciones_detectadas_contexto(detectados, sistema_id, evidencia_analista.id)
    heartbeat(55, "descubrimiento", "preparar_agentes", "Preparando el análisis semántico por módulos", 0, None)

    resultado_semantico = run_semantic_agent_pipeline(
        work=trabajo,
        run_root=raiz,
        run_id=id_ejecucion,
        tenant_id=str(tarea.get("usuario_id") or id_repositorio),
        repository_id=id_repositorio,
        source_hash=hash_fuente_antes,
        analyst_elements=detectados,
        extraction=extraccion,
        normalized_graph=normalizado,
        admin=supabase_admin,
        preliminary_scans=escaneo_previo,
        checkpoint=lambda: heartbeat(60, "descubrimiento", None, None, None, None),
        progress=lambda modulo, completadas, totales: heartbeat(
            60 + (20 * completadas // max(1, totales)),
            "descubrimiento",
            "analizar_modulos",
            (
                f"Infraestructura analizada; preparando {totales} módulos"
                if completadas == 0
                else f"Módulo {completadas}/{totales}: {modulo}"
            ),
            completadas,
            totales,
        ),
    )
    evidencia_por_id = {
        item.id: item for item in (*extraccion.evidence, *normalizado.evidence, *resultado_semantico.evidence)
    }
    evidencia = tuple(evidencia_por_id[key] for key in sorted(evidencia_por_id))
    inferidos = resultado_semantico.elements
    relaciones = (*relaciones_contexto, *resultado_semantico.relationships)
    elementos = (*detectados, *inferidos)
    validacion = validate_candidates(elementos, relaciones, evidencia, require_decisions=False)
    if validacion.issues:
        raise ValueError("Candidatos C4 inválidos: " + "; ".join(item.message for item in validacion.issues))
    contenido = crear_contenido_revision(elementos, relaciones, metadata=resultado_semantico.metadata)
    contenido["evidencia"] = [item.model_dump(mode="json") for item in evidencia]
    contenido["hash_fuente"] = hash_fuente_antes
    if _hash_directorio(fuente) != hash_fuente_antes:
        raise RuntimeError("La fuente inmutable cambió durante el análisis")
    heartbeat(85, "revision", "preparar_revision", "Preparando candidatos para revisión", None, None)
    _escribir_atomico(raiz / "revision" / "candidates.json", canonical_json(contenido))
    _escribir_atomico(
        raiz / "evidence" / "evidence.json",
        canonical_json({"hash_fuente": hash_fuente_antes, "registros": contenido["evidencia"]}),
    )
    eliminar_directorio_seguro(trabajo, raiz)
    heartbeat(90, "revision", "publicar_revision", "Publicando evidencia y candidatos", None, None)
    raiz_canonica.parent.mkdir(parents=True, exist_ok=True)
    eliminar_directorio_seguro(raiz_canonica, C4_RUNS_DIR)
    raiz.replace(raiz_canonica)
    heartbeat(95, "revision", "registrar_revision", "Registrando la revisión C4", None, None)
    supabase_admin.table("revisiones_c4").upsert({
        "ejecucion_c4_id": id_ejecucion,
        "estado": "pendiente",
        "contenido": contenido,
    }, on_conflict="ejecucion_c4_id").execute()
    heartbeat(100, "revision", "revision_humana", "Esperando revisión humana", None, None)


def preparar_resultado_revision_c4(tarea: dict[str, Any]) -> dict[str, Any]:
    """Build the review state committed atomically with task completion."""
    id_ejecucion = tarea.get("ejecucion_c4_id") or (tarea.get("payload") or {}).get("id_ejecucion")
    resultado = (
        supabase_admin.table("revisiones_c4").select("contenido")
        .eq("ejecucion_c4_id", id_ejecucion).order("created_at", desc=True).limit(1).execute()
    )
    if not resultado.data:
        raise RuntimeError("No se encontró la revisión generada")
    revision = (resultado.data[0].get("contenido") or {}).get("revision") or {}
    ejecucion = _obtener_ejecucion(id_ejecucion)
    contenido = resultado.data[0].get("contenido") or {}
    return {
        **(ejecucion.get("resultado") or {}),
        "fase": "revision",
        "version": revision["version"],
        "hash": revision["hash"],
        "hash_fuente": contenido.get("hash_fuente"),
    }


def _obtener_ejecucion(id_ejecucion: str, id_repositorio: str | None = None) -> dict[str, Any]:
    consulta = supabase_admin.table("ejecuciones_c4").select("*").eq("id", id_ejecucion)
    if id_repositorio:
        consulta = consulta.eq("id_repositorio", id_repositorio)
    resultado = consulta.limit(1).execute()
    if not resultado.data:
        raise RuntimeError("La ejecución C4 no existe")
    return dict(resultado.data[0])


def _hash_directorio(ruta: Path) -> str:
    digest = hashlib.sha256()
    for entrada in sorted(ruta.rglob("*"), key=lambda item: item.relative_to(ruta).as_posix()):
        relativa = entrada.relative_to(ruta).as_posix().encode("utf-8")
        digest.update(b"D" if entrada.is_dir() else b"F")
        digest.update(len(relativa).to_bytes(8, "big"))
        digest.update(relativa)
        if entrada.is_file():
            digest.update(entrada.stat().st_size.to_bytes(8, "big"))
            with entrada.open("rb") as archivo:
                for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
                    digest.update(bloque)
    return digest.hexdigest()


def _ejecutar_herramienta(comando: list[str], cwd: Path, descripcion: str) -> subprocess.CompletedProcess[str]:
    timeout = int(os.getenv("C4_TOOL_TIMEOUT_SECONDS", "300"))
    try:
        resultado = subprocess.run(comando, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error:
        raise RuntimeError(f"No se encontró la herramienta para {descripcion}: {comando[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{descripcion} excedió {timeout} segundos") from error
    if resultado.returncode:
        detalle = _error_sanitizado(resultado.stderr or resultado.stdout)
        raise RuntimeError(f"{descripcion} falló: {detalle}")
    return resultado


def _comando_structurizr(java: str, cli: str) -> list[str]:
    if Path(cli).suffix.lower() == ".jar":
        return [java, "-cp", str(Path(cli).parent / "*"), "com.structurizr.cli.StructurizrCliApplication"]
    return [cli]


def _registro_artefacto(id_ejecucion: str, raiz: Path, ruta: Path, tipo: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "ejecucion_c4_id": id_ejecucion,
        "tipo": tipo,
        "nombre": ruta.name,
        "ruta": ruta.resolve().relative_to(raiz.resolve()).as_posix(),
        "metadata": {
            **metadata,
            **metadata_artefacto(ruta),
        },
    }


def ejecutar_publicacion_c4(tarea: dict[str, Any], heartbeat: Heartbeat = _sin_heartbeat) -> dict[str, Any] | None:
    id_repositorio = tarea["id_repositorio"]
    id_ejecucion = tarea.get("ejecucion_c4_id") or (tarea.get("payload") or {}).get("id_ejecucion")
    ejecucion = _obtener_ejecucion(id_ejecucion, id_repositorio)
    if ejecucion.get("estado") == "completado":
        return ejecucion.get("resultado") or {}
    resultado_ejecucion = ejecucion.get("resultado") or {}
    modelo = CanonicalC4Model.model_validate(resultado_ejecucion.get("modelo_aprobado"))
    assert_valid_c4_model(modelo)
    raiz = obtener_raiz_ejecucion(id_repositorio, id_ejecucion)
    intento = int(tarea.get("intentos") or 1)
    id_tarea = str(tarea.get("id") or "manual")
    salida_canonica = raiz / "artifacts"
    salida = obtener_raiz_intento_publicacion(id_tarea, intento)
    heartbeat(1, "generacion", "preparar_publicacion", "Preparando la publicación aprobada", None, None)
    eliminar_directorio_seguro(salida, C4_PUBLICATION_ATTEMPTS_DIR)
    salida.mkdir(parents=True, exist_ok=True)
    heartbeat(15, "generacion", "generar_dsl", "Generando el workspace Structurizr", None, None)
    dsl_artifact = render_structurizr_artifact(modelo)
    _escribir_atomico(salida / dsl_artifact.filename, dsl_artifact.content)

    cli = os.getenv("STRUCTURIZR_CLI_PATH")
    plantuml = os.getenv("PLANTUML_JAR")
    java = os.getenv("JAVA_BIN", "java")
    if not cli or not Path(cli).is_file():
        raise RuntimeError("STRUCTURIZR_CLI_PATH no apunta a Structurizr CLI")
    if not plantuml or not Path(plantuml).is_file():
        raise RuntimeError("PLANTUML_JAR no apunta a un JAR de PlantUML")
    cli = str(Path(cli).resolve())
    plantuml = str(Path(plantuml).resolve())
    dsl = salida / "workspace.dsl"
    heartbeat(25, "validacion", "validar_structurizr", "Validando el workspace Structurizr", None, None)
    structurizr = _comando_structurizr(java, cli)
    validacion_structurizr = _ejecutar_herramienta(
        [*structurizr, "validate", "-workspace", str(dsl)],
        salida,
        "Validación Structurizr",
    )
    _escribir_atomico(
        salida / "structurizr-validation.txt",
        (validacion_structurizr.stdout or "Structurizr validation passed").strip() + "\n",
    )
    puml = salida / "plantuml"
    puml.mkdir(exist_ok=True)
    _ejecutar_herramienta(
        [*structurizr, "export", "-workspace", str(dsl), "-format", "plantuml", "-output", str(puml)],
        salida,
        "Exportación Structurizr",
    )
    fuentes = sorted(puml.glob("*.puml"))
    if not fuentes:
        raise RuntimeError("Structurizr no exportó diagramas PlantUML")
    for formato in ("svg", "png"):
        _ejecutar_herramienta([java, "-jar", plantuml, f"-t{formato}", *[str(item) for item in fuentes]], salida, f"Render PlantUML {formato}")
    esperados = set(re.findall(
        r'^\s*(?:systemContext|container|component)\s+\S+\s+"([^"]+)"\s*\{',
        dsl.read_text(encoding="utf-8"),
        re.MULTILINE,
    ))
    faltantes = [clave for clave in sorted(esperados) if not all(any(clave in item.stem for item in puml.glob(f"*.{fmt}")) for fmt in ("svg", "png"))]
    if faltantes:
        raise RuntimeError("Faltan diagramas requeridos: " + ", ".join(faltantes))
    heartbeat(75, "validacion", "renderizar_diagramas", "Diagramas PlantUML requeridos renderizados", None, None)

    advertencias: list[str] = []
    mermaid_dir = salida / "mermaid"
    try:
        mermaid_dir.mkdir(exist_ok=True)
        _ejecutar_herramienta(
            [*structurizr, "export", "-workspace", str(dsl), "-format", "mermaid", "-output", str(mermaid_dir)],
            salida,
            "Exportación Mermaid",
        )
        mermaid_sources = sorted((*mermaid_dir.glob("*.mmd"), *mermaid_dir.glob("*.mermaid")))
        if not mermaid_sources:
            advertencias.append("Structurizr no produjo fuentes Mermaid; la salida C4 principal sigue siendo válida.")
        mermaid_cli = os.getenv("MERMAID_CLI_BIN") or shutil.which("mmdc")
        if mermaid_sources and not mermaid_cli:
            advertencias.append("Mermaid fue exportado, pero MERMAID_CLI_BIN/mmdc no está disponible para renderizarlo.")
        elif mermaid_cli:
            for source in mermaid_sources:
                _ejecutar_herramienta(
                    [mermaid_cli, "-i", str(source), "-o", str(source.with_suffix(".svg")), "-b", "transparent"],
                    salida,
                    f"Render Mermaid {source.name}",
                )
    except RuntimeError as error:
        advertencias.append(f"Salida Mermaid opcional no disponible: {_error_sanitizado(error, 500)}")

    diagramas_svg = sorted(puml.glob("*.svg"))
    diagramas_png = sorted(puml.glob("*.png"))
    markdown_artifact = render_markdown_artifact(
        modelo,
        diagram_filenames=(f"plantuml/{ruta.name}" for ruta in diagramas_svg),
    )
    docx_artifact = render_docx_artifact(
        modelo,
        diagrams=((ruta.stem, ruta.read_bytes()) for ruta in diagramas_png),
    )
    _escribir_atomico(salida / markdown_artifact.filename, markdown_artifact.content)
    _escribir_atomico(salida / docx_artifact.filename, docx_artifact.content)

    issues = validate_c4_model(modelo)
    reporte = {"valida": not issues, "errores": [item.message for item in issues], "advertencias": advertencias}
    _escribir_atomico(salida / "validation-report.json", canonical_json(reporte))
    heartbeat(82, "validacion", "generar_documentos", "Documentación Markdown y DOCX generada", None, None)
    eliminar_directorio_seguro(salida_canonica, raiz)
    salida.replace(salida_canonica)
    salida = salida_canonica
    dsl = salida / "workspace.dsl"
    puml = salida / "plantuml"
    mermaid_dir = salida / "mermaid"
    diagramas_svg = sorted(puml.glob("*.svg"))
    _escribir_atomico(
        raiz / "approved" / "canonical-model.json",
        canonical_json(modelo),
    )
    rutas = [
        raiz / "extraction" / "graphify" / "graph.json",
        raiz / "evidence" / "evidence.json",
        raiz / "revision" / "candidates.json",
        raiz / "approved" / "canonical-model.json",
        dsl,
        salida / "structurizr-validation.txt",
        salida / "ARCHITECTURE.md",
        salida / "ARCHITECTURE.docx",
        salida / "validation-report.json",
    ]
    for directorio in ("semantic", "agents", "merge", "evaluation"):
        base = raiz / directorio
        if base.is_dir():
            rutas.extend(sorted(item for item in base.rglob("*") if item.is_file()))
    rutas.extend(sorted((*puml.glob("*.puml"), *puml.glob("*.svg"), *puml.glob("*.png"))))
    if mermaid_dir.is_dir():
        rutas.extend(sorted(item for item in mermaid_dir.rglob("*") if item.is_file()))
    rutas = list(dict.fromkeys(rutas))
    manifiesto = [{
        "nombre": ruta.name,
        "ruta": ruta.resolve().relative_to(raiz.resolve()).as_posix(),
        "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
        "size": ruta.stat().st_size,
    } for ruta in rutas]
    _escribir_atomico(salida / "artifact-manifest.json", canonical_json(manifiesto))
    rutas.append(salida / "artifact-manifest.json")
    heartbeat(85, "validacion", "registrar_artefactos", "Registrando artefactos validados", 0, len(rutas))
    registros_nuevos = []
    for indice, ruta in enumerate(rutas):
        heartbeat(
            86 + min(10, indice * 10 // max(1, len(rutas))),
            "validacion",
            "registrar_artefactos",
            f"Artefacto {indice + 1}/{len(rutas)}: {ruta.name}",
            indice + 1,
            len(rutas),
        )
        formato = ruta.suffix.lstrip(".")
        nivel = next((nivel for nivel in ("context", "containers", "components") if nivel in ruta.stem), None)
        relativa = ruta.resolve().relative_to(raiz.resolve()).as_posix()
        if formato in {"svg", "png", "puml", "mmd"}:
            tipo = "diagrama"
        elif relativa.startswith("semantic/"):
            tipo = "indice_semantico"
        elif relativa.startswith(("agents/", "merge/", "evaluation/")):
            tipo = "revision_multiagente"
        elif relativa.startswith("evidence/"):
            tipo = "evidencia_rag"
        else:
            tipo = "documento_c4"
        registros_nuevos.append(_registro_artefacto(
            id_ejecucion,
            raiz,
            ruta,
            tipo,
            {"formato": formato, "nivel": nivel, "ruta_logica": relativa},
        ))
    heartbeat(97, "validacion", "confirmar_artefactos", "Confirmando el registro atómico de artefactos", len(rutas), len(rutas))
    resultado_registro = supabase_admin.rpc("reemplazar_artefactos_c4", {
        "p_tarea_id": tarea["id"],
        "p_lease_owner": tarea.get("lease_owner") or os.getenv("WORKER_ID") or "",
        "p_intento": intento,
        "p_ejecucion_c4_id": id_ejecucion,
        "p_artefactos": registros_nuevos,
    }).execute()
    registros = [dict(item) for item in (resultado_registro.data or [])]
    if len(registros) != len(registros_nuevos):
        raise RuntimeError("El registro atómico de artefactos C4 quedó incompleto")
    final = {
        **resultado_ejecucion,
        "fase": "completado",
        "validacion": reporte,
        "artefactos": [{"id": item["id"], "nombre": item["nombre"], "tipo": item["tipo"]} for item in registros],
        "diagramas": filtrar_diagramas_publicados(registros),
    }
    heartbeat(100, "completado", "completado", "Publicación C4 completada", len(rutas), len(rutas))
    return final
