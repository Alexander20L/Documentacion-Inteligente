import shutil
from pathlib import Path


CARPETAS_NO_ANALIZABLES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    "target",
    "vendor",
    ".next",
    ".angular",
}


def limpiar_carpetas_no_analizables(ruta_base: Path) -> None:
    for nombre_carpeta in CARPETAS_NO_ANALIZABLES:
        for ruta in list(ruta_base.rglob(nombre_carpeta)):
            if ruta.is_dir():
                shutil.rmtree(ruta, ignore_errors=True)