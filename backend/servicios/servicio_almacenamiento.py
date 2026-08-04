from __future__ import annotations

import os
import shutil
import stat
import hashlib
import json
from pathlib import Path
from typing import Any

from configuracion.rutas_c4 import (
    C4_ANALYSIS_ATTEMPTS_DIR,
    C4_PUBLICATION_ATTEMPTS_DIR,
    C4_RUNS_DIR,
)
from configuracion.rutas_repositorios import (
    BASE_DIR,
    REPOSITORY_OBJECTS_DIR,
    REPOS_DIR,
    obtener_raiz_repositorio,
    obtener_ruta_objeto_fuente,
    token_almacenamiento,
)
from configuracion.supabase_cliente import supabase_admin


def _hacer_escribible_y_reintentar(func, ruta: str, _error) -> None:
    os.chmod(ruta, os.stat(ruta).st_mode | stat.S_IWUSR)
    func(ruta)


def eliminar_directorio_seguro(ruta: Path, raiz_permitida: Path) -> None:
    """Remove one bounded tree, including Windows read-only files, or fail."""
    if ruta.is_symlink():
        raise ValueError("No se permite limpiar un enlace simbólico como directorio")
    raiz = raiz_permitida.resolve()
    objetivo = ruta.resolve()
    if objetivo == raiz:
        raise ValueError("No se puede eliminar la raíz de almacenamiento")
    try:
        objetivo.relative_to(raiz)
    except ValueError as error:
        raise ValueError("La limpieza solicitada sale de la raíz permitida") from error

    if not ruta.exists():
        return
    shutil.rmtree(objetivo, onerror=_hacer_escribible_y_reintentar)
    if ruta.exists() or ruta.is_symlink():
        raise OSError(f"No se pudo eliminar completamente el directorio: {objetivo}")


def hash_directorio(ruta: Path) -> str:
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


def publicar_fuente_inmutable(ruta_temporal: Path) -> tuple[str, Path]:
    """Atomically reuse or publish an immutable extracted source tree."""
    source_hash = hash_directorio(ruta_temporal)
    destino = obtener_ruta_objeto_fuente(source_hash)
    if destino.is_dir():
        if hash_directorio(destino) != source_hash:
            raise RuntimeError("El objeto de fuente existente no supera la verificación de integridad")
        eliminar_directorio_seguro(ruta_temporal, REPOS_DIR)
        return source_hash, destino

    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        ruta_temporal.replace(destino)
    except OSError:
        if not destino.is_dir() or hash_directorio(destino) != source_hash:
            raise
        eliminar_directorio_seguro(ruta_temporal, REPOS_DIR)
    if hash_directorio(destino) != source_hash:
        eliminar_directorio_seguro(destino.parent, REPOSITORY_OBJECTS_DIR)
        raise RuntimeError("La fuente publicada no supera la verificación de integridad")
    return source_hash, destino


def _filas(tabla: str, columnas: str) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    desplazamiento = 0
    while True:
        pagina = (
            supabase_admin.table(tabla)
            .select(columnas)
            .range(desplazamiento, desplazamiento + 999)
            .execute()
            .data
            or []
        )
        if not pagina:
            return filas
        filas.extend(dict(fila) for fila in pagina)
        desplazamiento += len(pagina)


def _candidatos_directos(
    raiz: Path,
    esperados: set[str],
    categoria: str,
    ignorados: set[str] | None = None,
) -> list[dict[str, str]]:
    if not raiz.is_dir():
        return []
    return [
        {"categoria": categoria, "ruta": str(ruta.absolute())}
        for ruta in sorted(raiz.iterdir())
        if ruta.name not in esperados and ruta.name not in (ignorados or set())
    ]


def _candidatos_intentos(
    raiz: Path,
    esperados: set[tuple[str, str]],
    categoria: str,
) -> list[dict[str, str]]:
    if not raiz.is_dir():
        return []
    candidatos: list[dict[str, str]] = []
    for directorio_tarea in sorted(raiz.iterdir()):
        if not directorio_tarea.is_dir():
            candidatos.append({"categoria": categoria, "ruta": str(directorio_tarea.absolute())})
            continue
        intentos = sorted(directorio_tarea.iterdir())
        if not intentos and not any(token == directorio_tarea.name for token, _ in esperados):
            candidatos.append({"categoria": categoria, "ruta": str(directorio_tarea.absolute())})
        for intento in intentos:
            if (directorio_tarea.name, intento.name) not in esperados:
                candidatos.append({"categoria": categoria, "ruta": str(intento.absolute())})
    return candidatos


def reconciliar_huerfanos_almacenamiento() -> dict[str, Any]:
    """Report storage candidates without deleting or modifying existing data."""
    proyectos = _filas("proyectos", "id_repositorio")
    ejecuciones = _filas("ejecuciones_c4", "id")
    tareas = _filas("tareas_proyecto", "id,tipo,estado,intentos")

    repositorios_esperados = {
        obtener_raiz_repositorio(str(fila["id_repositorio"])).name for fila in proyectos
    }
    objetos_referenciados: set[str] = set()
    for token in repositorios_esperados:
        referencia = REPOS_DIR / token / "source.json"
        if not referencia.is_file():
            continue
        try:
            source_hash = json.loads(referencia.read_text(encoding="utf-8"))["source_hash"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(source_hash, str):
            objetos_referenciados.add(source_hash)
    ejecuciones_esperadas = {
        token_almacenamiento("execution", str(fila["id"])) for fila in ejecuciones
    }
    intentos_analisis: set[tuple[str, str]] = set()
    intentos_publicacion: set[tuple[str, str]] = set()
    for tarea in tareas:
        if tarea.get("estado") != "procesando" or int(tarea.get("intentos") or 0) < 1:
            continue
        if tarea.get("tipo") == "analisis_c4":
            intentos_analisis.add((
                token_almacenamiento("analysis-task", str(tarea["id"])),
                str(tarea["intentos"]),
            ))
        elif tarea.get("tipo") == "publicacion_c4":
            intentos_publicacion.add((
                token_almacenamiento("publication-task", str(tarea["id"])),
                str(tarea["intentos"]),
            ))

    candidatos = _candidatos_directos(REPOS_DIR, repositorios_esperados, "repositorio_sin_registro", {REPOSITORY_OBJECTS_DIR.name})
    candidatos.extend(_candidatos_directos(
        REPOSITORY_OBJECTS_DIR,
        objetos_referenciados,
        "objeto_fuente_sin_referencia",
    ))
    candidatos.extend(_candidatos_directos(C4_RUNS_DIR, ejecuciones_esperadas, "ejecucion_sin_registro"))
    candidatos.extend(_candidatos_intentos(C4_ANALYSIS_ATTEMPTS_DIR, intentos_analisis, "intento_analisis_inactivo"))
    candidatos.extend(_candidatos_intentos(C4_PUBLICATION_ATTEMPTS_DIR, intentos_publicacion, "intento_publicacion_inactivo"))
    candidatos.extend(_candidatos_directos(BASE_DIR / "uploads", set(), "upload_transitorio"))
    return {"modo": "dry-run", "total": len(candidatos), "candidatos": candidatos}
