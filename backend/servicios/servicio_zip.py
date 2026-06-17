import os
import stat
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from configuracion.rutas_repositorios import BASE_DIR, REPOS_DIR


UPLOADS_DIR = BASE_DIR / "uploads"

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))
MAX_ZIP_FILES = int(os.getenv("MAX_ZIP_FILES", "5000"))
MAX_EXTRACTED_BYTES = int(os.getenv("MAX_EXTRACTED_BYTES", str(1024 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE = 1024 * 1024

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(REPOS_DIR, exist_ok=True)


async def guardar_upload_en_disco(archivo: UploadFile, ruta_zip: Path) -> None:
    bytes_escritos = 0

    try:
        with open(ruta_zip, "wb") as buffer:
            while True:
                chunk = await archivo.read(UPLOAD_CHUNK_SIZE)

                if not chunk:
                    break

                bytes_escritos += len(chunk)

                if bytes_escritos > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="El archivo ZIP excede el tamaño máximo permitido",
                    )

                buffer.write(chunk)
    except HTTPException:
        ruta_zip.unlink(missing_ok=True)
        raise
    finally:
        await archivo.close()


def validar_nombre_zip(nombre_archivo: str | None) -> None:
    if not nombre_archivo:
        raise HTTPException(
            status_code=400,
            detail="El archivo no tiene nombre válido",
        )

    if not nombre_archivo.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Solo se permiten archivos .zip",
        )


def extraer_zip_seguro(ruta_zip: Path, ruta_destino: Path) -> None:
    destino_resuelto = ruta_destino.resolve()

    try:
        with zipfile.ZipFile(ruta_zip, "r") as zip_ref:
            miembros = zip_ref.infolist()

            if len(miembros) > MAX_ZIP_FILES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="El ZIP contiene demasiados archivos",
                )

            total_bytes = sum(miembro.file_size for miembro in miembros)

            if total_bytes > MAX_EXTRACTED_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="El contenido descomprimido excede el tamaño máximo permitido",
                )

            for miembro in miembros:
                ruta_relativa = Path(miembro.filename)
                modo = miembro.external_attr >> 16

                if ruta_relativa.is_absolute() or ruta_relativa.drive:
                    raise HTTPException(
                        status_code=400,
                        detail="El archivo ZIP contiene rutas absolutas no permitidas",
                    )

                if stat.S_ISLNK(modo):
                    raise HTTPException(
                        status_code=400,
                        detail="El archivo ZIP contiene enlaces simbólicos no permitidos",
                    )

                ruta_miembro = (destino_resuelto / miembro.filename).resolve()

                try:
                    ruta_miembro.relative_to(destino_resuelto)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="El archivo ZIP contiene rutas no permitidas",
                    )

            zip_ref.extractall(destino_resuelto)

    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="El archivo ZIP no es válido",
        )