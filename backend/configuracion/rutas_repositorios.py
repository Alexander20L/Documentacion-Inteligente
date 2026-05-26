from pathlib import Path

from fastapi import HTTPException


BASE_DIR = Path(__file__).resolve().parent.parent
REPOS_DIR = BASE_DIR / "repos"
GRAPHIFY_OUT_DIRNAME = "graphify-out"
IGNORED_REPO_DIRS = {GRAPHIFY_OUT_DIRNAME, ".git"}


def obtener_ruta_repositorio(id_repositorio: str) -> Path:
    ruta_repositorio = REPOS_DIR / id_repositorio

    if not ruta_repositorio.exists():
        raise HTTPException(status_code=404, detail="El repositorio no existe")

    return ruta_repositorio


def obtener_ruta_codigo_repositorio(id_repositorio: str) -> Path:
    ruta_repositorio = obtener_ruta_repositorio(id_repositorio)

    carpetas = [
        ruta
        for ruta in ruta_repositorio.iterdir()
        if ruta.is_dir() and ruta.name not in IGNORED_REPO_DIRS
    ]

    if len(carpetas) == 1:
        return carpetas[0]

    return ruta_repositorio


def iterar_candidatos_graphify_out(
    ruta_repositorio: Path,
    ruta_codigo: Path | None = None,
) -> list[Path]:
    candidatos: list[Path] = []
    vistos: set[Path] = set()

    def agregar(ruta: Path):
        ruta_resuelta = ruta.resolve()
        if ruta_resuelta not in vistos:
            vistos.add(ruta_resuelta)
            candidatos.append(ruta)

    if ruta_codigo is not None:
        agregar(ruta_codigo / GRAPHIFY_OUT_DIRNAME)

    agregar(ruta_repositorio / GRAPHIFY_OUT_DIRNAME)

    for ruta in sorted(ruta_repositorio.iterdir()):
        if ruta.is_dir() and ruta.name not in IGNORED_REPO_DIRS:
            agregar(ruta / GRAPHIFY_OUT_DIRNAME)

    return candidatos


def resolver_ruta_graphify_out(id_repositorio: str) -> Path:
    ruta_repositorio = obtener_ruta_repositorio(id_repositorio)
    ruta_codigo = obtener_ruta_codigo_repositorio(id_repositorio)

    for candidato in iterar_candidatos_graphify_out(ruta_repositorio, ruta_codigo):
        if candidato.is_dir():
            return candidato

    raise HTTPException(
        status_code=404,
        detail="No se encontró graphify-out para el repositorio",
    )
