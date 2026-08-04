import hashlib
import mimetypes
from pathlib import Path
from typing import Any


MEDIA_TYPES_C4 = {
    ".dsl": "text/plain; charset=utf-8",
    ".puml": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def metadata_artefacto(ruta: Path) -> dict[str, Any]:
    datos = ruta.read_bytes()
    return {
        "media_type": MEDIA_TYPES_C4.get(ruta.suffix.lower())
        or mimetypes.guess_type(ruta.name)[0]
        or "application/octet-stream",
        "sha256": hashlib.sha256(datos).hexdigest(),
        "size": len(datos),
    }
