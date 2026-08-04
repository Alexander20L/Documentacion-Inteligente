import base64
import hashlib
import os
import json
from pathlib import Path

from fastapi import HTTPException
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_STORAGE_ROOT = (
    Path(os.environ["LOCALAPPDATA"]) / "doc-int"
    if os.name == "nt" and os.getenv("LOCALAPPDATA")
    else BASE_DIR
)
REPOS_DIR = Path(os.getenv("REPOSITORY_STORAGE_ROOT") or (DEFAULT_STORAGE_ROOT / "repos")).expanduser().resolve()
REPOSITORY_OBJECTS_DIR = REPOS_DIR / "_objects"
GRAPHIFY_OUT_DIRNAME = "graphify-out"
IGNORED_REPO_DIRS = {GRAPHIFY_OUT_DIRNAME, ".git"}


def ruta_contenida(base: Path, *partes: str) -> Path:
    """Resolve an untrusted relative path and require it to remain below base."""
    base_resuelta = base.resolve()
    candidata = base_resuelta.joinpath(*partes).resolve()
    try:
        candidata.relative_to(base_resuelta)
    except ValueError as error:
        raise ValueError("La ruta solicitada sale del directorio permitido") from error
    return candidata


def token_almacenamiento(ambito: str, identificador: str) -> str:
    """Create a fixed-size filesystem token without exposing untrusted identifiers."""
    if not ambito or not identificador or not identificador.strip():
        raise ValueError("El identificador de almacenamiento no puede estar vacío")
    digest = hashlib.sha256(f"{ambito}\0{identificador}".encode("utf-8")).digest()[:16]
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()


def obtener_raiz_repositorio(id_repositorio: str) -> Path:
    tokenizada = ruta_contenida(REPOS_DIR, token_almacenamiento("repository", id_repositorio))
    try:
        legado = ruta_contenida(REPOS_DIR, id_repositorio)
    except ValueError:
        legado = None
    return legado if legado is not None and not tokenizada.exists() and legado.exists() else tokenizada


def obtener_ruta_fuente(id_repositorio: str) -> Path:
    raiz = obtener_raiz_repositorio(id_repositorio)
    referencia = raiz / "source.json"
    if referencia.is_file():
        try:
            source_hash = json.loads(referencia.read_text(encoding="utf-8"))["source_hash"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("La referencia de fuente del repositorio es inválida") from error
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(
            character not in "0123456789abcdef" for character in source_hash
        ):
            raise ValueError("El hash de la fuente del repositorio es inválido")
        return ruta_contenida(REPOSITORY_OBJECTS_DIR, source_hash, "source")
    return ruta_contenida(raiz, "source")


def obtener_ruta_objeto_fuente(source_hash: str) -> Path:
    if len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash):
        raise ValueError("El hash de fuente es inválido")
    return ruta_contenida(REPOSITORY_OBJECTS_DIR, source_hash, "source")


def obtener_ruta_repositorio(id_repositorio: str) -> Path:
    ruta_repositorio = obtener_raiz_repositorio(id_repositorio)

    if not ruta_repositorio.exists():
        raise HTTPException(status_code=404, detail="El repositorio no existe")

    return ruta_repositorio


def obtener_ruta_codigo_repositorio(id_repositorio: str) -> Path:
    obtener_ruta_repositorio(id_repositorio)
    ruta_repositorio = obtener_ruta_fuente(id_repositorio)

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
