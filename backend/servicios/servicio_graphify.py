import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import HTTPException, status

from configuracion.rutas_repositorios import (
    BASE_DIR,
    obtener_ruta_repositorio,
    obtener_ruta_codigo_repositorio,
    iterar_candidatos_graphify_out,
)
from configuracion.url_base import construir_url_publica
from servicios.servicio_limpieza import limpiar_carpetas_no_analizables


load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)

ARCHIVOS_GRAPHIFY = {
    "json": "graph.json",
    "manifest": "manifest.json",
    "analysis": ".graphify_analysis.json",
    "html": "graph.html",
    "reporte": "GRAPH_REPORT.md",
}

REPO_COMMAND_TIMEOUT_SECONDS = int(os.getenv("REPO_COMMAND_TIMEOUT_SECONDS", "900"))

VARIABLES_LLM_SOPORTADAS = [
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MOONSHOT_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
]


def preparar_entorno_graphify() -> dict[str, str]:
    """
    Prepara las variables de entorno que recibirá Graphify.

    Importante:
    - Carga variables desde backend/.env.
    - Agrega el venv local al PATH si existe.
    - Si existe GEMINI_API_KEY, también la expone como GOOGLE_API_KEY,
      porque algunas herramientas buscan una u otra.
    """
    variables_sistema = {
        "PATH", "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR", "SYSTEMROOT",
        "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "OLLAMA_HOST",
    }
    env = {
        nombre: valor
        for nombre, valor in os.environ.items()
        if nombre.upper() in variables_sistema or nombre in VARIABLES_LLM_SOPORTADAS
    }

    if env.get("GEMINI_API_KEY") and not env.get("GOOGLE_API_KEY"):
        env["GOOGLE_API_KEY"] = env["GEMINI_API_KEY"]

    rutas_venv = [
        str(ruta)
        for ruta in (
            BASE_DIR / ".venv" / "Scripts",
            BASE_DIR / ".venv" / "bin",
        )
        if ruta.exists()
    ]

    if rutas_venv:
        env["PATH"] = os.pathsep.join(rutas_venv + [env.get("PATH", "")])

    return env


def validar_configuracion_llm(env: dict[str, str]) -> None:
    """
    Valida que exista al menos una API key compatible con Graphify.
    """
    if os.getenv("C4_GRAPHIFY_LLM_PROVIDER", os.getenv("C4_LLM_PROVIDER", "ollama")).casefold() == "ollama":
        return
    tiene_api_key = any(env.get(nombre) for nombre in VARIABLES_LLM_SOPORTADAS)

    if not tiene_api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se encontró una API key LLM para Graphify. "
                "Configura GEMINI_API_KEY o GOOGLE_API_KEY en backend/.env."
            ),
        )


def argumentos_llm_graphify() -> list[str]:
    provider = os.getenv("C4_GRAPHIFY_LLM_PROVIDER", os.getenv("C4_LLM_PROVIDER", "ollama")).strip().casefold()
    if provider == "ollama":
        model = os.getenv("C4_GRAPHIFY_OLLAMA_MODEL", os.getenv("C4_OLLAMA_MODEL", "qwen3:8b"))
        return ["--backend", "ollama", "--model", model, "--max-concurrency", "1"]
    return []


def argumentos_extraccion_graphify() -> list[str]:
    provider = os.getenv("C4_GRAPHIFY_LLM_PROVIDER", os.getenv("C4_LLM_PROVIDER", "ollama")).strip().casefold()
    code_only = os.getenv("C4_GRAPHIFY_LOCAL_CODE_ONLY", "true").casefold() == "true"
    return ["--code-only"] if provider == "ollama" and code_only else argumentos_llm_graphify()


def argumentos_agrupacion_graphify() -> list[str]:
    provider = os.getenv("C4_GRAPHIFY_LLM_PROVIDER", os.getenv("C4_LLM_PROVIDER", "ollama")).strip().casefold()
    code_only = os.getenv("C4_GRAPHIFY_LOCAL_CODE_ONLY", "true").casefold() == "true"
    return ["--no-label"] if provider == "ollama" and code_only else argumentos_llm_graphify()


def ejecutar_comando(comando: list[str], cwd: Path, descripcion: str):
    env = preparar_entorno_graphify()

    try:
        resultado = subprocess.run(
            comando,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=env,
            timeout=REPO_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        logger.exception("%s excedió el tiempo máximo", descripcion)

        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"{descripcion} excedió el tiempo máximo permitido",
        ) from error

    logger.info(
        "%s finalizó. comando=%s stdout=%s stderr=%s",
        descripcion,
        comando,
        resultado.stdout,
        resultado.stderr,
    )

    if resultado.returncode != 0:
        logger.error(
            "%s falló. comando=%s stdout=%s stderr=%s",
            descripcion,
            comando,
            resultado.stdout,
            resultado.stderr,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{descripcion} falló. "
                "Revisa los logs del servidor para más detalles."
            ),
        )

    return resultado


def obtener_graphify_bin() -> Path | None:
    """
    Busca el ejecutable de Graphify.

    Prioridad:
    1. GRAPHIFY_BIN definido en .env
    2. backend/.venv/Scripts/graphify.exe
    3. backend/.venv/bin/graphify
    4. graphify disponible en PATH
    """
    ruta_env = os.getenv("GRAPHIFY_BIN")
    candidatos: list[Path] = []

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
            (
                "Graphify no generó graph.html para este análisis. "
                "El backend no genera una visualización HTML manual."
            ),
        )

    if not disponibles["reporte"]:
        mensajes.setdefault(
            "reporte",
            "Graphify no generó GRAPH_REPORT.md para este análisis.",
        )

    return {
        "archivos": archivos,
        "disponibles": disponibles,
        "mensajes": mensajes,
    }


def asegurar_outputs_graphify(ruta_graphify_out: Path) -> dict[str, str]:
    """
    Valida que Graphify haya generado sus artefactos reales.

    Este backend NO genera graph.html manual.
    El HTML debe venir exclusivamente de Graphify.
    """
    ruta_graph_json = ruta_graphify_out / ARCHIVOS_GRAPHIFY["json"]
    ruta_reporte = ruta_graphify_out / ARCHIVOS_GRAPHIFY["reporte"]
    ruta_html = ruta_graphify_out / ARCHIVOS_GRAPHIFY["html"]

    if not ruta_graph_json.is_file():
        raise HTTPException(
            status_code=500,
            detail="Graphify terminó, pero no generó graphify-out/graph.json",
        )

    if not ruta_reporte.is_file():
        raise HTTPException(
            status_code=500,
            detail="Graphify terminó, pero no generó graphify-out/GRAPH_REPORT.md",
        )

    if not ruta_html.is_file():
        raise HTTPException(
            status_code=500,
            detail=(
                "Graphify terminó, pero no generó graphify-out/graph.html. "
                "No se puede completar el análisis porque el sistema requiere "
                "la visualización HTML interactiva generada por Graphify."
            ),
        )

    return {}


def ejecutar_analisis_repositorio(id_repositorio: str) -> dict[str, Any]:
    ruta_repositorio = obtener_ruta_repositorio(id_repositorio)
    ruta_analisis = obtener_ruta_codigo_repositorio(id_repositorio)

    graphify_bin = obtener_graphify_bin()

    if graphify_bin is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "No se encontró Graphify. Configura GRAPHIFY_BIN o instala "
                "la CLI en el entorno del backend."
            ),
        )

    env = preparar_entorno_graphify()
    validar_configuracion_llm(env)

    limpiar_carpetas_no_analizables(ruta_analisis)

    for candidato in iterar_candidatos_graphify_out(ruta_repositorio, ruta_analisis):
        shutil.rmtree(candidato, ignore_errors=True)

    ejecutar_comando(
        ["git", "init"],
        cwd=ruta_analisis,
        descripcion="Inicialización de Git",
    )

    ejecutar_comando(
        ["git", "add", "-A", "-f"],
        cwd=ruta_analisis,
        descripcion="Registro de archivos en Git",
    )

    ejecutar_comando(
        [
            str(graphify_bin),
            "extract",
            ".",
            "--force",
            *argumentos_extraccion_graphify(),
        ],
        cwd=ruta_analisis,
        descripcion="Extracción de Graphify",
    )

    ruta_graphify_out = buscar_ruta_graphify_out(
        ruta_repositorio,
        ruta_analisis,
    )

    if ruta_graphify_out is None:
        raise HTTPException(
            status_code=500,
            detail="Graphify extract terminó, pero no generó la carpeta graphify-out",
        )

    ejecutar_comando(
        [
            str(graphify_bin),
            "cluster-only",
            ".",
            *argumentos_agrupacion_graphify(),
        ],
        cwd=ruta_analisis,
        descripcion="Generación de reporte y HTML interactivo de Graphify",
    )

    return construir_estado_archivos_graphify(
        f"repositorios/{id_repositorio}",
        ruta_graphify_out,
        asegurar_outputs_graphify(ruta_graphify_out),
    )


def ejecutar_graphify_en_ruta(ruta_analisis: Path) -> Path:
    """Run Graphify only inside an already isolated working copy."""
    from configuracion.rutas_c4 import es_repositorio_intento_analisis

    ruta_analisis = ruta_analisis.resolve()
    if not ruta_analisis.is_dir():
        raise RuntimeError("La copia de trabajo del repositorio no existe")
    if not es_repositorio_intento_analisis(ruta_analisis):
        raise RuntimeError("La ruta de Graphify no es una copia de trabajo C4 válida")
    graphify_bin = obtener_graphify_bin()
    if graphify_bin is None:
        raise RuntimeError("No se encontró Graphify; configura GRAPHIFY_BIN")
    validar_configuracion_llm(preparar_entorno_graphify())
    limpiar_carpetas_no_analizables(ruta_analisis)
    shutil.rmtree(ruta_analisis / "graphify-out", ignore_errors=True)
    ejecutar_comando(["git", "init"], ruta_analisis, "Inicialización de Git")
    ejecutar_comando(["git", "add", "-A", "-f"], ruta_analisis, "Registro de archivos en Git")
    ejecutar_comando(
        [str(graphify_bin), "extract", ".", "--force", *argumentos_extraccion_graphify()],
        ruta_analisis,
        "Extracción de Graphify",
    )
    salida = ruta_analisis / "graphify-out"
    if not salida.is_dir():
        raise RuntimeError("Graphify no generó graphify-out")
    ejecutar_comando(
        [str(graphify_bin), "cluster-only", ".", *argumentos_agrupacion_graphify()],
        ruta_analisis,
        "Generación de Graphify",
    )
    if not (salida / "graph.json").is_file():
        raise RuntimeError("Graphify no generó graphify-out/graph.json")
    return salida
