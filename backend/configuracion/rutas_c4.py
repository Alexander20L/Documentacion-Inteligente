import os
from pathlib import Path

from configuracion.rutas_repositorios import DEFAULT_STORAGE_ROOT, ruta_contenida, token_almacenamiento


C4_STORAGE_ROOT = Path(os.getenv("C4_STORAGE_ROOT") or (DEFAULT_STORAGE_ROOT / "c4")).expanduser().resolve()
C4_RUNS_DIR = C4_STORAGE_ROOT / "r"
C4_ANALYSIS_ATTEMPTS_DIR = C4_STORAGE_ROOT / "a"
C4_PUBLICATION_ATTEMPTS_DIR = C4_STORAGE_ROOT / "p"


def obtener_raiz_ejecucion(id_repositorio: str, id_ejecucion: str) -> Path:
    token_almacenamiento("repository-check", id_repositorio)
    return ruta_contenida(C4_RUNS_DIR, token_almacenamiento("execution", id_ejecucion))


def _validar_intento(intento: int) -> str:
    if intento < 1:
        raise ValueError("El intento debe ser mayor que cero")
    return str(intento)


def obtener_raiz_intento_analisis(id_tarea: str, intento: int) -> Path:
    return ruta_contenida(
        C4_ANALYSIS_ATTEMPTS_DIR,
        token_almacenamiento("analysis-task", id_tarea),
        _validar_intento(intento),
    )


def obtener_repositorio_intento_analisis(id_tarea: str, intento: int) -> Path:
    return ruta_contenida(obtener_raiz_intento_analisis(id_tarea, intento), "w")


def obtener_raiz_intento_publicacion(id_tarea: str, intento: int) -> Path:
    return ruta_contenida(
        C4_PUBLICATION_ATTEMPTS_DIR,
        token_almacenamiento("publication-task", id_tarea),
        _validar_intento(intento),
    )


def es_repositorio_intento_analisis(ruta: Path) -> bool:
    try:
        relativa = ruta.resolve().relative_to(C4_ANALYSIS_ATTEMPTS_DIR.resolve())
    except ValueError:
        return False
    return (
        len(relativa.parts) == 3
        and len(relativa.parts[0]) == 26
        and relativa.parts[1].isdigit()
        and int(relativa.parts[1]) > 0
        and relativa.parts[2] == "w"
    )


def obtener_ruta_ejecucion(id_repositorio: str, id_ejecucion: str, ruta_relativa: str) -> Path:
    return ruta_contenida(obtener_raiz_ejecucion(id_repositorio, id_ejecucion), ruta_relativa)


def ruta_relativa_ejecucion(id_repositorio: str, id_ejecucion: str, ruta: Path) -> str:
    return ruta.resolve().relative_to(obtener_raiz_ejecucion(id_repositorio, id_ejecucion).resolve()).as_posix()
